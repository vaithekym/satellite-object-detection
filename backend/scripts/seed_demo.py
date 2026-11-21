"""Load the demo data: upload the sample images through the API and analyse them.

Run from backend/ with the API and a worker running:  python -m scripts.seed_demo
(or `make demo`). Anyone running this gets the same images and, with the same pinned model,
the same detections as on the machine the project was developed on.

Idempotent: images that are already uploaded (same file name) and analyses that already
completed are skipped, so it is safe to run again.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from scripts.download_samples import NAIP_ITEMS, SAMPLES_DIR
from scripts.download_samples import main as download_samples

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
DEMO_FILES = [*NAIP_ITEMS, "rgb_byte_landsat.tif"]
JOB_TIMEOUT_SECONDS = 600


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_services(client: httpx.Client) -> None:
    try:
        ready = client.get("/health/ready")
    except httpx.HTTPError:
        fail(f"cannot reach the API at {API_URL}. Start it with `make backend`.")
    body = ready.json()
    if body.get("status") != "ready":
        down = [name for name, check in body["checks"].items() if not check["ok"]]
        fail(
            f"services not ready: {', '.join(down)}. See /health/ready (bucket: make init-storage)."
        )


def existing_images(client: httpx.Client) -> dict[str, str]:
    items = client.get("/api/v1/images", params={"limit": 200}).json()["items"]
    return {image["filename"]: image["id"] for image in items}


def upload(client: httpx.Client, path: Path) -> str:
    with path.open("rb") as f:
        response = client.post(
            "/api/v1/images/upload", files={"file": (path.name, f, "image/tiff")}, timeout=300
        )
    if response.status_code != 201:
        fail(f"upload of {path.name} failed ({response.status_code}): {response.text}")
    return str(response.json()["id"])


def latest_job(client: httpx.Client, image_id: str) -> dict[str, Any] | None:
    items = client.get("/api/v1/jobs", params={"image_id": image_id, "limit": 1}).json()["items"]
    return items[0] if items else None


def start_analysis(client: httpx.Client, image_id: str) -> str:
    response = client.post("/api/v1/analysis", json={"image_id": image_id})
    if response.status_code in (202, 409):  # 409: already queued or running
        return str(response.json()["job_id"])
    fail(f"could not start analysis ({response.status_code}): {response.text}")
    raise AssertionError  # unreachable


def wait_for(client: httpx.Client, jobs: dict[str, str]) -> None:
    """Poll until every job has finished; jobs maps file name → job id."""
    pending = dict(jobs)
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while pending:
        if time.monotonic() > deadline:
            fail(f"timed out waiting for {', '.join(pending)}. Is `make worker` running?")
        for name, job_id in list(pending.items()):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                detail = job["error_message"] if job["status"] == "FAILED" else job["message"]
                print(f"  {name}: {job['status']} - {detail}")
                del pending[name]
        time.sleep(1)


def main() -> None:
    missing = [name for name in DEMO_FILES if not (SAMPLES_DIR / name).exists()]
    if missing:
        print(f"Downloading {len(missing)} sample image(s)…")
        download_samples(missing)

    with httpx.Client(base_url=API_URL, timeout=30) as client:
        check_services(client)

        uploaded = existing_images(client)
        image_ids: dict[str, str] = {}
        for name in DEMO_FILES:
            if name in uploaded:
                print(f"  {name}: already uploaded")
                image_ids[name] = uploaded[name]
            else:
                image_ids[name] = upload(client, SAMPLES_DIR / name)
                print(f"  {name}: uploaded")

        jobs: dict[str, str] = {}
        for name, image_id in image_ids.items():
            job = latest_job(client, image_id)
            if job and job["status"] == "COMPLETED":
                print(f"  {name}: already analysed - {job['message']}")
            else:
                jobs[name] = start_analysis(client, image_id)
        if jobs:
            print(f"Analysing {len(jobs)} image(s); this needs a running worker (`make worker`)…")
            wait_for(client, jobs)

        stats = client.get("/api/v1/stats").json()
        print(
            f"Done: {stats['images']} images, {stats['detections']} detections "
            f"({stats['detections_by_class']}). Open http://localhost:5173"
        )


if __name__ == "__main__":
    main()
