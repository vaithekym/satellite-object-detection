# Security

## Scope and threat model

Satellite Object Detection is a development and portfolio application meant for a **single, trusted machine**.

> **There is no authentication or authorization.** Anyone who can reach the API can upload,
> analyse and read everything. Do not expose the frontend, API, MinIO, RabbitMQ or PostgreSQL to a
> network. Authentication (e.g. OIDC) and per-user access control are prerequisites for any other
> deployment.

The main threat considered is **untrusted input**: uploaded rasters and their metadata are treated
as hostile, because raster formats are complex and GDAL has a large attack surface.

## Uploads

| Control | Implementation |
|---|---|
| Size limit before reading | `Content-Length` is required (411 otherwise) and checked against `MAX_UPLOAD_BYTES` before the body is parsed. The streamed size is checked again (413). |
| Disk exhaustion | Free temporary space must exceed `MIN_FREE_DISK_BYTES` + 3 × upload size (507 otherwise). |
| File type | The TIFF/BigTIFF signature is checked on the first bytes (415). The extension and declared content type are ignored. |
| Restricted parser | GDAL may only open the file with the **GTiff driver**, so VRT, XML or other formats that could reference local files or URLs cannot be smuggled in. `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` prevents reading sidecar files. |
| Decompression bombs | Width × height, band count and decompressed size are checked from the header **before any pixel data is read** (`MAX_RASTER_PIXELS`, `MAX_RASTER_BANDS`, `MAX_UNCOMPRESSED_BYTES`). Tested with a sparse file of about 1 MB that would be 30 GB decoded. |
| Corrupt files | The first block must decode. COG conversion reads the whole file, and failures are rejected with 422. |
| Filenames | Reduced to a sanitised basename (no path components or control characters) for display only. Storage keys are `images/<server-generated uuid>/…`. No command is ever built from filenames or metadata. |
| Metadata | Stored tags are capped in count and length. NaN and Inf values are serialised safely. |
| Partial failure | If the database insert fails after storage writes, the stored objects are deleted. |

## API and data access

- **SQL injection:** all queries go through SQLAlchemy with bound parameters. No raw SQL is built
  from input.
- **Request validation:** Pydantic models and typed path and query parameters, with ranges for
  paging, zoom levels and confidence. Unknown analysis types and models are rejected.
- **Safe errors:** responses carry short, intentional messages. Unexpected exceptions in readiness
  checks return only the exception type, and details go to the server log (tested to not leak host
  names or passwords).
- **CORS:** only the configured frontend origin (`CORS_ORIGINS`), with methods GET, POST and
  DELETE and header `Content-Type`.
- **Queue messages** carry only a job id, never imagery or file paths.

## Infrastructure

- **Least-privilege database role:** the application connects as `satellite_detection`, owner of its own
  database but not a superuser. PostGIS is created once by a superuser. The test suite uses a
  separate `satellite_detection_test` database and refuses to run against a database whose name does not end
  in `_test`.
- **Local-only services:** MinIO binds to `127.0.0.1` (API and console). RabbitMQ's `guest` user is
  only accepted from localhost. Homebrew PostgreSQL listens on localhost.
- **Secrets:** configuration comes from `.env`, which is git-ignored and should be readable only by
  you (`chmod 600 .env`). `.env.example` contains placeholders only. MinIO's root credentials are
  used by the app for simplicity. A dedicated access key with a bucket-scoped policy would be better.
- **Telemetry:** Ultralytics' usage analytics (`sync`) are disabled at model load.
- **Supply chain:** Python and npm dependencies are pinned to exact versions. Model weights are
  verified against a pinned SHA-256. `npm audit` reported 0 known vulnerabilities at install time.
  Python dependencies have not been scanned (e.g. with `pip-audit`). That, and automated scanning in
  CI, is still to do.
- **External requests from the browser:** basemap tiles (OpenStreetMap) and map font glyphs
  (`demotiles.maplibre.org`) are loaded from public servers, which can see which map areas are
  viewed. Configure `VITE_BASEMAP_URL` and `VITE_GLYPHS_URL` to self-hosted sources if that matters.

## Resource limits

| Limit | Default |
|---|---|
| Upload size | 2 GiB |
| Raster pixels | 500 million |
| Bands | 16 |
| Decompressed size | 8 GiB |
| Job soft / hard time limit | 1 h / 1 h 5 min |
| Concurrent jobs per worker | 1 (`WORKER_CONCURRENCY`) |
| Detections per GeoJSON request | 10 000 |

## Not done

Authentication and authorization, rate limiting, HTTPS/TLS, container isolation for raster
parsing, Python dependency scanning, audit logging, and separate S3 credentials for the API and
workers.
