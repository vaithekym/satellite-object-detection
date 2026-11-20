"""Upload API against the real test database and a dedicated MinIO test bucket."""

import warnings
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from affine import Affine
from fastapi import FastAPI
from httpx import AsyncClient
from rasterio.errors import NotGeoreferencedWarning
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.image_service import cog_key, original_key, preview_key
from tests.api_helpers import TEST_BUCKET, upload
from tests.rasters import SAMPLES_DIR, write_geotiff
from tests.test_tiles import lonlat_to_tile


def stored_keys(app: FastAPI) -> list[str]:
    listed = app.state.s3.list_objects_v2(Bucket=TEST_BUCKET)
    return sorted(obj["Key"] for obj in listed.get("Contents", []))


async def image_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        return int(await session.scalar(text("SELECT count(*) FROM images")) or 0)


@pytest.mark.skipif(not (SAMPLES_DIR / "naip_san_2024.tif").exists(), reason="run make samples")
async def test_upload_real_naip_image(app: FastAPI, client: AsyncClient) -> None:
    response = await upload(client, SAMPLES_DIR / "naip_san_2024.tif")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "naip_san_2024.tif"
    assert body["status"] == "READY"
    image_id = body["id"]

    # Original, COG and preview are in object storage.
    assert stored_keys(app) == sorted(
        [original_key(image_id), cog_key(image_id), preview_key(image_id)]
    )
    head = app.state.s3.head_object(Bucket=TEST_BUCKET, Key=original_key(image_id))
    assert head["ContentLength"] == (SAMPLES_DIR / "naip_san_2024.tif").stat().st_size

    detail = (await client.get(f"/api/v1/images/{image_id}")).json()
    assert (detail["width"], detail["height"], detail["band_count"]) == (2048, 2048, 4)
    assert detail["crs"] == "EPSG:26911"
    assert detail["resolution_x"] == pytest.approx(0.6)
    assert detail["acquisition_date"] == "2024-05-06T16:00:00Z"
    assert detail["bounds"]["type"] == "Polygon"
    min_lon, min_lat, max_lon, max_lat = detail["metadata"]["wgs84_bbox"]
    assert -117.21 < min_lon < max_lon < -117.18  # San Diego International Airport
    assert 32.72 < min_lat < max_lat < 32.75

    listing = (await client.get("/api/v1/images")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == image_id

    preview = await client.get(f"/api/v1/images/{image_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")


async def test_upload_sanitizes_filename(client: AsyncClient, tmp_path: Path) -> None:
    path = write_geotiff(tmp_path / "x.tif")
    response = await upload(client, path, name="../../etc/evil.tif")
    assert response.status_code == 201
    assert response.json()["filename"] == "evil.tif"


async def test_rejects_non_tiff(app: FastAPI, client: AsyncClient, tmp_path: Path) -> None:
    fake = tmp_path / "fake.tif"
    fake.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    response = await upload(client, fake)
    assert response.status_code == 415
    assert stored_keys(app) == []
    assert await image_count(app) == 0


async def test_rejects_raster_without_georeferencing(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        path = write_geotiff(tmp_path / "plain.tif", crs=None, transform=None)
    response = await upload(client, path)
    assert response.status_code == 422
    assert "coordinate reference system" in response.json()["detail"]
    assert stored_keys(app) == []
    assert await image_count(app) == 0


async def test_rejects_corrupted_tiff(app: FastAPI, client: AsyncClient, tmp_path: Path) -> None:
    path = write_geotiff(tmp_path / "ok.tif", width=512, height=512, compress="deflate")
    broken = tmp_path / "broken.tif"
    broken.write_bytes(path.read_bytes()[:2000])
    response = await upload(client, broken)
    assert response.status_code == 422
    assert stored_keys(app) == []


async def test_rejects_file_over_size_limit(
    app: FastAPI, client: AsyncClient, tmp_path: Path
) -> None:
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(update={"max_upload_bytes": 1000})
    path = write_geotiff(tmp_path / "big.tif", width=256, height=256)
    response = await upload(client, path)
    assert response.status_code == 413
    assert stored_keys(app) == []


async def test_requires_content_length(client: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"II*\x00"

    response = await client.post(
        "/api/v1/images/upload",
        content=chunks(),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 411


async def test_requires_file_field(client: AsyncClient) -> None:
    response = await client.post("/api/v1/images/upload", files={"other": ("a.txt", b"hi")})
    assert response.status_code == 422


async def test_storage_is_cleaned_up_when_database_insert_fails(
    app: FastAPI, client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_commit(self: AsyncSession) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await upload(client, write_geotiff(tmp_path / "x.tif"))
    assert stored_keys(app) == []


async def test_unknown_image_returns_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/images/{missing}")).status_code == 404
    assert (await client.get(f"/api/v1/images/{missing}/preview")).status_code == 404


async def test_tilejson_and_tiles_for_uploaded_image(client: AsyncClient, tmp_path: Path) -> None:
    transform = Affine(0.0001, 0, 10.0, 0, -0.0001, 60.0)  # lon 10.0-10.1, lat 59.9-60.0
    path = write_geotiff(
        tmp_path / "geo.tif", width=1000, height=1000, crs="EPSG:4326", transform=transform
    )
    image_id = (await upload(client, path)).json()["id"]

    tilejson = (await client.get(f"/api/v1/images/{image_id}/tilejson.json")).json()
    assert tilejson["bounds"] == pytest.approx([10.0, 59.9, 10.1, 60.0])
    assert tilejson["tiles"][0].endswith(f"/api/v1/images/{image_id}/tiles/{{z}}/{{x}}/{{y}}.png")
    z = tilejson["maxzoom"]
    assert 0 <= tilejson["minzoom"] <= z <= 24

    x, y = (int(v) for v in lonlat_to_tile(10.05, 59.95, z))
    tile = await client.get(f"/api/v1/images/{image_id}/tiles/{z}/{x}/{y}.png")
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/png"
    assert tile.content.startswith(b"\x89PNG")

    base = f"/api/v1/images/{image_id}/tiles"
    assert (await client.get(f"{base}/{z}/0/0.png")).status_code == 404  # outside the image
    assert (await client.get(f"{base}/2/4/0.png")).status_code == 404  # x >= 2^z
    assert (await client.get(f"{base}/25/0/0.png")).status_code == 422  # zoom too deep
