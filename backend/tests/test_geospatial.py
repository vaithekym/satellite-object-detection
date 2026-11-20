from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS

from app.geospatial import create_raster_tiles, geo_to_pixel, pixel_to_geo, reproject_raster
from app.raster import open_raster
from tests.rasters import UTM_TRANSFORM, write_geotiff

UTM32 = "EPSG:32632"
TO_WGS84 = Transformer.from_crs(UTM32, "EPSG:4326", always_xy=True)


def test_pixel_corner_and_center_convention() -> None:
    # (0, 0) is the upper-left corner of the first pixel; (0.5, 0.5) its centre.
    assert pixel_to_geo(UTM_TRANSFORM, UTM32, 0, 0, dst_crs=UTM32) == (500_000, 6_650_000)
    assert pixel_to_geo(UTM_TRANSFORM, UTM32, 0.5, 0.5, dst_crs=UTM32) == (500_005, 6_649_995)
    # Rows grow southwards, columns eastwards.
    assert pixel_to_geo(UTM_TRANSFORM, UTM32, 10, 20, dst_crs=UTM32) == (500_100, 6_649_800)


def test_pixel_to_wgs84_matches_independent_pyproj_transform() -> None:
    lon, lat = pixel_to_geo(UTM_TRANSFORM, UTM32, 100, 200)
    expected = TO_WGS84.transform(500_000 + 100 * 10, 6_650_000 - 200 * 10)
    assert (lon, lat) == pytest.approx(expected, abs=1e-12)
    assert lon == pytest.approx(9.0, abs=0.02)  # close to the zone 32 central meridian
    assert lat == pytest.approx(59.96, abs=0.02)


def test_geo_to_pixel_roundtrip_with_arrays() -> None:
    rng = np.random.default_rng(0)
    cols = rng.uniform(0, 5000, 100)
    rows = rng.uniform(0, 5000, 100)
    lons, lats = pixel_to_geo(UTM_TRANSFORM, UTM32, cols, rows)
    back_cols, back_rows = geo_to_pixel(UTM_TRANSFORM, UTM32, lons, lats)
    np.testing.assert_allclose(back_cols, cols, atol=1e-6)
    np.testing.assert_allclose(back_rows, rows, atol=1e-6)


@pytest.mark.parametrize("tile_size", [256, 512, 1024])
def test_tiles_cover_raster_with_overlap(tile_size: int) -> None:
    width, height, overlap = 2500, 1700, 64
    tiles = create_raster_tiles(width, height, tile_size, overlap)

    covered = np.zeros((height, width), dtype=bool)
    for t in tiles:
        assert (t.width, t.height) == (tile_size, tile_size)  # edge tiles are not truncated
        assert t.col_off + t.width <= width and t.row_off + t.height <= height
        covered[t.row_off : t.row_off + t.height, t.col_off : t.col_off + t.width] = True
    assert covered.all()

    col_offsets = sorted({t.col_off for t in tiles})
    steps = np.diff(col_offsets)
    assert (steps <= tile_size - overlap).all()  # neighbours overlap by at least `overlap`
    assert col_offsets[-1] == width - tile_size


def test_raster_smaller_than_tile_gives_single_tile() -> None:
    tiles = create_raster_tiles(100, 80, 512, 64)
    assert [(t.col_off, t.row_off, t.width, t.height) for t in tiles] == [(0, 0, 100, 80)]


def test_invalid_tile_parameters() -> None:
    with pytest.raises(ValueError):
        create_raster_tiles(100, 100, 256, 256)
    with pytest.raises(ValueError):
        create_raster_tiles(100, 100, 0, 0)


def quadrant_raster(path: Path) -> Path:
    """200x200 UTM raster: NW=1, NE=2, SW=3, SE=4."""
    data = np.zeros((1, 200, 200), dtype="uint8")
    data[0, :100, :100], data[0, :100, 100:] = 1, 2
    data[0, 100:, :100], data[0, 100:, 100:] = 3, 4
    return write_geotiff(path, width=200, height=200, count=1, data=data, nodata=0)


@pytest.mark.parametrize("dst_crs", ["EPSG:4326", "EPSG:3857"])
def test_reproject_raster_keeps_locations(tmp_path: Path, dst_crs: str) -> None:
    src = quadrant_raster(tmp_path / "q.tif")
    dst = tmp_path / "reprojected.tif"
    reproject_raster(src, dst, dst_crs, resampling=rasterio.enums.Resampling.nearest)

    with open_raster(dst) as ds:
        assert ds.crs == CRS.from_user_input(dst_crs)
        to_dst = Transformer.from_crs(UTM32, dst_crs, always_xy=True)
        # Centre of each source quadrant must carry the same value after reprojection.
        for (x, y), expected in {
            (500_500, 6_649_500): 1,
            (501_500, 6_649_500): 2,
            (500_500, 6_648_500): 3,
            (501_500, 6_648_500): 4,
        }.items():
            value = next(ds.sample([to_dst.transform(x, y)]))[0]
            assert value == expected
