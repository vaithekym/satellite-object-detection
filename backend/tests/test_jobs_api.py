"""Job API and task logic without a running worker (the queue is replaced by a recorder)."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.config import get_settings
from app.ml.jobs import JobNotRunnableError, execute_detection_job
from app.models import AnalysisJob, JobStatus, JobType
from app.worker import tasks
from app.worker.celery_app import TASK_OBJECT_DETECTION
from tests.api_helpers import TEST_QUEUE, upload
from tests.detectors import RedSquareDetector, image_with_squares
from tests.rasters import write_geotiff


class RecordingCelery:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    def send_task(self, name: str, **kwargs: Any) -> None:
        if self.fail:
            raise ConnectionRefusedError("broker down")
        self.sent.append({"name": name, **kwargs})


@pytest.fixture
def queue(app: FastAPI) -> RecordingCelery:
    recorder = RecordingCelery()
    app.state.celery = recorder
    return recorder


async def uploaded_image(client: AsyncClient, tmp_path: Path) -> str:
    path = write_geotiff(
        tmp_path / "img.tif",
        width=600,
        height=600,
        data=image_with_squares(600, 600, [(50, 50, 30)]),
    )
    return str((await upload(client, path)).json()["id"])


async def test_create_analysis_queues_only_the_job_id(
    app: FastAPI, client: AsyncClient, queue: RecordingCelery, tmp_path: Path
) -> None:
    image_id = await uploaded_image(client, tmp_path)
    response = await client.post(
        "/api/v1/analysis",
        json={"image_id": image_id, "analysis_type": "object_detection", "model": "default"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    job_id = body["job_id"]

    # The message references the job; no imagery or file paths.
    assert queue.sent == [
        {"name": TASK_OBJECT_DETECTION, "args": [job_id], "task_id": job_id, "queue": TEST_QUEUE}
    ]
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["status"] == "QUEUED"
    assert job["progress"] == 0
    assert job["image_id"] == image_id
    assert job["image_filename"] == "img.tif"
    assert job["message"] == "Waiting for a worker"


async def test_duplicate_analysis_of_active_image_is_rejected(
    client: AsyncClient, queue: RecordingCelery, tmp_path: Path
) -> None:
    image_id = await uploaded_image(client, tmp_path)
    first = (await client.post("/api/v1/analysis", json={"image_id": image_id})).json()
    second = await client.post("/api/v1/analysis", json={"image_id": image_id})
    assert second.status_code == 409
    assert second.json()["job_id"] == first["job_id"]
    assert len(queue.sent) == 1


async def test_analysis_validation(client: AsyncClient, queue: RecordingCelery) -> None:
    unknown = await client.post("/api/v1/analysis", json={"image_id": str(uuid.uuid4())})
    assert unknown.status_code == 404
    bad_type = await client.post(
        "/api/v1/analysis", json={"image_id": str(uuid.uuid4()), "analysis_type": "magic"}
    )
    assert bad_type.status_code == 422
    bad_model = await client.post(
        "/api/v1/analysis", json={"image_id": str(uuid.uuid4()), "model": "gpt"}
    )
    assert bad_model.status_code == 422
    assert queue.sent == []


async def test_queue_unavailable_fails_job_and_returns_503(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    app.state.celery = RecordingCelery(fail=True)
    image_id = await uploaded_image(client, tmp_path)
    response = await client.post("/api/v1/analysis", json={"image_id": image_id})
    assert response.status_code == 503
    jobs = (await client.get("/api/v1/jobs", params={"image_id": image_id})).json()
    assert jobs["total"] == 1
    assert jobs["items"][0]["status"] == "FAILED"
    assert jobs["items"][0]["error_message"] == "The job queue is unavailable"


async def test_list_filter_and_cancel_jobs(
    client: AsyncClient, queue: RecordingCelery, tmp_path: Path
) -> None:
    image_id = await uploaded_image(client, tmp_path)
    job_id = (await client.post("/api/v1/analysis", json={"image_id": image_id})).json()["job_id"]

    listing = (await client.get("/api/v1/jobs", params={"status": "QUEUED"})).json()
    assert [j["job_id"] for j in listing["items"]] == [job_id]
    assert (await client.get("/api/v1/jobs", params={"status": "RUNNING"})).json()["total"] == 0
    assert (await client.get("/api/v1/jobs", params={"status": "BOGUS"})).status_code == 422

    cancelled = await client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert (await client.post(f"/api/v1/jobs/{job_id}/cancel")).status_code == 409
    assert (await client.get(f"/api/v1/jobs/{uuid.uuid4()}")).status_code == 404
    # The image can be analysed again once nothing is active.
    assert (await client.post("/api/v1/analysis", json={"image_id": image_id})).status_code == 202


async def _queued_job(app: FastAPI, client: AsyncClient, tmp_path: Path) -> uuid.UUID:
    image_id = uuid.UUID(await uploaded_image(client, tmp_path))
    async with app.state.sessionmaker() as session:
        job = AnalysisJob(
            image_id=image_id, job_type=JobType.OBJECT_DETECTION, status=JobStatus.QUEUED
        )
        session.add(job)
        await session.commit()
        return job.id


class FlakyDetector(RedSquareDetector):
    def predict(self, images: list[Any]) -> list[Any]:
        raise ConnectionError("storage hiccup")


async def test_transient_error_leaves_job_queued_for_retry(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    job_id = await _queued_job(app, client, tmp_path)
    args = (job_id, app.state.sessionmaker, app.state.s3, app.state.settings, FlakyDetector())
    with pytest.raises(ConnectionError):
        await execute_detection_job(*args, retryable=(ConnectionError,))
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["status"] == "QUEUED"
    assert job["message"] == "Waiting to retry after a temporary error"

    # On the final attempt the same error is not retryable any more → FAILED.
    with pytest.raises(ConnectionError):
        await execute_detection_job(*args, retryable=())
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["status"] == "FAILED"
    assert job["error_message"] == "ConnectionError: storage hiccup"


async def test_cancelled_job_is_skipped_by_worker(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    job_id = await _queued_job(app, client, tmp_path)
    await client.post(f"/api/v1/jobs/{job_id}/cancel")
    detector = RedSquareDetector()
    result = await execute_detection_job(
        job_id, app.state.sessionmaker, app.state.s3, app.state.settings, detector
    )
    assert result is None
    assert detector.calls == 0
    assert (await client.get(f"/api/v1/jobs/{job_id}")).json()["status"] == "CANCELLED"


# --- Celery task wrapper (eager, no broker) -------------------------------------------------


def test_retry_delay_is_exponential_capped_and_jittered() -> None:
    settings = get_settings().model_copy(
        update={"job_retry_backoff_seconds": 10, "job_retry_backoff_max_seconds": 600}
    )
    for retries, full in [(0, 10), (1, 20), (2, 40), (3, 80), (10, 600)]:
        delays = [tasks.retry_delay(retries, settings) for _ in range(50)]
        assert all(full * 0.5 <= d <= full for d in delays)


def _patch_execute(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    async def fake_execute(*args: Any) -> dict[str, Any]:
        calls.append(args)
        raise error

    monkeypatch.setattr(tasks, "_execute", fake_execute)
    return calls


def test_task_retries_transient_errors_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    # Eager mode re-runs retries immediately (no waiting), so the whole sequence is visible.
    calls = _patch_execute(monkeypatch, ConnectionError("db restarting"))
    delays: list[float] = []
    original_delay = tasks.retry_delay

    def recording_delay(retries: int, settings: Any) -> float:
        delays.append(original_delay(retries, settings))
        return delays[-1]

    monkeypatch.setattr(tasks, "retry_delay", recording_delay)
    result = tasks.run_object_detection.apply(args=[str(uuid.uuid4())])

    max_retries = tasks.run_object_detection.max_retries
    assert len(calls) == max_retries + 1
    # Every attempt but the last may treat the error as transient; the last marks FAILED.
    assert [c[2] for c in calls] == [tasks.TRANSIENT_ERRORS] * max_retries + [()]
    assert len(delays) == max_retries
    assert result.state == "FAILURE"


def test_task_does_not_retry_on_final_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_execute(monkeypatch, ConnectionError("still down"))
    max_retries = tasks.run_object_detection.max_retries
    result = tasks.run_object_detection.apply(args=[str(uuid.uuid4())], retries=max_retries)
    assert result.state == "FAILURE"
    assert calls[0][2] == ()  # nothing retryable: the job is marked FAILED


def test_task_rejects_unknown_job_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_execute(monkeypatch, JobNotRunnableError("Job not found"))
    result = tasks.run_object_detection.apply(args=[str(uuid.uuid4())])
    assert result.state == "REJECTED"


def test_task_does_not_retry_deterministic_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_execute(monkeypatch, ValueError("corrupt raster"))
    result = tasks.run_object_detection.apply(args=[str(uuid.uuid4())])
    assert result.state == "FAILURE"
