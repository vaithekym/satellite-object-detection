from pathlib import Path

from httpx import AsyncClient, Response

TEST_BUCKET = "satellite-detection-test"
TEST_QUEUE = "analysis-test"  # separate from the dev worker's "analysis" queue


async def upload(client: AsyncClient, path: Path, name: str | None = None) -> Response:
    with path.open("rb") as f:
        return await client.post(
            "/api/v1/images/upload", files={"file": (name or path.name, f, "image/tiff")}
        )
