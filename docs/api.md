# API

Base URL in development: `http://127.0.0.1:8000`. The frontend's dev server proxies `/api` and
`/health` to it. Interactive OpenAPI documentation is at `/docs`, and the schema at
`/openapi.json`.

Errors use FastAPI's format: `{"detail": "<message>"}`, or a list of validation errors for 422 on
malformed input. Messages are safe to show to users: internal details such as host names, paths
and credentials are logged server-side only.

## Health

| Method | Path | Response |
|---|---|---|
| GET | `/health/live` | `200 {"status": "alive"}` |
| GET | `/health/ready` | `200` or `503` with per-dependency checks |

```json
{
  "status": "ready",
  "checks": {
    "postgres": {"ok": true, "detail": "PostGIS 3.7.0"},
    "rabbitmq": {"ok": true, "detail": "connected"},
    "object_storage": {"ok": true, "detail": "bucket 'satellite-detection'"}
  }
}
```

The checks run concurrently, each with a timeout (3 s by default).

## Images

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/images/upload` | Upload a GeoTIFF (multipart field `file`) |
| GET | `/api/v1/images?limit=50&offset=0` | List images, newest first (`limit` ≤ 200) |
| GET | `/api/v1/images/{id}` | Image with full raster metadata |
| GET | `/api/v1/images/{id}/preview` | PNG thumbnail (max 512 px, NoData transparent) |
| GET | `/api/v1/images/{id}/tilejson.json` | TileJSON 3.0.0 for web maps |
| GET | `/api/v1/images/{id}/tiles/{z}/{x}/{y}.png` | 256 px Web Mercator tile |
| GET | `/api/v1/images/{id}/detections` | Detections as GeoJSON |

### Upload

```bash
curl -F "file=@data/samples/naip_lax_2024.tif" http://127.0.0.1:8000/api/v1/images/upload
```

`201 Created`:

```json
{"id": "10d16304-dd2c-4923-ae53-e2cb321f682f", "filename": "naip_lax_2024.tif", "status": "READY"}
```

| Status | Meaning |
|---|---|
| 411 | `Content-Length` header missing (chunked uploads are not accepted) |
| 413 | File larger than `MAX_UPLOAD_BYTES` (default 2 GiB) |
| 415 | Not a TIFF/BigTIFF (checked by file signature, not extension) |
| 422 | Invalid raster, with the reason: no CRS, not georeferenced, rotated, too many pixels or bands, too large when decompressed, unsupported data type, corrupt or unreadable, crosses the antimeridian, empty file, missing `file` field |
| 507 | Not enough free disk space to process the upload |

### Image

`GET /api/v1/images/{id}` (the list returns the same fields without `metadata`):

```json
{
  "id": "…",
  "filename": "naip_lax_2024.tif",
  "file_size": 11411927,
  "width": 2048,
  "height": 2048,
  "band_count": 4,
  "crs": "EPSG:26911",
  "resolution_x": 0.6,
  "resolution_y": 0.6,
  "resolution_unit": "metre",
  "bounds": {"type": "Polygon", "coordinates": [[[-118.41484, 33.93689], "…"]]},
  "acquisition_date": "2024-05-06T16:00:00Z",
  "uploaded_at": "2026-11-19T22:25:52Z",
  "processing_status": "READY",
  "metadata": {
    "dtypes": ["uint8", "uint8", "uint8", "uint8"],
    "nodata": null,
    "color_interpretation": ["red", "green", "blue", "undefined"],
    "wgs84_bbox": [-118.41484, 33.93689, -118.40136, 33.94812],
    "crs_wkt": "…",
    "acquisition_date_source": "ACQUISITIONDATETIME",
    "display_bands": [1, 2, 3],
    "display_ranges": null,
    "…": "…"
  }
}
```

`crs` is `EPSG:<code>`, or `CUSTOM` when the CRS has no EPSG code (the full WKT is in `metadata`).
`acquisition_date` is `null` unless the file contains an explicit acquisition tag. It is never
guessed.

### Tiles

```json
{
  "tilejson": "3.0.0",
  "name": "naip_lax_2024.tif",
  "tiles": ["http://127.0.0.1:8000/api/v1/images/{id}/tiles/{z}/{x}/{y}.png"],
  "minzoom": 15,
  "maxzoom": 18,
  "bounds": [-118.41484, 33.93689, -118.40136, 33.94812]
}
```

The tile endpoint returns 404 for tiles outside the image or for `x`/`y` ≥ 2^z, and 422 for z > 24.

### Detections

`GET /api/v1/images/{id}/detections`

| Parameter | Description |
|---|---|
| `bbox` | `min_lon,min_lat,max_lon,max_lat` (EPSG:4326). Uses the spatial index. |
| `class_name` | Repeatable, e.g. `?class_name=plane&class_name=ship` |
| `min_confidence` | 0–1 |
| `job_id` | A specific job. **Default: the image's most recent completed detection job.** |
| `limit`, `offset` | Paging (`limit` ≤ 10 000, default 5 000) |

The response is an RFC 7946 FeatureCollection with media type `application/geo+json`, sorted by
confidence (highest first):

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "id": "6443e63f-…",
    "geometry": {"type": "Polygon", "coordinates": [[[-117.19624, 32.73318], "…"]]},
    "properties": {
      "class_name": "plane",
      "class_id": 0,
      "confidence": 0.93,
      "job_id": "…",
      "image_id": "…",
      "pixel_bbox": {"points": [[1033.2, 1402.5], "…"], "clipped_to_image": false}
    }
  }]
}
```

Geometries are oriented boxes clipped to the image extent. `pixel_bbox.points` are the model's
corner points in full-image pixel coordinates, before clipping. `confidence` is the model's score,
not a probability that the detection is correct.

## Analysis and jobs

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/analysis` | Queue an analysis |
| GET | `/api/v1/jobs?status=&image_id=&limit=&offset=` | Jobs, newest first |
| GET | `/api/v1/jobs/{id}` | One job |
| POST | `/api/v1/jobs/{id}/cancel` | Cancel a job that has not started |

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analysis \
  -H "Content-Type: application/json" \
  -d '{"image_id": "<id>", "analysis_type": "object_detection", "model": "default"}'
```

`202 Accepted`: `{"job_id": "…", "status": "QUEUED"}`

| Status | Meaning |
|---|---|
| 404 | Image not found |
| 409 | An analysis of this image is already pending, queued or running. The body includes its `job_id`. |
| 422 | Image not ready, or unsupported `analysis_type` or `model` (only `object_detection` and `default` exist) |
| 503 | The queue is unavailable. The job is recorded as `FAILED`. |

Job:

```json
{
  "job_id": "…",
  "image_id": "…",
  "image_filename": "naip_lax_2024.tif",
  "job_type": "object_detection",
  "status": "RUNNING",
  "progress": 45,
  "message": "Processing image tiles (4/9)",
  "error_message": null,
  "model_name": "yolo26s-obb",
  "model_version": "sha256:38dbd72ef680",
  "parameters": {"tile_size": 1024, "overlap": 128, "confidence": 0.25, "device": "cpu", "worker": "host:pid", "…": "…"},
  "created_at": "…",
  "started_at": "…",
  "completed_at": null
}
```

Statuses: `PENDING`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`. Progress reflects
real work: 0–5 % download, 5–95 % tiles processed, 95–100 % saving. After completion,
`parameters` also contains tile counts, timings and detections per class.

Cancelling returns 409 if the job is no longer pending or queued. Running jobs cannot be
interrupted.

## Statistics

`GET /api/v1/stats`

```json
{
  "images": 6,
  "analyses_completed": 10,
  "jobs_active": 0,
  "jobs_failed": 0,
  "detections": 440,
  "detections_by_class": {"plane": 227, "small vehicle": 171, "…": 0},
  "recent_activity": [
    {"kind": "job_completed", "at": "…", "image_id": "…", "image_filename": "…", "job_id": "…", "message": "…"}
  ]
}
```

Detection counts include only each image's most recent completed analysis, so re-analysing an
image does not double-count. `kind` is one of `upload`, `job_completed`, `job_failed`,
`job_cancelled` and `job_queued`.
