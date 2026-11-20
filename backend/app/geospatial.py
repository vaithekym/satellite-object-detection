"""Pixel ↔ geographic coordinate conversion, processing windows and reprojection.

Pixel coordinates follow the GDAL convention: (col, row) = (0, 0) is the upper-left corner
of the upper-left pixel; the centre of that pixel is (0.5, 0.5). Pixel coordinates are never
geographic coordinates: they are mapped through the raster's affine transform into the
raster's own CRS, and only then reprojected (e.g. to EPSG:4326).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

from app.raster import SAFE_GDAL_ENV, open_raster

Coords = float | npt.NDArray[np.float64]
WGS84 = "EPSG:4326"


def _transformer(src: CRS | str, dst: CRS | str) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def pixel_to_geo(
    transform: Affine, raster_crs: CRS | str, col: Coords, row: Coords, dst_crs: CRS | str = WGS84
) -> tuple[Coords, Coords]:
    """Pixel (col, row) → (x, y) in dst_crs (lon/lat for EPSG:4326). Accepts arrays."""
    x, y = transform @ (col, row)  # type: ignore[operator]  # affine accepts numpy arrays
    if CRS.from_user_input(raster_crs) == CRS.from_user_input(dst_crs):
        return x, y
    lon, lat = _transformer(raster_crs, dst_crs).transform(x, y)
    return lon, lat


def geo_to_pixel(
    transform: Affine, raster_crs: CRS | str, x: Coords, y: Coords, src_crs: CRS | str = WGS84
) -> tuple[Coords, Coords]:
    """(x, y) in src_crs → fractional pixel (col, row). Accepts arrays."""
    if CRS.from_user_input(raster_crs) != CRS.from_user_input(src_crs):
        x, y = _transformer(src_crs, raster_crs).transform(x, y)
    col, row = ~transform @ (x, y)
    return col, row


@dataclass(frozen=True)
class TileWindow:
    col_off: int
    row_off: int
    width: int
    height: int

    @property
    def window(self) -> Window:
        return Window(self.col_off, self.row_off, self.width, self.height)


def _offsets(length: int, tile: int, stride: int) -> list[int]:
    if length <= tile:
        return [0]
    offsets = list(range(0, length - tile + 1, stride))
    if offsets[-1] + tile < length:
        offsets.append(length - tile)  # last tile is shifted back so it stays full-size
    return offsets


def create_raster_tiles(width: int, height: int, tile_size: int, overlap: int) -> list[TileWindow]:
    """Overlapping processing windows that cover the whole raster.

    Tiles are tile_size x tile_size; edge tiles are shifted inwards (overlapping more) rather
    than truncated, so every tile has the same shape. Rasters smaller than tile_size give a
    single tile of the raster's own size.
    """
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if not 0 <= overlap < tile_size:
        raise ValueError("overlap must be >= 0 and smaller than tile_size")
    stride = tile_size - overlap
    return [
        TileWindow(col, row, min(tile_size, width), min(tile_size, height))
        for row in _offsets(height, tile_size, stride)
        for col in _offsets(width, tile_size, stride)
    ]


def reproject_raster(
    src_path: Path,
    dst_path: Path,
    dst_crs: CRS | str,
    resampling: Resampling = Resampling.bilinear,
    resolution: float | None = None,
) -> None:
    """Reproject to dst_crs (GeoTIFF). Streams through a warped VRT, so memory stays bounded."""
    options: dict[str, Any] = {"crs": CRS.from_user_input(dst_crs), "resampling": resampling}
    with rasterio.Env(**SAFE_GDAL_ENV), open_raster(src_path) as src:
        if resolution is not None:
            from rasterio.warp import calculate_default_transform

            transform, width, height = calculate_default_transform(
                src.crs, options["crs"], src.width, src.height, *src.bounds, resolution=resolution
            )
            options |= {"transform": transform, "width": width, "height": height}
        with WarpedVRT(src, **options) as vrt:
            rio_copy(vrt, str(dst_path), driver="GTiff", tiled=True, compress="deflate")
