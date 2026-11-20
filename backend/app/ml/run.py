"""Run object detection on an uploaded image from the command line (no queue).

    python -m app.ml.run <image_id>        (or: make detect IMAGE=<image_id>)

Step 6 runs the same job function from Celery workers.
"""

import argparse
import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db import create_engine
from app.ml.detector import get_detector
from app.ml.jobs import execute_detection_job
from app.models import AnalysisJob, Image, JobStatus, JobType
from app.storage import create_s3_client


async def main(image_id: uuid.UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            if await session.get(Image, image_id) is None:
                raise SystemExit(f"Image {image_id} not found")
            job = AnalysisJob(
                image_id=image_id,
                job_type=JobType.OBJECT_DETECTION,
                status=JobStatus.QUEUED,
                parameters={"model": "default", "trigger": "cli"},
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        detector = get_detector(
            settings.detection_model_path,
            settings.detection_device,
            settings.detection_confidence,
            settings.detection_iou_threshold,
            settings.detection_tile_size,
            settings.detection_model_sha256,
        )
        device = settings.detection_device
        print(f"job {job_id}: model {detector.name} ({detector.version}) on {device}")
        result = await execute_detection_job(
            job_id, sessionmaker, create_s3_client(settings), settings, detector
        )
        if result is not None:
            print(
                f"{len(result.detections)} detections "
                f"({result.raw_detections} before merging) in {result.total_seconds:.1f}s, "
                f"{result.tiles_total} tiles ({result.tiles_skipped} skipped as NoData)"
            )
            print("per class:", result.per_class)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_id", type=uuid.UUID)
    asyncio.run(main(parser.parse_args().image_id))
