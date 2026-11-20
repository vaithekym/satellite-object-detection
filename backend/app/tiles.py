"""XYZ map tiles (Web Mercator, EPSG:3857) rendered on demand from an image's COG.

GDAL reads only the byte ranges it needs from the COG in object storage (/vsis3/), and
rio-tiler reprojects the source CRS into the requested Web Mercator tile.
"""

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import numpy as np
import rasterio
from rasterio.session import AWSSession
from rio_tiler.errors import NoOverviewWarning, TileOutsideBounds
from rio_tiler.io import Reader

from app.config import Settings
from app.raster import SAFE_GDAL_ENV, DisplayRanges

TILE_SIZE = 256


@dataclass(frozen=True)
class TileInfo:
    minzoom: int
    maxzoom: int
    bounds: tuple[float, float, float, float]  # west, south, east, north (EPSG:4326)


def s3_url(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def s3_gdal_env(settings: Settings) -> rasterio.Env:
    endpoint = urlparse(settings.s3_endpoint_url)
    session = AWSSession(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        endpoint_url=endpoint.netloc,
    )
    return rasterio.Env(
        session=session,
        AWS_HTTPS="YES" if endpoint.scheme == "https" else "NO",
        AWS_VIRTUAL_HOSTING="FALSE",
        VSI_CACHE="TRUE",
        GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        **SAFE_GDAL_ENV,
    )


def run_in_env[T](env: rasterio.Env, func: Callable[..., T], *args: Any) -> T:
    """Run func inside a GDAL environment (GDAL config is per thread, so call this in the
    worker thread that does the reading)."""
    with env, warnings.catch_warnings():
        warnings.simplefilter("ignore", NoOverviewWarning)
        return func(*args)


def tile_info(source: str) -> TileInfo:
    with Reader(source) as cog:
        west, south, east, north = cog.get_geographic_bounds(cog.tms.rasterio_geographic_crs)
        return TileInfo(cog.minzoom, cog.maxzoom, (west, south, east, north))


def render_tile(
    source: str, z: int, x: int, y: int, bands: list[int], ranges: DisplayRanges | None
) -> bytes | None:
    """PNG for tile z/x/y with NoData transparent, or None if the tile misses the image."""
    with Reader(source) as cog:
        try:
            image = cog.tile(x, y, z, tilesize=TILE_SIZE, indexes=bands)
        except TileOutsideBounds:
            return None
    if image.array.dtype != np.uint8:
        if ranges is None:
            info = np.iinfo(image.array.dtype) if image.array.dtype.kind in "iu" else None
            ranges = [(info.min, info.max) if info else (0.0, 1.0)] * image.count
        image.rescale(in_range=[(low, high) for low, high in ranges])
    png: bytes = image.render(img_format="PNG", add_mask=True)
    return png
