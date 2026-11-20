import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.enums import ColorInterp
from rasterio.errors import NotGeoreferencedWarning
from shapely.geometry import Point

from app.image_service import sanitize_filename
from app.raster import (
    RasterLimits,
    RasterValidationError,
    create_cog,
    display_bands,
    has_tiff_signature,
    inspect_raster,
    open_raster,
    parse_datetime,
    render_preview,
    to_uint8,
)
from tests.rasters import SAMPLES_DIR, UTM_TRANSFORM, write_geotiff

LIMITS = RasterLimits(max_pixels=50_000_000, max_bands=16, max_uncompressed_bytes=1024**3)


def test_tiff_signatures() -> None:
    assert has_tiff_signature(b"II*\x00rest")
    assert has_tiff_signature(b"MM\x00*rest")
    assert has_tiff_signature(b"II+\x00rest")  # BigTIFF
    assert not has_tiff_signature(b"\x89PNG\r\n\x1a\n")
    assert not has_tiff_signature(b"<VRTDataset>")
    assert not has_tiff_signature(b"")


def test_metadata_of_projected_raster(tmp_path: Path) -> None:
    path = write_geotiff(tmp_path / "utm.tif", width=100, height=50, count=3, nodata=0)
    info = inspect_raster(path, LIMITS)

    assert (info.width, info.height, info.band_count) == (100, 50, 3)
    assert info.crs == "EPSG:32632"
    assert (info.resolution_x, info.resolution_y) == (10, 10)
    assert info.metadata["nodata"] == 0
    assert info.metadata["dtypes"] == ["uint8"] * 3
    assert info.metadata["crs_units"] == "metre"
    assert info.metadata["native_bounds"] == [500_000, 6_649_500, 501_000, 6_650_000]
    assert info.acquisition_date is None

    # Each native corner, reprojected independently with pyproj, lies on the footprint.
    to_wgs84 = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
    for x, y in [(500_000, 6_650_000), (501_000, 6_649_500)]:
        lon, lat = to_wgs84.transform(x, y)
        assert info.footprint_wgs84.distance(Point(lon, lat)) < 1e-9
    # 500000 E is the central meridian of UTM zone 32 (9° E).
    assert info.footprint_wgs84.bounds[0] == pytest.approx(9.0, abs=1e-9)


def test_geographic_raster_footprint_equals_bounds(tmp_path: Path) -> None:
    transform = Affine(0.001, 0, 10.7, 0, -0.001, 59.95)
    path = write_geotiff(tmp_path / "wgs84.tif", crs="EPSG:4326", transform=transform)
    info = inspect_raster(path, LIMITS)
    assert info.crs == "EPSG:4326"
    assert info.metadata["crs_units"] == "degree"
    assert info.footprint_wgs84.bounds == pytest.approx((10.7, 59.886, 10.764, 59.95))


def test_acquisition_date_only_from_explicit_tags(tmp_path: Path) -> None:
    tagged = write_geotiff(tmp_path / "a.tif", tags={"ACQUISITIONDATETIME": "2024-05-06T10:30:00Z"})
    info = inspect_raster(tagged, LIMITS)
    assert info.acquisition_date == datetime(2024, 5, 6, 10, 30, tzinfo=UTC)
    assert info.metadata["acquisition_date_source"] == "ACQUISITIONDATETIME"
    assert info.metadata["acquisition_timezone_assumed_utc"] is False

    # TIFFTAG_DATETIME is the file creation time, not the acquisition time.
    created = write_geotiff(tmp_path / "b.tif", tags={"TIFFTAG_DATETIME": "2024:05:06 10:30:00"})
    assert inspect_raster(created, LIMITS).acquisition_date is None


def test_parse_datetime_formats() -> None:
    assert parse_datetime("2024:05:06 10:30:00") == (datetime(2024, 5, 6, 10, 30, tzinfo=UTC), True)
    assert parse_datetime("2024-05-06T10:30:00+02:00") is not None
    assert parse_datetime("not a date") is None


def test_rejects_raster_without_crs(tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        path = write_geotiff(tmp_path / "plain.tif", crs=None, transform=None)
    with pytest.raises(RasterValidationError, match="coordinate reference system"):
        inspect_raster(path, LIMITS)


def test_rejects_rotated_raster(tmp_path: Path) -> None:
    rotated = UTM_TRANSFORM @ Affine.rotation(30)
    path = write_geotiff(tmp_path / "rotated.tif", transform=rotated)
    with pytest.raises(RasterValidationError, match="Rotated"):
        inspect_raster(path, LIMITS)


def test_rejects_decompression_bomb(tmp_path: Path) -> None:
    # 100k x 100k pixel sparse GeoTIFF: ~1 MB on disk (tile index only), 30 GB if decoded.
    path = write_geotiff(
        tmp_path / "bomb.tif",
        width=100_000,
        height=100_000,
        data=np.zeros((0, 0, 0), dtype="uint8"),
        tiled=True,
        compress="deflate",
        sparse_ok=True,
    )
    assert path.stat().st_size < 2 * 1024 * 1024
    with pytest.raises(RasterValidationError, match="too large"):
        inspect_raster(path, LIMITS)


def test_rejects_too_many_bands(tmp_path: Path) -> None:
    path = write_geotiff(tmp_path / "bands.tif", count=20, width=8, height=8)
    with pytest.raises(RasterValidationError, match="1 to 16 bands"):
        inspect_raster(path, LIMITS)


def test_rejects_unsupported_dtype(tmp_path: Path) -> None:
    data = np.ones((1, 8, 8), dtype="complex64")
    path = write_geotiff(
        tmp_path / "complex.tif", count=1, width=8, height=8, data=data, dtype="complex64"
    )
    with pytest.raises(RasterValidationError, match="Unsupported data type"):
        inspect_raster(path, LIMITS)


def test_rejects_truncated_file(tmp_path: Path) -> None:
    path = write_geotiff(tmp_path / "ok.tif", width=512, height=512, compress="deflate")
    truncated = tmp_path / "truncated.tif"
    truncated.write_bytes(path.read_bytes()[:2000])
    with pytest.raises(RasterValidationError):
        inspect_raster(truncated, LIMITS)


def test_rejects_non_tiff_even_if_gdal_could_read_it(tmp_path: Path) -> None:
    png = tmp_path / "image.tif"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(png, "w", driver="PNG", width=4, height=4, count=1, dtype="uint8") as d:
            d.write(np.zeros((1, 4, 4), dtype="uint8"))
    with pytest.raises(RasterValidationError, match="not a readable GeoTIFF"):
        inspect_raster(png, LIMITS)


def test_create_cog(tmp_path: Path) -> None:
    src = write_geotiff(tmp_path / "src.tif", width=1500, height=1200, nodata=0)
    cog = tmp_path / "cog.tif"
    create_cog(src, cog)
    with open_raster(cog) as ds, open_raster(src) as original:
        assert ds.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert ds.block_shapes[0] == (512, 512)
        assert ds.overviews(1)  # internal overviews present
        assert ds.crs == original.crs
        assert ds.transform == original.transform
        assert ds.nodata == 0
        assert np.array_equal(ds.read(), original.read())  # lossless


def test_render_preview_is_png_with_transparent_nodata(tmp_path: Path) -> None:
    data = np.full((3, 200, 400), 120, dtype="uint8")
    data[:, :, :100] = 0  # left quarter is NoData
    path = write_geotiff(tmp_path / "p.tif", width=400, height=200, nodata=0, data=data)

    preview_result = render_preview(path, max_size=100)
    assert preview_result.bands == [1, 2, 3]
    assert preview_result.display_ranges is None  # 8-bit data is not stretched
    png = preview_result.png
    assert png.startswith(b"\x89PNG")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        preview_path = tmp_path / "preview.png"
        preview_path.write_bytes(png)
        with rasterio.open(preview_path) as preview:
            assert (preview.width, preview.height, preview.count) == (100, 50, 4)
            alpha = preview.read(4)
    assert alpha[:, :20].max() == 0  # NoData → transparent
    assert alpha[:, 30:].min() == 255


def test_display_bands_prefers_rgb_color_interpretation(tmp_path: Path) -> None:
    path = write_geotiff(tmp_path / "bgrn.tif", count=4)
    with rasterio.open(path, "r+") as ds:
        ds.colorinterp = [
            ColorInterp.blue,
            ColorInterp.green,
            ColorInterp.red,
            ColorInterp.undefined,
        ]
    with open_raster(path) as ds:
        assert display_bands(ds) == [3, 2, 1]

    single = write_geotiff(tmp_path / "gray.tif", count=1)
    with open_raster(single) as ds:
        assert display_bands(ds) == [1]


def test_to_uint8_stretches_non_byte_data() -> None:
    data = np.ma.masked_array(np.linspace(1000, 5000, 100).reshape(1, 10, 10).astype("uint16"))
    out = to_uint8(data)
    assert out.dtype == np.uint8
    assert out.min() == 0 and out.max() == 255


def test_sanitize_filename() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\x\\scene.tif") == "scene.tif"
    assert sanitize_filename("a\x00b\nc.tif") == "abc.tif"
    assert sanitize_filename("") == "upload.tif"
    assert sanitize_filename(None) == "upload.tif"


@pytest.mark.skipif(not (SAMPLES_DIR / "rgb_byte_landsat.tif").exists(), reason="run make samples")
def test_real_landsat_sample_metadata() -> None:
    info = inspect_raster(SAMPLES_DIR / "rgb_byte_landsat.tif", LIMITS)
    assert (info.width, info.height, info.band_count) == (791, 718, 3)
    assert info.crs == "EPSG:32618"
    assert info.resolution_x == pytest.approx(300.0379, abs=1e-4)
    assert info.metadata["nodata"] == 0
    # Scene over the Bahamas (UTM zone 18N).
    min_lon, min_lat, max_lon, max_lat = info.footprint_wgs84.bounds
    assert -79.0 < min_lon < max_lon < -76.5
    assert 23.5 < min_lat < max_lat < 25.6
