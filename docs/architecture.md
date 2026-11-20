# Architecture

## Components

| Component | Responsibility | Runs as |
|---|---|---|
| **Frontend** (React, MapLibre) | UI: upload, map, analysis, jobs, dashboard. No image processing. | Vite dev server (`make frontend`) |
| **API** (FastAPI) | Validation, metadata extraction, storage, job creation, map tiles, result queries | Uvicorn (`make backend`) |
| **Worker** (Celery) | Object detection jobs: CPU/GPU-heavy work | Celery prefork pool (`make worker`), one or more processes or hosts |
| **PostgreSQL + PostGIS** | Image metadata, jobs, detections; spatial queries | Homebrew service |
| **MinIO** | Original GeoTIFF, Cloud Optimized GeoTIFF, preview PNG (S3 API) | `make minio`, bound to 127.0.0.1 |
| **RabbitMQ** | Job queue `analysis` and dead-letter queue `analysis.dead` | Homebrew service |

## Data flows

### Upload

1. The browser posts a multipart GeoTIFF to `POST /api/v1/images/upload`.
2. The API checks `Content-Length`, free disk space and the TIFF file signature, streams the file
   to a temporary file, and validates it with Rasterio: header-based size and band limits, CRS,
   geotransform, and that pixel data can be decoded.
3. It extracts metadata and computes the image footprint in EPSG:4326.
4. It converts the file to a COG and renders a preview PNG.
5. It uploads original, COG and preview to MinIO under `images/<uuid>/…`, then inserts the
   `images` row. If the insert fails, the uploaded objects are deleted again.

Steps 4–5 currently run in the request (in threads, not blocking the event loop). See the
limitations section below.

### Map display

`GET /api/v1/images/{id}/tilejson.json` gives bounds and zoom range. MapLibre then requests
`…/tiles/{z}/{x}/{y}.png`. rio-tiler reads only the needed byte ranges of the COG from MinIO (GDAL
`/vsis3/`), reprojects to Web Mercator, applies the image's stored contrast range, and returns a PNG
with NoData transparent. Detections are loaded as GeoJSON and drawn as vector layers.

### Analysis

1. `POST /api/v1/analysis` checks the image and rejects a second active analysis of the same image
   (409). It commits a job row with status `QUEUED`, then publishes a message containing only the
   job id (also used as the Celery task id). If publishing fails, the job is marked `FAILED` and the
   API returns 503.
2. A worker process takes the message, marks the job `RUNNING`, downloads the COG to a temporary
   directory, and runs the pipeline (tiling → model → merge → pixel→geo). It writes progress to the
   job row as tiles complete.
3. Detections replace any earlier detections of the same job in one transaction, and the job
   becomes `COMPLETED`.
4. The frontend polls `GET /api/v1/jobs?image_id=…` every second while a job is active, then
   reloads the detections.

## Reliability

| Mechanism | Implementation |
|---|---|
| No lost jobs | `acks_late` + `prefetch=1`: a message is acknowledged after the job finishes. `task_reject_on_worker_lost` redelivers if a worker dies. |
| No duplicate results | Jobs are idempotent: detections are replaced per job. A completed or cancelled job is skipped on redelivery. |
| Transient errors | Storage, database and network errors are retried up to 5 times with exponential backoff (10 s · 2ⁿ, capped at 600 s, 50–100 % jitter). The job shows `QUEUED` with a retry message in between. |
| Deterministic errors | Corrupt data, missing objects or model errors fail the job at once (`FAILED` with error message), without retries. |
| Dead-lettering | Failed or rejected messages are rejected without requeue, and RabbitMQ moves them to `analysis.dead`. Unknown job ids are rejected the same way. |
| Timeouts | Soft limit 1 h, hard limit 1 h 5 min per job (configurable). |
| Startup | Each worker process loads and checksum-verifies the model once at start-up and reuses it for every job. |

## Technology choices

- **No Docker.** By the project owner's decision, all services run natively (Homebrew). The
  original specification's Docker Compose and Kubernetes milestones are therefore not implemented.
- **No Redis.** Celery runs without a result backend. Job state (status, progress, errors) lives in
  PostgreSQL, where the API and UI read it.
- **Tile server inside the API** (rio-tiler) instead of a separate service. This is simple for a
  single machine and can be split out later.
- **MinIO.** The Homebrew formula is deprecated (the upstream repository is archived). The code
  uses only the standard S3 API through boto3, so any S3-compatible store works by changing
  `S3_ENDPOINT_URL`.
- **YOLO OBB on DOTA** as the baseline model, because it is trained on overhead imagery and
  predicts oriented boxes. A generic COCO model is not suitable for nadir imagery. The pipeline
  depends only on an `ObjectDetector` interface (see [ml-pipeline.md](ml-pipeline.md)).

## Scaling strategy

- **Workers** scale horizontally: run more processes (`WORKER_CONCURRENCY`) or more hosts
  consuming the same queue. Each process holds one job at a time (`prefetch=1`) and one copy of the
  model (about 1.8 GB peak resident memory per process on CPU). Use a GPU (`DETECTION_DEVICE=cuda:0`)
  for throughput.
- **Memory** per job is bounded by the tile size, not the image size: windows are read one batch at
  a time. Raster validation rejects images above configurable pixel and decompressed-size limits.
- **Large images**: move COG creation into the worker, process tiles of one job across several
  workers (fan-out/fan-in), and stream the COG with range reads instead of downloading it.
- **Map tiles**: add an HTTP cache or CDN in front of the tile endpoint (tiles are immutable per
  image), or run the tile service separately.
- **Queue**: switch to RabbitMQ quorum queues with a delivery limit, to stop jobs that repeatedly
  crash workers.
- **Database**: detections are indexed by geometry (GiST), job and image. Queries are paginated.

## Current limitations

See the README's *Known limitations* section. The main architectural one is that COG conversion
runs during the upload request.
