"""End to end with a real Celery worker process, RabbitMQ, PostGIS, MinIO and the real model.

Upload GeoTIFF → MinIO → metadata in PostGIS → POST /analysis → RabbitMQ → worker inference
→ detections in PostGIS → GeoJSON from the API. Uses its own queue, so a running dev worker
is not involved. Skipped when RabbitMQ, the model weights or the sample imagery are missing.
"""

import asyncio
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from kombu import Connection
from shapely.geometry import shape

from app.config import get_settings
from app.worker.celery_app import TASK_OBJECT_DETECTION, analysis_queues, dead_letter_queue
from tests.api_helpers import TEST_BUCKET, TEST_QUEUE, upload
from tests.rasters import SAMPLES_DIR

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL = BACKEND_DIR.parent / "data" / "models" / "yolo26s-obb.pt"
CELERY = Path(sys.executable).parent / "celery"


def _queue_message_count(name: str) -> int:
    with Connection(get_settings().rabbitmq_url) as conn:
        queue = next(q for q in analysis_queues(TEST_QUEUE) if q.name == name)
        _, count, _ = queue(conn.default_channel).queue_declare(passive=True)
        return int(count)


def _delete_test_queues() -> None:
    with Connection(get_settings().rabbitmq_url) as conn:
        for queue in analysis_queues(TEST_QUEUE):
            queue(conn.default_channel).delete()


@pytest.fixture(scope="module")
def worker(migrated_database: str) -> Iterator[list[str]]:
    if not MODEL.exists():
        pytest.skip("model weights missing (make model)")
    try:
        with Connection(get_settings().rabbitmq_url, connect_timeout=2) as conn:
            conn.connect()
    except Exception:
        pytest.skip("RabbitMQ is not running")
    _delete_test_queues()

    env = os.environ | {
        "DATABASE_URL": migrated_database,
        "S3_BUCKET": TEST_BUCKET,
        "ANALYSIS_QUEUE": TEST_QUEUE,
    }
    process = subprocess.Popen(  # noqa: S603 (fixed command)
        [
            str(CELERY), "-A", "app.worker.celery_app", "worker", "-Q", TEST_QUEUE,
            "--concurrency=2", "--loglevel=INFO", "--without-mingle", "--without-gossip",
            "-n", f"e2e-{uuid.uuid4().hex[:8]}@%h",
        ],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    output: list[str] = []
    assert process.stdout is not None
    stdout = process.stdout
    threading.Thread(target=lambda: output.extend(stdout), daemon=True).start()
    deadline = time.monotonic() + 90
    while not any("ready." in line for line in output):
        if process.poll() is not None or time.monotonic() > deadline:
            process.kill()
            pytest.fail("worker did not start:\n" + "".join(output[-30:]))
        time.sleep(0.2)
    try:
        yield output
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        _delete_test_queues()


async def wait_for_job(
    client: AsyncClient, job_id: str, limit_seconds: float = 120
) -> tuple[dict[str, Any], list[tuple[str, int]]]:
    seen: list[tuple[str, int]] = []
    deadline = time.monotonic() + limit_seconds
    while time.monotonic() < deadline:
        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        if not seen or seen[-1] != (job["status"], job["progress"]):
            seen.append((job["status"], job["progress"]))
        if job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return job, seen
        await asyncio.sleep(0.1)
    pytest.fail(f"job {job_id} did not finish; states seen: {seen}")


needs_samples = pytest.mark.skipif(
    not all((SAMPLES_DIR / f).exists() for f in ("naip_lax_2024.tif", "naip_sfo_2024.tif")),
    reason="run make samples",
)


@needs_samples
async def test_full_workflow_with_real_imagery(worker: list[str], client: AsyncClient) -> None:
    uploaded = (await upload(client, SAMPLES_DIR / "naip_lax_2024.tif")).json()
    image = (await client.get(f"/api/v1/images/{uploaded['id']}")).json()

    accepted = await client.post("/api/v1/analysis", json={"image_id": uploaded["id"]})
    assert accepted.status_code == 202
    job, seen = await wait_for_job(client, accepted.json()["job_id"])

    assert job["status"] == "COMPLETED", job["error_message"]
    assert job["progress"] == 100
    assert job["model_name"] == "yolo26s-obb"
    progress = [p for _, p in seen]
    assert progress == sorted(progress)  # never goes backwards
    assert any(status == "RUNNING" and 0 < p < 100 for status, p in seen)  # real intermediate

    features = (await client.get(f"/api/v1/images/{uploaded['id']}/detections")).json()["features"]
    planes = [f for f in features if f["properties"]["class_name"] == "plane"]
    assert len(planes) >= 20  # LAX gates: dozens of parked aircraft
    footprint = shape(image["bounds"]).buffer(1e-9)
    assert all(footprint.contains(shape(f["geometry"])) for f in features)
    assert {f["properties"]["job_id"] for f in features} == {job["job_id"]}


@needs_samples
async def test_two_worker_processes_run_jobs_in_parallel(
    worker: list[str], client: AsyncClient
) -> None:
    ids = [
        (await upload(client, SAMPLES_DIR / name)).json()["id"]
        for name in ("naip_lax_2024.tif", "naip_sfo_2024.tif")
    ]
    job_ids = [
        (await client.post("/api/v1/analysis", json={"image_id": i})).json()["job_id"] for i in ids
    ]
    jobs = [(await wait_for_job(client, j))[0] for j in job_ids]

    assert all(j["status"] == "COMPLETED" for j in jobs)
    assert jobs[0]["parameters"]["worker"] != jobs[1]["parameters"]["worker"]
    # Overlapping execution windows: both ran at the same time.
    assert max(j["started_at"] for j in jobs) < min(j["completed_at"] for j in jobs)


async def test_unknown_job_message_goes_to_dead_letter_queue(
    worker: list[str], app: FastAPI
) -> None:
    bogus = str(uuid.uuid4())
    await asyncio.to_thread(
        app.state.celery.send_task,
        TASK_OBJECT_DETECTION,
        args=[bogus],
        task_id=bogus,
        queue=TEST_QUEUE,
    )
    deadline = time.monotonic() + 30
    while _queue_message_count(dead_letter_queue(TEST_QUEUE)) < 1:
        assert time.monotonic() < deadline, "message was not dead-lettered"
        await asyncio.sleep(0.2)
    assert any(bogus in line and "Rejecting" in line for line in worker)


async def test_deterministic_failure_fails_job_without_retry_and_dead_letters(
    worker: list[str], app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    from app.image_service import cog_key
    from tests.rasters import write_geotiff

    image_id = (await upload(client, write_geotiff(tmp_path / "x.tif"))).json()["id"]
    # The imagery disappeared from storage: not a transient error, retrying cannot help.
    app.state.s3.delete_object(Bucket=TEST_BUCKET, Key=cog_key(uuid.UUID(image_id)))
    dead_before = _queue_message_count(dead_letter_queue(TEST_QUEUE))

    job_id = (await client.post("/api/v1/analysis", json={"image_id": image_id})).json()["job_id"]
    job, seen = await wait_for_job(client, job_id, limit_seconds=30)

    assert job["status"] == "FAILED"
    assert "404" in job["error_message"] or "Not Found" in job["error_message"]
    assert ("QUEUED", 0) not in seen[1:]  # never put back for a retry
    deadline = time.monotonic() + 10
    while _queue_message_count(dead_letter_queue(TEST_QUEUE)) <= dead_before:
        assert time.monotonic() < deadline, "failed job message was not dead-lettered"
        await asyncio.sleep(0.2)
