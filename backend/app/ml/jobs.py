"""Execute an object detection job: download COG → tiled detection → save to PostGIS.

Progress written to the job row reflects real work: 0-5 % download, 5-95 % tiles processed,
95-100 % saving. Re-running a job replaces its detections instead of duplicating them.
"""

import asyncio
import logging
import os
import socket
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.image_service import cog_key
from app.ml.detector import ObjectDetector
from app.ml.pipeline import DetectionParams, DetectionResult, run_detection
from app.models import AnalysisJob, Image, JobStatus
from app.raster import display_bands_for
from app.repositories import replace_detections

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)
PROGRESS_INTERVAL_SECONDS = 1.0


class JobNotRunnableError(Exception):
    """The job does not exist, or is not in a state that may be executed."""


def detection_params(settings: Settings) -> DetectionParams:
    return DetectionParams(
        tile_size=settings.detection_tile_size,
        overlap=settings.detection_tile_overlap,
        batch_size=settings.detection_batch_size,
        iou_threshold=settings.detection_iou_threshold,
        min_valid_fraction=settings.detection_min_valid_fraction,
    )


class _Progress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.done, self.total = 0, 0

    def update(self, done: int, total: int) -> None:
        with self._lock:
            self.done, self.total = done, total

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return self.done, self.total


async def _set(session: AsyncSession, job: AnalysisJob, **fields: Any) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    await session.commit()


async def execute_detection_job(
    job_id: uuid.UUID,
    sessionmaker: async_sessionmaker[AsyncSession],
    s3: "S3Client",
    settings: Settings,
    detector: ObjectDetector,
    retryable: tuple[type[BaseException], ...] = (),
) -> DetectionResult | None:
    """Run the job. Returns None if it was already completed or cancelled (idempotent).

    Exceptions of a `retryable` type leave the job QUEUED (the caller schedules a retry);
    any other exception marks it FAILED. Either way the exception is re-raised.
    """
    async with sessionmaker() as session:
        job = await session.get(AnalysisJob, job_id)
        if job is None:
            raise JobNotRunnableError(f"Job {job_id} not found")
        if job.status == JobStatus.COMPLETED:
            return None
        if job.status == JobStatus.CANCELLED:
            logger.info("Skipping cancelled job %s", job_id)
            return None
        image = await session.get(Image, job.image_id)
        if image is None:
            raise JobNotRunnableError(f"Image for job {job_id} not found")

        params = detection_params(settings)
        await _set(
            session,
            job,
            status=JobStatus.RUNNING,
            progress=0,
            status_message="Downloading imagery",
            error_message=None,
            started_at=datetime.now(UTC),
            completed_at=None,
            model_name=detector.name,
            model_version=detector.version,
            parameters=job.parameters
            | {
                "tile_size": params.tile_size,
                "overlap": params.overlap,
                "confidence": settings.detection_confidence,
                "iou_threshold": params.iou_threshold,
                "device": settings.detection_device,
                "worker": f"{socket.gethostname()}:{os.getpid()}",
            },
        )
        try:
            result = await _detect(session, job, image, s3, settings, detector, params)
            await _set(session, job, progress=95, status_message="Saving detections")
            count = await replace_detections(session, job.id, image.id, result.detections)
            await _set(
                session,
                job,
                status=JobStatus.COMPLETED,
                progress=100,
                status_message=f"Completed: {count} detections",
                completed_at=datetime.now(UTC),
                parameters=job.parameters
                | {
                    "tiles_total": result.tiles_total,
                    "tiles_skipped_nodata": result.tiles_skipped,
                    "raw_detections": result.raw_detections,
                    "inference_seconds": round(result.inference_seconds, 2),
                    "total_seconds": round(result.total_seconds, 2),
                    "per_class": result.per_class,
                },
            )
            return result
        except Exception as exc:
            await session.rollback()
            if isinstance(exc, retryable):
                logger.warning("Detection job %s hit a transient error: %s", job_id, exc)
                await _set(
                    session,
                    job,
                    status=JobStatus.QUEUED,
                    progress=0,
                    status_message="Waiting to retry after a temporary error",
                    error_message=f"{type(exc).__name__}: {exc}"[:1000],
                )
                raise
            logger.exception("Detection job %s failed", job_id)
            await _set(
                session,
                job,
                status=JobStatus.FAILED,
                status_message="Failed",
                error_message=f"{type(exc).__name__}: {exc}"[:1000],
                completed_at=datetime.now(UTC),
            )
            raise


async def _detect(
    session: AsyncSession,
    job: AnalysisJob,
    image: Image,
    s3: "S3Client",
    settings: Settings,
    detector: ObjectDetector,
    params: DetectionParams,
) -> DetectionResult:
    metadata = image.raster_metadata
    bands = metadata.get("display_bands") or display_bands_for(
        metadata.get("color_interpretation", []), int(metadata.get("band_count", 1))
    )
    ranges = metadata.get("display_ranges")
    key = metadata.get("cog_object_key") or cog_key(image.id)

    with tempfile.TemporaryDirectory(prefix="satellite-detection-job-") as tmp:
        path = Path(tmp) / "image.tif"
        await asyncio.to_thread(s3.download_file, settings.s3_bucket, key, str(path))
        await _set(session, job, progress=5, status_message="Processing image tiles")

        progress = _Progress()
        loop = asyncio.get_running_loop()
        # One dedicated thread: GDAL dataset handles stay on the thread that opened them.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="detect") as executor:
            future = loop.run_in_executor(
                executor, run_detection, path, detector, params, bands, ranges, progress.update
            )
            last = (-1, -1)
            while not future.done():
                await asyncio.wait({future}, timeout=PROGRESS_INTERVAL_SECONDS)
                done, total = progress.snapshot()
                if total and (done, total) != last:
                    last = (done, total)
                    await _set(
                        session,
                        job,
                        progress=5 + int(90 * done / total),
                        status_message=f"Processing image tiles ({done}/{total})",
                    )
            return await future
