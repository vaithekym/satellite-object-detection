import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from httpx import AsyncClient
from shapely.geometry import box

from app.ml.pipeline import GeoDetection
from app.models import AnalysisJob, JobStatus, JobType
from app.repositories import replace_detections
from tests.api_helpers import upload
from tests.rasters import write_geotiff


def detections(*classes: str) -> list[GeoDetection]:
    return [
        GeoDetection(
            0, name, 0.9, np.zeros((4, 2)), box(10 + i * 1e-4, 59.9, 10.0001 + i * 1e-4, 59.9001)
        )
        for i, name in enumerate(classes)
    ]


async def add_job(
    app: FastAPI,
    image_id: uuid.UUID,
    status: JobStatus,
    completed_minutes_ago: int | None = None,
    found: list[GeoDetection] | None = None,
) -> uuid.UUID:
    async with app.state.sessionmaker() as session:
        now = datetime.now(UTC)
        job = AnalysisJob(
            image_id=image_id,
            job_type=JobType.OBJECT_DETECTION,
            status=status,
            completed_at=None
            if completed_minutes_ago is None
            else now - timedelta(minutes=completed_minutes_ago),
            error_message="RuntimeError: model crashed" if status == JobStatus.FAILED else None,
        )
        session.add(job)
        await session.flush()
        if found:
            await replace_detections(session, job.id, image_id, found)
        await session.commit()
        return job.id


async def test_stats_count_only_latest_analysis_per_image(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    first = uuid.UUID((await upload(client, write_geotiff(tmp_path / "a.tif"))).json()["id"])
    second = uuid.UUID((await upload(client, write_geotiff(tmp_path / "b.tif"))).json()["id"])

    await add_job(app, first, JobStatus.COMPLETED, 30, detections("plane", "plane", "ship"))
    latest = await add_job(app, first, JobStatus.COMPLETED, 5, detections("plane", "storage tank"))
    await add_job(app, second, JobStatus.COMPLETED, 10, detections("plane"))
    failed = await add_job(app, second, JobStatus.FAILED, 1)
    await add_job(app, second, JobStatus.QUEUED)
    await add_job(app, second, JobStatus.RUNNING)

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["images"] == 2
    assert stats["analyses_completed"] == 3
    assert stats["jobs_active"] == 2
    assert stats["jobs_failed"] == 1
    # first image: only its latest job (plane, storage tank); second image: one plane.
    assert stats["detections_by_class"] == {"plane": 2, "storage tank": 1}
    assert stats["detections"] == 3

    activity = stats["recent_activity"]
    assert len(activity) <= 10
    times = [a["at"] for a in activity]
    assert times == sorted(times, reverse=True)
    kinds = {a["kind"] for a in activity}
    assert {"upload", "job_completed", "job_failed", "job_queued"} <= kinds
    failure = next(a for a in activity if a["kind"] == "job_failed")
    assert failure["job_id"] == str(failed)
    assert failure["message"] == "RuntimeError: model crashed"
    assert any(a["job_id"] == str(latest) for a in activity)


async def test_stats_on_empty_database(client: AsyncClient) -> None:
    stats = (await client.get("/api/v1/stats")).json()
    assert stats == {
        "images": 0,
        "analyses_completed": 0,
        "jobs_active": 0,
        "jobs_failed": 0,
        "detections": 0,
        "detections_by_class": {},
        "recent_activity": [],
    }
