"""Detection jobs end to end: MinIO → pipeline → PostGIS → GeoJSON API."""

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.ml.jobs import execute_detection_job
from app.models import AnalysisJob, Detection, JobStatus, JobType
from tests.api_helpers import upload
from tests.detectors import FailingDetector, RedSquareDetector, image_with_squares
from tests.rasters import write_geotiff

SQUARES = [(100, 100, 30), (1000, 300, 30), (1500, 1200, 30)]


async def uploaded_image_with_job(app: FastAPI, client: AsyncClient, tmp_path: Path) -> uuid.UUID:
    path = write_geotiff(
        tmp_path / "squares.tif",
        width=1600,
        height=1400,
        data=image_with_squares(1600, 1400, SQUARES),
    )
    image_id = uuid.UUID((await upload(client, path)).json()["id"])
    async with app.state.sessionmaker() as session:
        job = AnalysisJob(
            image_id=image_id, job_type=JobType.OBJECT_DETECTION, status=JobStatus.QUEUED
        )
        session.add(job)
        await session.commit()
        return job.id


async def run(app: FastAPI, job_id: uuid.UUID, detector: RedSquareDetector) -> object:
    settings = app.state.settings.model_copy(update={"detection_tile_size": 512})
    return await execute_detection_job(
        job_id, app.state.sessionmaker, app.state.s3, settings, detector
    )


async def job_and_count(app: FastAPI, job_id: uuid.UUID) -> tuple[AnalysisJob, int]:
    async with app.state.sessionmaker() as session:
        job = await session.get(AnalysisJob, job_id)
        count = await session.scalar(
            select(func.count()).select_from(Detection).where(Detection.job_id == job_id)
        )
    assert job is not None
    return job, int(count or 0)


async def test_job_runs_to_completion_with_real_progress(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    job_id = await uploaded_image_with_job(app, client, tmp_path)
    result = await run(app, job_id, RedSquareDetector())
    assert result is not None

    job, count = await job_and_count(app, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100
    assert job.status_message == "Completed: 3 detections"
    assert job.started_at is not None and job.completed_at is not None
    assert job.completed_at >= job.started_at
    assert job.model_name == "red-square-test-detector"
    assert job.parameters["per_class"] == {"red square": 3}
    assert job.parameters["tile_size"] == 512
    assert count == len(SQUARES)


async def test_rerunning_a_job_does_not_duplicate_detections(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    job_id = await uploaded_image_with_job(app, client, tmp_path)
    await run(app, job_id, RedSquareDetector())

    # A completed job delivered again (e.g. queue redelivery) is a no-op.
    detector = RedSquareDetector()
    assert await run(app, job_id, detector) is None
    assert detector.calls == 0

    # A retry of an interrupted job re-runs and replaces, never appends.
    async with app.state.sessionmaker() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None
        job.status = JobStatus.QUEUED
        await session.commit()
    await run(app, job_id, RedSquareDetector())
    _, count = await job_and_count(app, job_id)
    assert count == len(SQUARES)


async def test_failing_detector_marks_job_failed(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    job_id = await uploaded_image_with_job(app, client, tmp_path)
    with pytest.raises(RuntimeError, match="model crashed"):
        await run(app, job_id, FailingDetector())
    job, count = await job_and_count(app, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_message == "RuntimeError: model crashed"
    assert job.completed_at is not None
    assert count == 0


async def test_detections_geojson_endpoint(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    job_id = await uploaded_image_with_job(app, client, tmp_path)
    await run(app, job_id, RedSquareDetector())
    job, _ = await job_and_count(app, job_id)
    base = f"/api/v1/images/{job.image_id}/detections"

    response = await client.get(base)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    collection = response.json()
    assert collection["type"] == "FeatureCollection"
    assert len(collection["features"]) == 3
    feature = collection["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["class_name"] == "red square"
    assert feature["properties"]["job_id"] == str(job_id)
    assert len(feature["properties"]["pixel_bbox"]["points"]) == 4

    # Filters: bbox around the first square only, class, confidence, job.
    lons = [c[0] for f in collection["features"] for c in f["geometry"]["coordinates"][0]]
    lats = [c[1] for f in collection["features"] for c in f["geometry"]["coordinates"][0]]
    west, north = min(lons), max(lats)  # first square is the most north-western one
    small = f"{west - 1e-5},{north - 0.003},{west + 0.003},{north + 1e-5}"
    assert len((await client.get(base, params={"bbox": small})).json()["features"]) == 1
    assert (await client.get(base, params={"class_name": "plane"})).json()["features"] == []
    assert (await client.get(base, params={"min_confidence": 0.95})).json()["features"] == []
    other_job = str(uuid.uuid4())
    assert (await client.get(base, params={"job_id": other_job})).json()["features"] == []
    assert (await client.get(base, params={"bbox": "1,2,3"})).status_code == 422


async def test_detections_default_to_latest_completed_job(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    first = await uploaded_image_with_job(app, client, tmp_path)
    await run(app, first, RedSquareDetector())
    first_job, _ = await job_and_count(app, first)
    base = f"/api/v1/images/{first_job.image_id}/detections"

    async with app.state.sessionmaker() as session:
        second_job = AnalysisJob(
            image_id=first_job.image_id,
            job_type=JobType.OBJECT_DETECTION,
            status=JobStatus.QUEUED,
        )
        session.add(second_job)
        await session.commit()
        second = second_job.id
    await run(app, second, RedSquareDetector())

    features = (await client.get(base)).json()["features"]
    assert len(features) == len(SQUARES)  # not doubled
    assert {f["properties"]["job_id"] for f in features} == {str(second)}
    older = (await client.get(base, params={"job_id": str(first)})).json()["features"]
    assert {f["properties"]["job_id"] for f in older} == {str(first)}


async def test_image_without_completed_job_has_no_detections(
    client: AsyncClient, tmp_path: Path
) -> None:
    image_id = (await upload(client, write_geotiff(tmp_path / "x.tif"))).json()["id"]
    response = await client.get(f"/api/v1/images/{image_id}/detections")
    assert response.json() == {"type": "FeatureCollection", "features": []}
