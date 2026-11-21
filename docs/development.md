# Development

Everything runs natively. The project was developed and tested on macOS (Apple Silicon) with
Homebrew. For Linux and Windows (WSL2), see the README section
[Linux and Windows](../README.md#linux-and-windows). Those instructions have not been verified.

## Requirements

| Tool | Version used | Install |
|---|---|---|
| Python | 3.12 | `brew install python@3.12` |
| Node.js | 24 (jsdom wants ≥ 24.15 or 22.22) | nodejs.org or `brew install node` |
| PostgreSQL + PostGIS | 17 + 3.7 | `brew install postgresql@17 postgis` |
| RabbitMQ | 4.4 | `brew install rabbitmq` |
| MinIO | 2025-10-15 | `brew install minio` (deprecated Homebrew formula; see troubleshooting) |
| GDAL CLI (optional) | 3.13 | `brew install gdal` (Rasterio wheels bundle their own GDAL) |

Disk: about 3 GB for Python packages (PyTorch) and node_modules.

## Setup

```bash
brew link --force postgresql@17   # keg-only formula: puts psql, createdb etc. on PATH
brew services start postgresql@17
brew services start rabbitmq

/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e "backend[dev]"
(cd frontend && npm install)

cp .env.example .env && chmod 600 .env   # then replace every change-me value

createuser --pwprompt satellite_detection           # password = the one in DATABASE_URL / TEST_DATABASE_URL
createdb --owner satellite_detection satellite_detection
createdb --owner satellite_detection satellite_detection_test
psql -d satellite_detection -c "CREATE EXTENSION postgis;"
psql -d satellite_detection_test -c "CREATE EXTENSION postgis;"
make migrate

make model      # detector weights → data/models (SHA-256 verified)
make samples    # sample imagery → data/samples
```

## Configuration

All backend settings come from environment variables or `.env` in the repository root (see
`backend/app/config.py`). Main settings:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | required | `postgresql+asyncpg://satellite_detection:…@localhost:5432/satellite_detection` |
| `TEST_DATABASE_URL` | unset | Integration tests are skipped if unset. The database name must end in `_test`. |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672//` | |
| `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | `http://127.0.0.1:9000`, required, required, `satellite-detection` | Any S3-compatible store |
| `MAX_UPLOAD_BYTES`, `MAX_RASTER_PIXELS`, `MAX_RASTER_BANDS`, `MAX_UNCOMPRESSED_BYTES`, `MIN_FREE_DISK_BYTES` | 2 GiB, 5·10⁸, 16, 8 GiB, 2 GiB | Upload protection |
| `DETECTION_MODEL_PATH`, `DETECTION_MODEL_SHA256` | `data/models/yolo26s-obb.pt`, pinned | Set the hash to empty to allow other weights |
| `DETECTION_DEVICE` | `cpu` | `mps` (Apple GPU) or `cuda:0` |
| `DETECTION_TILE_SIZE`, `DETECTION_TILE_OVERLAP`, `DETECTION_BATCH_SIZE` | 1024, 128, 4 | |
| `DETECTION_CONFIDENCE`, `DETECTION_IOU_THRESHOLD` | 0.25, 0.5 | |
| `ANALYSIS_QUEUE`, `WORKER_CONCURRENCY` | `analysis`, 1 | |
| `JOB_MAX_RETRIES`, `JOB_RETRY_BACKOFF_SECONDS`, `JOB_RETRY_BACKOFF_MAX_SECONDS` | 5, 10, 600 | Transient errors only |
| `JOB_SOFT_TIME_LIMIT_SECONDS`, `JOB_TIME_LIMIT_SECONDS` | 3600, 3900 | |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list |

Frontend (Vite, optional): `VITE_BASEMAP_URL` (XYZ template for the basemap) and `VITE_GLYPHS_URL`
(MapLibre font glyphs).

## Running

```bash
make minio          # terminal 1: MinIO on 127.0.0.1:9000, console on :9001, data in data/minio
make init-storage   # once: create the bucket
make backend        # terminal 2: API on 127.0.0.1:8000 with auto-reload, docs at /docs
make worker         # terminal 3: Celery worker (WORKER_CONCURRENCY=2 make worker for two jobs)
make frontend       # terminal 4: http://localhost:5173
```

Without the queue, `make detect IMAGE=<image id>` runs a detection job directly from the command
line.

## Loading sample imagery

With the API and a worker running, `make init-storage` (once) and then **`make demo`** load the demo
data: the sample images are downloaded if missing, uploaded through the API and analysed. Every
machine gets identical results, because the sample sources are pinned STAC items and the model
weights are checksum-verified. Running `make demo` again skips what already exists. Point it at
another API with `API_URL=http://host:port make demo`.

`make samples` only downloads the images into `data/samples/` (see
[../datasets/README.md](../datasets/README.md)). To upload one manually:

```bash
curl -F "file=@data/samples/naip_lax_2024.tif" http://127.0.0.1:8000/api/v1/images/upload
```

`python -m scripts.download_samples naip_lax_2024.tif` (from `backend/`) downloads a single sample.

## Tests

```bash
make test            # backend + frontend
make test-backend    # pytest
make test-frontend   # vitest
make lint            # ruff check, ruff format --check, mypy --strict, eslint, prettier --check, tsc
```

Backend test groups:

| Files | Needs |
|---|---|
| `test_raster.py`, `test_geospatial.py`, `test_tiles.py`, `test_ml.py` (most), `test_health.py` | Nothing: deterministic synthetic rasters |
| `test_database.py`, `test_images_api.py`, `test_detection_jobs.py`, `test_jobs_api.py`, `test_stats.py` | PostGIS (`TEST_DATABASE_URL`) and MinIO (bucket `satellite-detection-test`) |
| `test_ml.py` (real model), `test_images_api.py` (real NAIP) | `make model`, `make samples` |
| `test_worker_e2e.py` | All of the above plus RabbitMQ. Starts its own worker on queue `analysis-test`. |

Tests skip with a reason when a requirement is missing. The test database is wiped and re-migrated
on each run, and the test bucket and queues are cleaned up. A running development worker is not
affected.

The frontend tests replace the MapLibre map with a stub (jsdom has no WebGL), so map rendering
itself is verified manually in a browser.

Model evaluation: `make evaluate` (see [ml-pipeline.md](ml-pipeline.md)).

## Troubleshooting

| Problem | Fix |
|---|---|
| `psql: command not found` | `brew link --force postgresql@17` (the versioned formula is keg-only) |
| `brew install minio/stable/minio` fails with HTTP 410 | MinIO no longer publishes binaries there. Use `brew install minio` (Homebrew's own, deprecated build) or any S3-compatible store such as SeaweedFS, and set `S3_ENDPOINT_URL`. |
| `/health/ready` reports that the bucket does not exist | `make init-storage` (with MinIO running) |
| Migration fails: "PostGIS missing" | `psql -d satellite_detection -c "CREATE EXTENSION postgis;"` as your superuser |
| No outlines on the map, console shows "Worker failed to load" | Hard-reload the page (Cmd+Shift+R). The MapLibre worker URL is set at module load, and hot reload does not reset it. |
| Analysis stays "I kø" (queued) | No worker is running on the queue: `make worker`. Check `rabbitmqctl list_queues name messages consumers`. |
| Job failed: "Model weights not found" | `make model` |
| Imagery does not show when zoomed out | Images appear from their minimum zoom (e.g. z15 for 0.6 m NAIP). Click the image name to zoom to it. |
| `npm warn EBADENGINE` for jsdom | Node is older than 24.15. Tests still run. Upgrade Node to silence it. |
| VS Code: "Import app.api could not be resolved" | Select `.venv` as the Python interpreter |
| Inspect dead-lettered messages | `rabbitmqctl list_queues name messages`, then the RabbitMQ management UI or a consumer on `analysis.dead` |
