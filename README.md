# Satellite Object Detection

Satellite Object Detection is a full-stack geospatial application for uploading georeferenced imagery, viewing it on
an interactive map, and finding objects such as aircraft, ships, vehicles and storage tanks with a
computer-vision model. Detections are stored as geographic polygons in PostGIS and can be filtered,
inspected and exported as GeoJSON.

![Aircraft detected at San Francisco International Airport, shown on the map](docs/images/map-detections.jpg)

*NAIP aerial imagery (0.6 m, USDA, public domain) of San Francisco International Airport over an
OpenStreetMap basemap. Each outline is a detection from the pretrained YOLO26-s OBB model.*

## Features

- **Upload GeoTIFFs**, validated as untrusted input. Metadata is extracted, and the original and a
  Cloud Optimized GeoTIFF are stored in S3-compatible object storage (MinIO).
- **View imagery on a map** (MapLibre). Map tiles are read directly from the COG and reprojected to
  Web Mercator.
- **Detect objects** with a pretrained oriented-bounding-box YOLO model (DOTA v1 classes). Large
  images are processed in overlapping tiles, duplicates are merged, and boxes are converted to
  geographic polygons.
- **Run analyses as background jobs** (RabbitMQ + Celery) with real progress, retries for transient
  errors and a dead-letter queue.
- **Explore results** with class filters, confidence filters, an object table that zooms the map to
  each object, a job monitor, a dashboard and GeoJSON export.

| Analysis page | Dashboard |
|---|---|
| ![Analysis page](docs/images/analysis.jpg) | ![Dashboard](docs/images/dashboard.jpg) |

## Architecture

```text
Browser (React, MapLibre)
        │  REST (JSON, GeoJSON, PNG tiles)
        ▼
FastAPI ──────────────► PostgreSQL + PostGIS   images, jobs, detections (EPSG:4326)
   │   │
   │   └──────────────► MinIO (S3 API)         original GeoTIFF, COG, preview
   │                         ▲
   │ job id only             │ read COG
   ▼                         │
RabbitMQ ──► Celery worker(s): tiling → YOLO OBB → merge → pixel→geo → PostGIS
```

The API does not process imagery for analysis; workers do, and queue messages carry only a job id.
Details: [docs/architecture.md](docs/architecture.md).

| Area | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, MapLibre GL JS, TanStack Query, Zustand |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, GeoAlchemy2 |
| Data and jobs | PostgreSQL 17 + PostGIS, MinIO, RabbitMQ, Celery |
| Geospatial | GDAL (via Rasterio), rio-tiler, PyProj, Shapely |
| Computer vision | PyTorch, Ultralytics YOLO26-s OBB, OpenCV |

## Quick start (macOS)

Requires [Homebrew](https://brew.sh) and Node.js 24. Everything runs natively; Docker is not used.

```bash
brew install python@3.12 postgresql@17 postgis rabbitmq minio
brew services start postgresql@17 && brew services start rabbitmq

/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e "backend[dev]"
(cd frontend && npm install)

cp .env.example .env    # then replace the change-me values

createuser --pwprompt satellite_detection   # same password as in DATABASE_URL
createdb --owner satellite_detection satellite_detection
psql -d satellite_detection -c "CREATE EXTENSION postgis;"
make migrate
make model samples      # model weights and sample imagery
```

Run each in its own terminal, and run `make init-storage` once after MinIO has started:

```bash
make minio      # object storage
make backend    # API on http://127.0.0.1:8000 (docs at /docs)
make worker     # analysis jobs
make frontend   # UI on http://localhost:5173
```

Upload a file from `data/samples/` on **Bilder**, open it on **Analyse**, and click
**Finn objekter i bildet**. The test database, configuration and troubleshooting are covered in
[docs/development.md](docs/development.md).

## Tests

```bash
make test   # pytest + Vitest
make lint   # Ruff, mypy --strict, ESLint, Prettier, tsc
```

The tests include integration and end-to-end tests against a real PostGIS database, MinIO,
RabbitMQ, a Celery worker process and the model.

## Model

The detector is Ultralytics **YOLO26-s OBB**, pretrained on **DOTA v1** (15 classes). On 0.6 m
NAIP imagery of four US airports it found nearly all parked aircraft, most with confidence above
0.9. Most false positives scored below 0.5, so the map shows detections from 50 % by default. On
CPU, inference takes about 170 ms per 1024 × 1024 tile.

The accuracy numbers from `make evaluate` are **not** an estimate of real-world accuracy: the
labelled sample is small and comes from the model's own training data. See
[docs/ml-pipeline.md](docs/ml-pipeline.md).

## Limitations

- **No authentication. Run it only on a trusted machine, and never expose it to a network.**
- Not implemented yet: change detection, Kubernetes, CI/CD and monitoring.
- COG conversion runs during upload rather than in a worker, so very large files upload slowly.
- Only the 15 DOTA classes can be detected, and small vehicles are rarely found at 0.6 m.
  Confidence is a model score, not a probability.

## Licences and data

- **Ultralytics YOLO is AGPL-3.0.** Distributing this application, or offering it as a network
  service, brings AGPL obligations.
- The model weights are trained on **DOTA**, which is for academic use only.
- NAIP imagery is public domain. Basemap © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors.
- No data, model weights or secrets are committed.

## Documentation

[Architecture](docs/architecture.md) · [API](docs/api.md) · [Data model](docs/data-model.md) ·
[Geospatial processing](docs/geospatial.md) · [ML pipeline](docs/ml-pipeline.md) ·
[Security](docs/security.md) · [Development](docs/development.md) ·
[Datasets](datasets/README.md) · [Specification](docs/specification.md)
