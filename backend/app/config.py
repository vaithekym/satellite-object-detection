from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
# .env lives in the repository root, one level above backend/.
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    # Separate database for integration tests; tests that need it are skipped when unset.
    test_database_url: str | None = None
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"

    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key: str
    s3_secret_key: SecretStr
    s3_bucket: str = "satellite-detection"
    s3_region: str = "us-east-1"

    # Upload and raster processing limits (uploads are untrusted input).
    max_upload_bytes: int = 2 * 1024**3
    max_raster_pixels: int = 500_000_000
    max_raster_bands: int = 16
    max_uncompressed_bytes: int = 8 * 1024**3
    min_free_disk_bytes: int = 2 * 1024**3

    # Object detection. Default: Ultralytics YOLO26-s OBB, pretrained on DOTA v1 (aerial
    # imagery, 15 classes, oriented boxes). Weights are AGPL-3.0 licensed.
    detection_model_path: Path = REPO_ROOT / "data" / "models" / "yolo26s-obb.pt"
    detection_model_sha256: str | None = (
        "38dbd72ef6804f9bbbea7ad20f486e6ca6e093c8cd9bc857207a846565bd6e0b"
    )
    detection_device: str = "cpu"  # "cpu", "mps" (Apple GPU) or "cuda:0"
    detection_tile_size: int = 1024
    detection_tile_overlap: int = 128
    detection_batch_size: int = 4
    detection_confidence: float = 0.25
    detection_iou_threshold: float = 0.5
    # Tiles with less valid (non-NoData) area than this are skipped.
    detection_min_valid_fraction: float = 0.05

    # Job queue (RabbitMQ + Celery). Messages carry only the job id, never imagery.
    analysis_queue: str = "analysis"
    worker_concurrency: int = 1  # CPU-bound jobs; PyTorch already uses several threads per job
    job_soft_time_limit_seconds: int = 3600
    job_time_limit_seconds: int = 3900  # hard kill of a stuck worker process
    job_max_retries: int = 5  # only for transient errors (storage/database unavailable)
    job_retry_backoff_seconds: int = 10  # doubled per attempt, with jitter
    job_retry_backoff_max_seconds: int = 600

    cors_origins: list[str] = ["http://localhost:5173"]
    health_check_timeout_seconds: float = 3.0


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required values come from env / .env
