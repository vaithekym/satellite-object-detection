VENV := $(CURDIR)/.venv/bin
MINIO_DATA := $(CURDIR)/data/minio

.PHONY: minio init-storage migrate samples model detect evaluate worker backend frontend test test-backend test-frontend lint

# MinIO bound to localhost only, data stored inside the project (git-ignored).
minio:
	@mkdir -p $(MINIO_DATA)
	@set -a && . ./.env && set +a && \
	MINIO_ROOT_USER="$$S3_ACCESS_KEY" MINIO_ROOT_PASSWORD="$$S3_SECRET_KEY" \
	minio server $(MINIO_DATA) --address 127.0.0.1:9000 --console-address 127.0.0.1:9001

init-storage:
	cd backend && $(VENV)/python -m app.storage

migrate:
	cd backend && $(VENV)/alembic upgrade head

# Small public sample rasters → data/samples/ (Landsat test scene + NAIP over SAN airport)
samples:
	cd backend && $(VENV)/python -m scripts.download_samples

# Default detector: YOLO26-s OBB pretrained on DOTA v1 (Ultralytics, AGPL-3.0), checksum-verified.
MODEL_URL := https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s-obb.pt
MODEL_SHA256 := 38dbd72ef6804f9bbbea7ad20f486e6ca6e093c8cd9bc857207a846565bd6e0b
model:
	@mkdir -p data/models
	curl -sSL -o data/models/yolo26s-obb.pt $(MODEL_URL)
	echo "$(MODEL_SHA256)  data/models/yolo26s-obb.pt" | shasum -a 256 -c -

# Run object detection on an uploaded image without the queue: make detect IMAGE=<image id>
detect:
	cd backend && $(VENV)/python -m app.ml.run $(IMAGE)

# Model evaluation on labelled validation data (DOTA8 sample) + speed on NAIP tiles
evaluate:
	cd backend && $(VENV)/python -m scripts.evaluate_model

# Celery worker consuming the analysis queue (run several for parallel jobs).
WORKER_CONCURRENCY ?= 1
worker:
	cd backend && $(VENV)/celery -A app.worker.celery_app worker -Q analysis \
		--concurrency=$(WORKER_CONCURRENCY) --loglevel=INFO

backend:
	cd backend && $(VENV)/uvicorn --factory app.main:create_app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && $(VENV)/pytest

test-frontend:
	cd frontend && npm test

lint:
	cd backend && $(VENV)/ruff check . && $(VENV)/ruff format --check . && $(VENV)/mypy app tests alembic scripts
	cd frontend && npm run lint && npm run typecheck
