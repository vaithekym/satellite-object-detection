# Satellite Object Detection – AI-Powered Satellite Imagery Analysis Platform

## 1. Project Overview

Satellite Object Detection is a fullstack geospatial intelligence platform designed to process, analyze, and visualize satellite and aerial imagery using computer vision, machine learning, and distributed systems.

The project is inspired by real-world challenges in Imagery Intelligence (IMINT) and remote sensing.

The objective is to build a production-oriented, modular application that demonstrates:

- Fullstack software engineering
- Geospatial data processing
- Computer vision and object detection
- Satellite imagery analysis
- Distributed and asynchronous processing
- Spatial databases
- Interactive geospatial visualization
- Containerization and Kubernetes
- Security, observability, testing, and CI/CD

---

# 2. Primary Objectives

Build a web-based application where users can:

1. Upload georeferenced satellite imagery.
2. View imagery on an interactive map.
3. Inspect geographic metadata.
4. Start asynchronous image analysis jobs.
5. Detect objects using computer vision models.
6. Visualize detected objects with bounding boxes.
7. Inspect model confidence scores and object classifications.
8. Compare imagery captured at different times.
9. Detect and visualize geographic changes.
10. Search, filter, and explore analysis results.
11. Monitor image processing jobs.
12. Export results as GeoJSON.
13. Manage large imagery datasets efficiently.

The application should demonstrate realistic software engineering practices suitable for a technical portfolio.

---

# 3. Technology Stack

## Frontend

Use:

- React
- TypeScript
- Vite
- Tailwind CSS
- MapLibre GL JS
- TanStack Query
- Zustand
- Axios
- React Router
- Vitest
- React Testing Library

The frontend must be responsive, modern, and suitable for professional geospatial analysis workflows.

## Backend

Use:

- Python 3.12
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- PostgreSQL
- PostGIS
- RabbitMQ
- Celery
- Redis, only if justified by an actual requirement

FastAPI must provide typed REST endpoints with automatic OpenAPI documentation.

Use asynchronous database access where appropriate.

## Geospatial Processing

Use:

- GDAL
- Rasterio
- GeoPandas
- Shapely
- PyProj
- NumPy

Support:

- GeoTIFF
- Cloud Optimized GeoTIFF (COG)
- Geographic coordinate systems
- Raster reprojection
- Raster tiling
- Bounding box extraction
- Spatial metadata extraction
- GeoJSON

## Computer Vision

Use:

- PyTorch
- OpenCV
- Ultralytics YOLO
- NumPy
- Pillow

The initial implementation should use a pretrained model.

Support custom model integration and future fine-tuning.

Do not assume that a generic pretrained YOLO model can reliably detect all satellite imagery object classes.

## Infrastructure

Use:

- Docker
- Docker Compose
- Kubernetes
- GitHub Actions
- MinIO for local S3-compatible object storage
- Prometheus for optional monitoring

All core services must be runnable locally through Docker Compose.

Kubernetes deployment is a later milestone.

---

# 4. High-Level Architecture

Implement the following architecture:

```text
                     USER
                      |
                      v
              React / TypeScript
                      |
                      v
                 FastAPI
                      |
        +-------------+-------------+
        |             |             |
        v             v             v
    PostgreSQL      MinIO        RabbitMQ
     PostGIS      Object Store      |
        ^             ^             v
        |             |       Celery Workers
        |             |             |
        |             +-------------+
        |                           |
        |                    Image Processing
        |                           |
        |                  +--------+--------+
        |                  |        |        |
        |                 GDAL    OpenCV    YOLO
        |                  |        |        |
        +------------------+--------+--------+
```

Architecture requirements:

- The frontend must not perform heavy image processing.
- FastAPI handles validation, metadata, job creation, and result retrieval.
- Large raster files must be stored in object storage.
- RabbitMQ messages must contain references to files, not raw imagery.
- Celery workers must perform CPU/GPU-intensive operations.
- PostgreSQL stores metadata and structured analysis results.
- PostGIS stores geographic geometries.
- The frontend retrieves analysis results through REST APIs.
- The architecture must allow multiple processing workers.

---

# 5. Repository Structure

Create the following structure:

```text
satellite-object-detection/
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   ├── map/
│   │   │   ├── imagery/
│   │   │   ├── analysis/
│   │   │   └── jobs/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── ImageryExplorer.tsx
│   │   │   ├── AnalysisPage.tsx
│   │   │   └── JobsPage.tsx
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── store/
│   │   ├── types/
│   │   └── utils/
│   └── tests/
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── geospatial/
│   │   ├── ml/
│   │   ├── workers/
│   │   └── db/
│   └── tests/
│
├── infrastructure/
│   ├── kubernetes/
│   ├── monitoring/
│   └── scripts/
│
├── datasets/
│   └── README.md
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── data-model.md
│   ├── ml-pipeline.md
│   ├── security.md
│   └── development.md
│
└── .github/
    └── workflows/
        └── ci.yml
```

The structure can be adjusted if necessary, but maintain clear separation of responsibilities.

---

# 6. Implementation Phase 1 – Project Initialization

## Step 1.1 – Initialize Repository

Create a Git repository.

Configure:

- Python and Node.js environments
- Dependency management
- Git ignore rules
- Environment variables
- Linting
- Formatting
- Type checking
- Basic CI

Use Ruff for Python linting and formatting.

Use ESLint and Prettier for frontend code.

## Step 1.2 – Configure Docker Compose

Create services for:

- frontend
- backend
- worker
- PostgreSQL with PostGIS
- RabbitMQ
- MinIO

Use persistent volumes for PostgreSQL, RabbitMQ, and MinIO.

Configure service health checks and startup dependencies.

Provide a `.env.example` file with all required environment variables.

Never commit real credentials.

## Step 1.3 – Create Backend Health Endpoints

Implement:

```http
GET /health/live
GET /health/ready
```

Readiness must verify required dependencies.

## Acceptance Criteria

- Docker Compose starts successfully.
- Frontend is accessible.
- FastAPI documentation is accessible at `/docs`.
- PostgreSQL and PostGIS are operational.
- RabbitMQ and MinIO are reachable.
- All containers pass health checks.

---

# 7. Implementation Phase 2 – Database Design

Use PostgreSQL with PostGIS.

Create Alembic migrations.

## Table: images

Fields:

```text
id UUID PRIMARY KEY
filename VARCHAR
object_key VARCHAR
content_type VARCHAR
file_size BIGINT
width INTEGER
height INTEGER
crs VARCHAR
resolution_x DOUBLE PRECISION
resolution_y DOUBLE PRECISION
bounds GEOMETRY(POLYGON, 4326)
acquisition_date TIMESTAMP NULL
uploaded_at TIMESTAMP
processing_status VARCHAR
metadata JSONB
```

Store image footprints as geographic polygons.

Add a spatial GiST index on bounds.

## Table: analysis_jobs

```text
id UUID PRIMARY KEY
image_id UUID
job_type VARCHAR
status VARCHAR
progress INTEGER
model_name VARCHAR NULL
model_version VARCHAR NULL
parameters JSONB
error_message TEXT NULL
created_at TIMESTAMP
started_at TIMESTAMP NULL
completed_at TIMESTAMP NULL
```

Supported statuses:

```text
PENDING
QUEUED
RUNNING
COMPLETED
FAILED
CANCELLED
```

## Table: detections

```text
id UUID PRIMARY KEY
image_id UUID
job_id UUID
class_name VARCHAR
class_id INTEGER
confidence FLOAT
pixel_bbox JSONB
geometry GEOMETRY(POLYGON, 4326)
created_at TIMESTAMP
```

Store both pixel-space and geographic bounding boxes.

Create spatial indexes.

## Table: change_detections

```text
id UUID PRIMARY KEY
before_image_id UUID
after_image_id UUID
job_id UUID
change_type VARCHAR
confidence FLOAT NULL
geometry GEOMETRY(GEOMETRY, 4326)
area_sqm DOUBLE PRECISION NULL
created_at TIMESTAMP
```

Use foreign keys and appropriate constraints.

## Acceptance Criteria

- Migrations execute successfully.
- Spatial queries work.
- Image metadata can be inserted and retrieved.
- Detections can be queried by geographic bounding box.

---

# 8. Implementation Phase 3 – Satellite Imagery Upload

## Step 3.1 – Upload API

Implement:

```http
POST /api/v1/images/upload
```

Accept GeoTIFF files initially.

Return:

```json
{
  "id": "image-uuid",
  "filename": "satellite_image.tif",
  "status": "uploaded"
}
```

The UUID must be generated dynamically.

## Step 3.2 – Validate Uploaded Files

Validate:

- File type and actual file signature
- Maximum file size
- Raster readability
- Raster dimensions
- Coordinate reference system
- Supported number of raster bands
- Available disk and processing resources

Reject corrupted or unsupported files.

Apply upload limits and protect against decompression bombs.

## Step 3.3 – Extract Metadata

Use Rasterio/GDAL to extract:

- Width and height
- Number of bands
- CRS
- Pixel resolution
- Bounds
- NoData values
- Data type
- Acquisition timestamp, if available

Do not invent missing acquisition dates.

## Step 3.4 – Store Image

Store the original file in MinIO.

Save its object key and metadata in PostgreSQL.

Generate a preview image and a map-compatible raster representation.

Prefer Cloud Optimized GeoTIFF for efficient raster access.

## Acceptance Criteria

- A real GeoTIFF can be uploaded.
- Metadata is correctly extracted.
- The original image is stored in MinIO.
- The image is visible in the image library.
- Invalid files are rejected safely.

---

# 9. Implementation Phase 4 – Geospatial Processing

Create a reusable geospatial processing module.

## Step 4.1 – Raster Reading

Implement functions for:

```python
read_raster()
get_raster_metadata()
get_raster_bounds()
reproject_raster()
create_raster_tiles()
create_cog()
pixel_to_geo()
geo_to_pixel()
```

Use Rasterio and GDAL.

## Step 4.2 – Coordinate Systems

Support:

- EPSG:4326
- EPSG:3857
- Original source CRS
- Other valid projected CRS through PyProj

Handle transformations correctly.

Never assume that image pixel coordinates are geographic coordinates.

## Step 4.3 – Raster Tiling

Large satellite images must be processed in smaller windows.

Implement configurable tile sizes:

```text
256 x 256
512 x 512
1024 x 1024
```

Support overlapping tiles.

Handle edge tiles and NoData regions.

Avoid loading an entire large raster into memory unnecessarily.

## Step 4.4 – Visualization

Create a map-compatible tile endpoint or integrate a suitable COG tile server.

Use MapLibre GL JS to display imagery.

Correctly handle raster bounds, reprojection, and map tile coordinates.

## Acceptance Criteria

- GeoTIFF metadata is correct.
- Raster reprojection works.
- Large images can be processed in windows.
- Raster imagery aligns correctly with map coordinates.
- Pixel-to-geographic coordinate conversion is tested.

---

# 10. Implementation Phase 5 – Computer Vision

Implement a modular computer vision pipeline.

## Step 5.1 – Model Integration

Use a pretrained YOLO model as the initial baseline.

Create an interface similar to:

```python
class ObjectDetector:
    def load_model(self):
        ...

    def predict(self, image):
        ...

    def postprocess(self, predictions):
        ...
```

Separate model loading from inference.

Load the model once per worker process rather than once per image tile.

## Step 5.2 – Satellite Image Preprocessing

Implement:

- Band selection
- RGB conversion
- Normalization
- Tiling
- Optional resizing
- NoData masking

Preserve transformations required to map predictions back to the original image.

Document how imagery with more than three spectral bands is handled.

## Step 5.3 – Object Detection

For each image:

1. Read the source raster.
2. Generate overlapping tiles.
3. Prepare tiles for inference.
4. Run object detection.
5. Convert tile-local bounding boxes to global pixel coordinates.
6. Merge overlapping predictions using NMS or an equivalent strategy.
7. Convert detections to geographic geometries.
8. Save results in PostGIS.
9. Return results through the API.

The model must return actual predictions.

Never generate random bounding boxes.

## Step 5.4 – Model Limitations

A generic YOLO model is not sufficient for reliable satellite object detection.

Implement a model adapter that supports future replacement with a remote-sensing-specific model.

Use a suitable publicly available dataset such as:

- xView
- DOTA
- SpaceNet

Follow each dataset's licensing and access requirements.

Start with a small, reproducible subset.

## Step 5.5 – Model Evaluation

Implement evaluation metrics:

- Precision
- Recall
- F1-score
- mAP@0.5
- mAP@0.5:0.95
- Inference time
- Throughput

Evaluate only on labeled validation data.

Do not present confidence scores as proof that a prediction is correct.

## Acceptance Criteria

- Real model inference works.
- Bounding boxes correspond to image locations.
- Geographic coordinates are correctly generated.
- Detections are persisted in PostGIS.
- Results are available as GeoJSON.
- The pipeline supports CPU execution.

GPU acceleration is optional.

---

# 11. Implementation Phase 6 – Asynchronous Processing

Use RabbitMQ with Celery.

## Step 6.1 – Job Creation

Implement:

```http
POST /api/v1/analysis
```

Request:

```json
{
  "image_id": "uuid",
  "analysis_type": "object_detection",
  "model": "default"
}
```

Response:

```http
202 Accepted
```

```json
{
  "job_id": "uuid",
  "status": "QUEUED"
}
```

## Step 6.2 – Worker Processing

The worker must:

1. Receive a queued job.
2. Fetch image metadata.
3. Read imagery from MinIO.
4. Execute preprocessing.
5. Run model inference.
6. Persist detections.
7. Update progress.
8. Mark the job completed or failed.

## Step 6.3 – Reliability

Implement:

- Retry policies
- Exponential backoff
- Dead-letter handling
- Idempotent job processing
- Job timeouts
- Structured error reporting
- Worker concurrency configuration

Ensure retries do not create duplicate detections.

Avoid unsafe automatic retries for deterministic failures.

## Step 6.4 – Job Monitoring

Implement:

```http
GET /api/v1/jobs
GET /api/v1/jobs/{job_id}
```

Return:

```json
{
  "job_id": "uuid",
  "status": "RUNNING",
  "progress": 65,
  "message": "Processing image tiles"
}
```

Progress must represent actual processing progress.

## Acceptance Criteria

- Jobs execute asynchronously.
- Multiple jobs can be queued.
- Multiple workers can process independent jobs.
- Failed jobs are reported.
- Retried jobs do not duplicate results.
- Frontend displays actual job progress.

---

# 12. Implementation Phase 7 – Interactive Frontend

Create a professional geospatial analysis interface.

## Page 1 – Dashboard

Display:

- Total uploaded images
- Completed analyses
- Pending jobs
- Failed jobs
- Total detections
- Recent activity

All statistics must come from the backend.

## Page 2 – Imagery Explorer

Implement:

- Interactive MapLibre map
- Satellite imagery overlays
- Image selection
- Zoom and pan
- Geographic coordinate display
- Layer visibility controls
- Image metadata panel

## Page 3 – Image Analysis

Allow the user to:

1. Select an uploaded image.
2. Choose an analysis type.
3. Start processing.
4. Monitor progress.
5. View detections on the image.
6. Filter detections by class.
7. Filter by confidence.
8. Click a detection for details.
9. Export detections as GeoJSON.

## Page 4 – Job Monitor

Display:

- Job ID
- Job type
- Image
- Status
- Progress
- Start time
- Completion time
- Error messages

Implement polling with TanStack Query.

WebSockets may be added later.

## UI Requirements

Use a clean, professional dashboard design.

Include:

- Sidebar navigation
- Responsive layout
- Loading indicators
- Empty states
- Error handling
- Toast notifications
- Accessible controls
- Dark mode

Do not populate dashboards with fabricated production data.

---

# 13. Implementation Phase 8 – Change Detection

Implement comparison of two satellite images.

## Step 8.1 – Image Selection

Allow users to select:

- Before image
- After image

Both images must cover an overlapping geographic area.

## Step 8.2 – Image Alignment

Perform:

1. CRS validation.
2. Geographic overlap calculation.
3. Reprojection to a common grid.
4. Resolution alignment.
5. Pixel registration checks.
6. NoData masking.

## Step 8.3 – Change Detection Algorithm

Start with a baseline method using:

- Absolute pixel differences
- Thresholding
- Morphological filtering
- Connected components

For multispectral Sentinel-2 imagery, optionally implement NDVI or other spectral-index differences.

Document limitations caused by:

- Clouds
- Shadows
- Seasonal changes
- Illumination
- Misregistration
- Different sensors

Do not classify every pixel difference as a real-world object change.

## Step 8.4 – Visualization

Implement:

- Before/after comparison
- Opacity slider
- Highlighted change regions
- Change area statistics
- GeoJSON export

## Acceptance Criteria

- Two real georeferenced images can be compared.
- Spatial alignment is verified.
- Changes are computed from actual pixel values.
- Detected change regions are displayed on the map.
- False positives and limitations are documented.

---

# 14. Implementation Phase 9 – Security

Apply secure software engineering practices.

Implement:

- Strict file validation
- Upload size limits
- Request validation
- Safe object storage keys
- SQL injection protection
- CORS configuration
- Secure environment variable handling
- Least-privilege database access
- Container security
- Dependency vulnerability scanning
- Safe error responses
- Resource limits for image processing

Never execute arbitrary commands derived from uploaded filenames or metadata.

Treat uploaded raster files as untrusted input.

Do not expose RabbitMQ, PostgreSQL, or MinIO administrative interfaces publicly.

For local development, document that the application runs in a trusted environment.

If authentication is not implemented in the MVP, clearly state that the application must not be exposed publicly.

---

# 15. Implementation Phase 10 – Testing

Create automated tests for each major subsystem.

## Backend Tests

Use pytest.

Test:

- Health endpoints
- Upload validation
- Metadata extraction
- CRS transformations
- Raster tiling
- Database operations
- Job lifecycle
- Error handling
- GeoJSON serialization

## Computer Vision Tests

Test:

- Image preprocessing
- Bounding box transformations
- Tile offset calculations
- Overlapping detection merging
- Model loading
- Inference result structure

Use deterministic fixtures for unit tests.

Use a small real image for integration tests.

## Frontend Tests

Use Vitest and React Testing Library.

Test:

- Image upload interface
- Job status display
- Filtering
- Error states
- API integration behavior

## Integration Tests

Test the full workflow:

```text
Upload GeoTIFF
       |
       v
Store in MinIO
       |
       v
Save metadata in PostGIS
       |
       v
Create analysis job
       |
       v
Publish to RabbitMQ
       |
       v
Worker executes inference
       |
       v
Save detections
       |
       v
Retrieve GeoJSON
       |
       v
Display detections on map
```

At least one end-to-end test must use real raster data.

---

# 16. Implementation Phase 11 – Kubernetes

After Docker Compose works, create Kubernetes manifests.

Include:

- Frontend Deployment
- Backend Deployment
- Worker Deployment
- Services
- ConfigMaps
- Secret references
- Resource requests and limits
- Liveness and readiness probes

Use persistent storage for stateful services.

For local development, use kind or Minikube.

Do not claim production readiness simply because Kubernetes manifests exist.

Document scaling considerations for workers and large raster processing.

---

# 17. Implementation Phase 12 – CI/CD

Create GitHub Actions workflows.

On pull requests and pushes:

1. Install dependencies.
2. Run Python linting.
3. Run Python type checks.
4. Run backend unit tests.
5. Run frontend linting.
6. Run TypeScript type checks.
7. Run frontend tests.
8. Build Docker images.
9. Run security checks where practical.

Use caching to improve execution time.

Do not require real cloud credentials for CI.

---

# 18. Public Datasets

Use publicly available imagery.

Recommended sources:

### Sentinel-2

Suitable for:

- Land cover analysis
- Vegetation monitoring
- Large-scale change detection
- Remote sensing workflows

Typical spatial resolution is 10–60 meters depending on the band.

Do not use Sentinel-2 as the primary dataset for detecting individual cars.

### xView

Suitable for:

- Small object detection
- Satellite imagery computer vision
- Object classification

Check dataset terms before use.

### DOTA

Suitable for:

- Aerial object detection
- Rotated bounding boxes
- Dense object scenes

### SpaceNet

Suitable for:

- Building footprint extraction
- Road extraction
- Geospatial machine learning

Implement dataset download instructions.

Do not automatically download extremely large datasets.

Provide a small, reproducible sample dataset workflow.

---

# 19. Performance Requirements

The platform must be designed to process large images efficiently.

Implement:

- Windowed raster reads
- Configurable tile sizes
- Bounded memory usage
- Background processing
- Efficient database queries
- Spatial indexes
- Pagination
- Caching where appropriate
- Batch database inserts
- Model reuse between jobs

Measure:

- Image upload time
- Metadata extraction time
- Processing time per tile
- Total inference time
- Database query latency
- Memory usage
- Worker throughput

Include a benchmark script.

Do not invent benchmark results.

---

# 20. Documentation Requirements

Create documentation covering:

## Architecture

Explain:

- System components
- Data flow
- Service responsibilities
- Technology choices
- Scaling strategy

## API

Document:

- Endpoints
- Request schemas
- Response schemas
- Error codes
- Example requests

## Machine Learning

Document:

- Model selection
- Preprocessing
- Inference
- Postprocessing
- Evaluation
- Known limitations

## Geospatial Processing

Document:

- CRS
- GeoTIFF
- COG
- Raster tiling
- Coordinate transformations
- GeoJSON

## Development

Document:

- Installation
- Environment configuration
- Running Docker Compose
- Running migrations
- Loading sample imagery
- Running tests
- Troubleshooting

---

## Development Priorities

Implement in this order:

**Priority 1: Working infrastructure**

- Docker Compose
- FastAPI
- React
- PostgreSQL/PostGIS
- RabbitMQ
- MinIO

**Priority 2: Real imagery workflow**

- Upload
- Validation
- Metadata extraction
- Storage
- Map visualization

**Priority 3: Computer vision**

- Preprocessing
- Model integration
- Object detection
- Geographic bounding boxes
- Database persistence

**Priority 4: Distributed processing**

- RabbitMQ
- Celery workers
- Job status
- Retries
- Error handling

**Priority 5: Advanced functionality**

- Change detection
- Performance optimization
- Kubernetes
- CI/CD
- Monitoring

## Important Implementation Constraints

- The project must work on macOS and Linux using Docker.
- The initial version must run without a dedicated GPU.
- CPU-based inference is acceptable.
- Do not require paid APIs or proprietary cloud infrastructure.
- Prefer open-source libraries and publicly available data.
- Pin dependency versions or use reproducible lockfiles.
- Keep the project suitable for publishing on GitHub.
- Never include secrets, private datasets, or confidential information.

## Verification Requirements

At the end of each phase, provide:

1. Files created or modified.
2. Features implemented.
3. Commands executed.
4. Tests performed and their results.
5. Known limitations.
6. Next implementation phase.

If tests fail, investigate and fix them before reporting success.

If Docker, network access, or a dataset is unavailable, explain exactly what could not be verified.

## Final Deliverables

The final repository must include:

- Complete frontend source code
- Complete backend source code
- Database migrations
- Image processing pipeline
- Object detection pipeline
- Distributed job processing
- Docker configuration
- Kubernetes manifests
- Automated tests
- CI/CD configuration
- Technical documentation
- Sample dataset instructions
- Working local development instructions

## Final Goal

Deliver a working, technically credible satellite imagery analysis platform that demonstrates fullstack engineering, computer vision, remote sensing, geospatial databases, distributed systems, and secure software development.


