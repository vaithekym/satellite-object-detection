"""Turn raster windows into model input.

Multispectral handling: the detector is trained on RGB aerial imagery, so only the display
bands are used — the bands tagged red/green/blue, otherwise the first three (grayscale is
repeated to three channels). Extra bands such as NIR are ignored for detection. Non-8-bit
data is scaled to 0-255 with the per-image contrast range computed at upload, so every tile
of an image is scaled identically. NoData pixels are set to black.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from rasterio.io import DatasetReader

from app.geospatial import TileWindow
from app.raster import DisplayRanges, to_uint8


@dataclass(frozen=True)
class PreparedTile:
    window: TileWindow
    image: npt.NDArray[np.uint8]  # (H, W, 3) RGB
    valid_fraction: float  # share of pixels that are not NoData


def prepare_tile(
    src: DatasetReader, window: TileWindow, bands: list[int], ranges: DisplayRanges | None
) -> PreparedTile:
    data = src.read(bands, window=window.window, masked=True)
    nodata = np.ma.getmaskarray(data).any(axis=0)
    channels = to_uint8(data, ranges)
    if channels.shape[0] == 1:
        channels = np.repeat(channels, 3, axis=0)
    image = np.ascontiguousarray(channels.transpose(1, 2, 0))
    image[nodata] = 0
    return PreparedTile(window, image, float(1.0 - nodata.mean()))
