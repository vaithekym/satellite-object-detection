"""Celery tasks. A message carries only the job id; imagery is read from object storage."""

import asyncio
import logging
import random
import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ConnectionClosedError, EndpointConnectionError
from celery import Task
from celery.exceptions import Reject
from celery.signals import worker_process_init, worker_ready
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings, get_settings
from app.db import create_engine
from app.ml.detector import ObjectDetector, get_detector
from app.ml.jobs import JobNotRunnableError, execute_detection_job
from app.storage import create_s3_client
from app.worker.celery_app import TASK_OBJECT_DETECTION, analysis_queues, celery_app

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

# Infrastructure that may come back: storage, database or network briefly unavailable.
# Everything else (corrupt data, model errors, bugs) fails the job without retrying.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    EndpointConnectionError,
    ConnectionClosedError,
    OperationalError,
    InterfaceError,
    ConnectionError,
    TimeoutError,
)


@lru_cache(maxsize=1)
def worker_s3() -> "S3Client":
    return create_s3_client(get_settings())


def worker_detector(settings: Settings) -> ObjectDetector:
    """Loaded once per worker process (cached), reused by every job it runs."""
    return get_detector(
        settings.detection_model_path,
        settings.detection_device,
        settings.detection_confidence,
        settings.detection_iou_threshold,
        settings.detection_tile_size,
        settings.detection_model_sha256,
    )


@worker_process_init.connect
def _load_model(**_: Any) -> None:
    try:
        detector = worker_detector(get_settings())
        logger.info("Loaded model %s (%s)", detector.name, detector.version)
    except Exception:
        # The job will fail with a clear error instead of the worker refusing to start.
        logger.exception("Could not load the detection model at worker start-up")


@worker_ready.connect
def _declare_queues(**_: Any) -> None:
    """Make sure the dead-letter queue exists, so rejected messages are kept, not dropped."""
    with celery_app.connection_for_write() as connection:
        for queue in analysis_queues(get_settings().analysis_queue):
            queue(connection.default_channel).declare()


def retry_delay(retries: int, settings: Settings) -> float:
    """Exponential backoff with jitter: base·2^n seconds, capped, randomised to 50-100 %."""
    delay = min(
        settings.job_retry_backoff_seconds * 2**retries, settings.job_retry_backoff_max_seconds
    )
    return float(delay * random.uniform(0.5, 1.0))  # noqa: S311 (not security-relevant)


async def _execute(
    job_id: uuid.UUID, settings: Settings, retryable: tuple[type[BaseException], ...]
) -> dict[str, Any]:
    engine = create_engine(settings)  # per task: asyncio.run creates a fresh event loop
    try:
        result = await execute_detection_job(
            job_id,
            async_sessionmaker(engine, expire_on_commit=False),
            worker_s3(),
            settings,
            worker_detector(settings),
            retryable,
        )
    finally:
        await engine.dispose()
    if result is None:
        return {"job_id": str(job_id), "skipped": True}
    return {"job_id": str(job_id), "detections": len(result.detections)}


@celery_app.task(bind=True, name=TASK_OBJECT_DETECTION, max_retries=get_settings().job_max_retries)
def run_object_detection(self: Task, job_id: str) -> dict[str, Any]:
    settings = get_settings()
    final_attempt = self.request.retries >= self.max_retries
    try:
        return asyncio.run(
            _execute(uuid.UUID(job_id), settings, () if final_attempt else TRANSIENT_ERRORS)
        )
    except JobNotRunnableError as exc:
        # Unknown job/image: nothing to retry; send the message to the dead-letter queue.
        logger.error("Rejecting job message %s: %s", job_id, exc)
        raise Reject(str(exc), requeue=False) from exc
    except TRANSIENT_ERRORS as exc:
        if final_attempt:
            raise
        countdown = retry_delay(self.request.retries, settings)
        logger.warning("Job %s: retrying in %.0fs after %r", job_id, countdown, exc)
        raise self.retry(exc=exc, countdown=countdown) from exc
