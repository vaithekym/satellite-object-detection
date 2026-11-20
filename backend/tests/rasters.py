"""Deterministic synthetic GeoTIFF fixtures for unit tests."""

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.transform import from_origin

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"

# 10 m pixels, upper-left corner at 500000 E / 6650000 N in UTM 32N (near Oslo).
UTM_TRANSFORM = from_origin(500_000, 6_650_000, 10, 10)


def write_geotiff(
    path: Path,
    *,
    width: int = 64,
    height: int = 64,
    count: int = 3,
    dtype: str = "uint8",
    crs: str | None = "EPSG:32632",
    transform: Affine | None = UTM_TRANSFORM,
    nodata: float | None = None,
    tags: dict[str, str] | None = None,
    data: np.ndarray[Any, Any] | None = None,
    **creation_options: Any,
) -> Path:
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": count,
        "dtype": dtype,
        "nodata": nodata,
        **creation_options,
    }
    if crs is not None:
        profile["crs"] = crs
    if transform is not None:
        profile["transform"] = transform
    if data is None:
        rng = np.random.default_rng(42)
        data = rng.integers(1, 200, size=(count, height, width)).astype(dtype)
    with rasterio.open(path, "w", **profile) as dst:
        if data.size:
            dst.write(data)
        if tags:
            dst.update_tags(**tags)
    return path
