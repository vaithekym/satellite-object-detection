"""Map tiles must line up with real-world coordinates.

Expected positions are computed with an independent Web Mercator implementation
(the standard OSM slippy-map formulas), not with the libraries under test.
"""

import math
import warnings
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from app.raster import SAFE_GDAL_ENV, create_cog
from app.tiles import TILE_SIZE, render_tile, run_in_env, tile_info
from tests.rasters import write_geotiff

COLORS = {1: (255, 0, 0), 2: (0, 0, 255), 3: (0, 255, 0), 4: (255, 255, 0)}  # NW, NE, SW, SE


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2**z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_to_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2**z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def colored_quadrants(path: Path, size: int, crs: str, transform: Affine) -> Path:
    labels = np.zeros((size, size), dtype=int)
    half = size // 2
    labels[:half, :half], labels[:half, half:] = 1, 2
    labels[half:, :half], labels[half:, half:] = 3, 4
    rgb = np.stack([np.vectorize(lambda v, i=i: COLORS[v][i])(labels) for i in range(3)])
    src = write_geotiff(
        path.with_suffix(".src.tif"),
        width=size,
        height=size,
        count=3,
        crs=crs,
        transform=transform,
        data=rgb.astype("uint8"),
        photometric="RGB",
    )
    create_cog(src, path)
    return path


def decode_png(png: bytes) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile(png) as mem, mem.open() as ds:
            pixels: np.ndarray = ds.read()
            return pixels


def check_tile_alignment(
    cog: Path,
    z: int,
    center: tuple[float, float],
    expected_quadrant: Callable[[float, float, float], int | None],
    margin: float,
) -> int:
    """Render the tile containing `center`; compare every pixel with the expected colour."""
    tx, ty = (int(v) for v in lonlat_to_tile(*center, z))
    env = rasterio.Env(**SAFE_GDAL_ENV)
    png = run_in_env(env, render_tile, str(cog), z, tx, ty, [1, 2, 3], None)
    assert png is not None
    pixels = decode_png(png)  # (4, 256, 256): RGB + alpha
    checked = 0
    for row in range(TILE_SIZE):
        for col in range(TILE_SIZE):
            lon, lat = tile_to_lonlat(tx + (col + 0.5) / TILE_SIZE, ty + (row + 0.5) / TILE_SIZE, z)
            quadrant = expected_quadrant(lon, lat, margin)
            if quadrant is None:
                continue  # too close to an edge to be unambiguous
            if quadrant == 0:
                assert pixels[3, row, col] == 0, f"expected transparent at {lon},{lat}"
            else:
                assert tuple(pixels[:3, row, col]) == COLORS[quadrant], f"at {lon},{lat}"
                assert pixels[3, row, col] == 255
            checked += 1
    return checked


def test_wgs84_raster_tiles_align_with_web_mercator(tmp_path: Path) -> None:
    # 1000x1000 px over lon 10.00-10.10, lat 59.90-60.00 (0.0001° pixels).
    transform = Affine(0.0001, 0, 10.0, 0, -0.0001, 60.0)
    cog = colored_quadrants(tmp_path / "wgs84.tif", 1000, "EPSG:4326", transform)

    def expected(lon: float, lat: float, margin: float) -> int | None:
        if not (10.0 + margin < lon < 10.1 - margin and 59.9 + margin < lat < 60.0 - margin):
            outside = lon < 10.0 - margin or lon > 10.1 + margin
            outside = outside or lat < 59.9 - margin or lat > 60.0 + margin
            return 0 if outside else None
        if abs(lon - 10.05) < margin or abs(lat - 59.95) < margin:
            return None
        return {(True, True): 1, (False, True): 2, (True, False): 3, (False, False): 4}[
            (lon < 10.05, lat > 59.95)
        ]

    # Tile around the centre point (all 4 quadrants) and around the NW corner (edge + outside).
    assert check_tile_alignment(cog, 14, (10.05, 59.95), expected, margin=0.00012) > 50_000
    assert check_tile_alignment(cog, 14, (10.0, 60.0), expected, margin=0.00012) > 50_000


def test_utm_raster_tiles_align_with_web_mercator(tmp_path: Path) -> None:
    # 400x400 px of 5 m in UTM 32N; quadrant boundaries are straight lines in UTM, so they
    # are slightly curved in Web Mercator. Expected quadrants are found via pyproj.
    origin_x, origin_y, res, size = 500_000, 6_650_000, 5.0, 400
    transform = Affine(res, 0, origin_x, 0, -res, origin_y)
    cog = colored_quadrants(tmp_path / "utm.tif", size, "EPSG:32632", transform)
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
    mid_x, mid_y = origin_x + size * res / 2, origin_y - size * res / 2

    def expected(lon: float, lat: float, margin: float) -> int | None:
        x, y = to_utm.transform(lon, lat)
        inside_x = origin_x + margin < x < origin_x + size * res - margin
        inside_y = origin_y - size * res + margin < y < origin_y - margin
        if not (inside_x and inside_y):
            return None
        if abs(x - mid_x) < margin or abs(y - mid_y) < margin:
            return None
        return {(True, True): 1, (False, True): 2, (True, False): 3, (False, False): 4}[
            (x < mid_x, y > mid_y)
        ]

    center = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True).transform(mid_x, mid_y)
    # margin: 1.5 source pixels (7.5 m): nearest-neighbour resampling can shift an edge by
    # up to half a source pixel plus half a tile pixel (~1.2 m at z16 here).
    assert check_tile_alignment(cog, 16, center, expected, margin=7.5) > 50_000


def test_tile_info_bounds_and_zooms(tmp_path: Path) -> None:
    transform = Affine(0.0001, 0, 10.0, 0, -0.0001, 60.0)
    cog = colored_quadrants(tmp_path / "wgs84.tif", 1000, "EPSG:4326", transform)
    info = run_in_env(rasterio.Env(**SAFE_GDAL_ENV), tile_info, str(cog))
    assert info.bounds == pytest.approx((10.0, 59.9, 10.1, 60.0))
    assert 0 <= info.minzoom <= info.maxzoom <= 24
    # Max zoom: tile pixel no coarser than the source pixel (0.0001° ≈ 5.6 m at 60° N).
    assert 360 / (2**info.maxzoom * TILE_SIZE) <= 0.0001 * 2


def test_tile_outside_image_returns_none(tmp_path: Path) -> None:
    transform = Affine(0.0001, 0, 10.0, 0, -0.0001, 60.0)
    cog = colored_quadrants(tmp_path / "wgs84.tif", 1000, "EPSG:4326", transform)
    tx, ty = (int(v) for v in lonlat_to_tile(-120.0, 35.0, 14))
    env = rasterio.Env(**SAFE_GDAL_ENV)
    assert run_in_env(env, render_tile, str(cog), 14, tx, ty, [1, 2, 3], None) is None


def test_uint16_tiles_use_stored_display_range(tmp_path: Path) -> None:
    data = np.full((1, 256, 256), 3000, dtype="uint16")
    transform = Affine(0.0001, 0, 10.0, 0, -0.0001, 60.0)
    src = write_geotiff(
        tmp_path / "u16.tif",
        count=1,
        width=256,
        height=256,
        dtype="uint16",
        data=data,
        crs="EPSG:4326",
        transform=transform,
    )
    cog = tmp_path / "u16.cog.tif"
    create_cog(src, cog)
    tx, ty = (int(v) for v in lonlat_to_tile(10.0128, 59.9872, 15))
    png = run_in_env(
        rasterio.Env(**SAFE_GDAL_ENV), render_tile, str(cog), 15, tx, ty, [1], [(2000.0, 4000.0)]
    )
    assert png is not None
    pixels = decode_png(png)
    visible = pixels[-1] == 255
    assert visible.any()
    assert np.all(np.abs(pixels[0][visible].astype(int) - 128) <= 1)  # 3000 is mid-range
