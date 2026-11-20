"""Raster inspection, validation and conversion.

Uploaded rasters are untrusted input: they are only opened with the GTiff driver, GDAL is
not allowed to look for sidecar files, and size/band limits are checked from the header
before any pixel data is read (protection against decompression bombs).
"""

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import rasterio
import shapely
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.io import DatasetReader, MemoryFile
from rasterio.shutil import copy as rio_copy
from shapely.geometry import Polygon, box

TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")  # TIFF and BigTIFF
SAFE_GDAL_ENV = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
SUPPORTED_DTYPES = {"uint8", "uint16", "int16", "uint32", "int32", "float32", "float64"}
# Tags that explicitly describe the acquisition time. TIFFTAG_DATETIME is deliberately not
# used: per the TIFF spec it is the file creation time, not when the image was captured.
ACQUISITION_TAGS = (
    "ACQUISITIONDATETIME",
    "ACQUISITION_DATETIME",
    "ACQUISITION_DATE",
    "DATE_ACQUIRED",
    "SENSING_TIME",
)
MAX_TAGS = 100
MAX_TAG_LENGTH = 500


class RasterValidationError(ValueError):
    """The raster was rejected. The message is safe to show to API clients."""


@dataclass(frozen=True)
class RasterLimits:
    max_pixels: int
    max_bands: int
    max_uncompressed_bytes: int


@dataclass(frozen=True)
class RasterInfo:
    width: int
    height: int
    band_count: int
    crs: str  # "EPSG:xxxx", or "CUSTOM" (full WKT is in metadata)
    resolution_x: float  # source CRS units per pixel
    resolution_y: float
    footprint_wgs84: Polygon
    acquisition_date: datetime | None
    metadata: dict[str, Any]


def has_tiff_signature(header: bytes) -> bool:
    return header[:4] in TIFF_SIGNATURES


def open_raster(path: Path) -> DatasetReader:
    """Open a local GeoTIFF with the GTiff driver only. Georeferencing is validated by callers."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            return rasterio.open(path, driver="GTiff")
    except RasterioError as exc:
        raise RasterValidationError("File is not a readable GeoTIFF") from exc


def inspect_raster(path: Path, limits: RasterLimits) -> RasterInfo:
    with rasterio.Env(**SAFE_GDAL_ENV), open_raster(path) as src:
        _check_limits(src, limits)
        if src.crs is None:
            raise RasterValidationError("Raster has no coordinate reference system")
        if src.transform.is_identity:
            raise RasterValidationError("Raster has no geotransform (not georeferenced)")
        if not src.transform.is_rectilinear:
            raise RasterValidationError("Rotated or skewed rasters are not supported")
        try:
            src.read(1, window=src.block_window(1, 0, 0))  # first block must decode
        except RasterioError as exc:
            raise RasterValidationError("Raster pixel data could not be read") from exc

        footprint = footprint_wgs84(src.crs, src.bounds)
        tags = src.tags()
        acquisition, source_tag, assumed_utc = find_acquisition_date(tags)
        epsg = src.crs.to_epsg()
        metadata: dict[str, Any] = {
            "band_count": src.count,
            "dtypes": list(src.dtypes),
            "nodata": _json_number(src.nodata),
            "band_descriptions": list(src.descriptions),
            "color_interpretation": [c.name for c in src.colorinterp],
            "compression": src.compression.value if src.compression else None,
            "block_shapes": [list(shape) for shape in src.block_shapes],
            "overview_count": len(src.overviews(1)),
            "native_bounds": list(src.bounds),
            "wgs84_bbox": list(footprint.bounds),
            "crs_wkt": src.crs.to_wkt(),
            # Unit of resolution_x/y: "degree" if geographic, else e.g. "metre", "US survey foot".
            "crs_units": "degree" if src.crs.is_geographic else src.crs.linear_units,
            "acquisition_date_source": source_tag,
            "acquisition_timezone_assumed_utc": assumed_utc,
            "tags": _sanitize_tags(tags),
        }
        return RasterInfo(
            width=src.width,
            height=src.height,
            band_count=src.count,
            crs=f"EPSG:{epsg}" if epsg else "CUSTOM",
            resolution_x=abs(src.transform.a),
            resolution_y=abs(src.transform.e),
            footprint_wgs84=footprint,
            acquisition_date=acquisition,
            metadata=metadata,
        )


def _check_limits(src: DatasetReader, limits: RasterLimits) -> None:
    if src.width <= 0 or src.height <= 0:
        raise RasterValidationError("Raster has invalid dimensions")
    if src.width * src.height > limits.max_pixels:
        raise RasterValidationError(
            f"Raster is too large ({src.width}x{src.height} pixels, "
            f"max {limits.max_pixels:,} pixels)"
        )
    if not 1 <= src.count <= limits.max_bands:
        raise RasterValidationError(f"Raster must have 1 to {limits.max_bands} bands")
    unsupported = set(src.dtypes) - SUPPORTED_DTYPES
    if unsupported:
        raise RasterValidationError(f"Unsupported data type: {', '.join(sorted(unsupported))}")
    uncompressed = src.width * src.height * sum(np.dtype(d).itemsize for d in src.dtypes)
    if uncompressed > limits.max_uncompressed_bytes:
        raise RasterValidationError("Raster is too large when decompressed")


def footprint_wgs84(crs: CRS, bounds: tuple[float, float, float, float]) -> Polygon:
    """Image footprint in EPSG:4326, densified so curved edges after reprojection are kept."""
    left, bottom, right, top = bounds
    native = box(left, bottom, right, top).segmentize(max(right - left, top - bottom) / 32)
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    footprint = shapely.transform(
        native, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
    )
    min_lon, min_lat, max_lon, max_lat = footprint.bounds
    if not all(math.isfinite(v) for v in footprint.bounds) or not footprint.is_valid:
        raise RasterValidationError("Could not compute a geographic footprint for the raster")
    if min_lon < -180 or max_lon > 180 or min_lat < -90 or max_lat > 90:
        raise RasterValidationError("Raster footprint is outside valid lon/lat ranges")
    if max_lon - min_lon > 180:
        raise RasterValidationError("Rasters crossing the antimeridian are not supported")
    return footprint


def parse_datetime(value: str) -> tuple[datetime, bool] | None:
    """Parse ISO 8601 or TIFF-style ("YYYY:MM:DD HH:MM:SS"). Returns (value, assumed_utc)."""
    text = value.strip()
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC), True
    return parsed, False


def find_acquisition_date(tags: dict[str, str]) -> tuple[datetime | None, str | None, bool]:
    upper = {key.upper(): value for key, value in tags.items()}
    for tag in ACQUISITION_TAGS:
        if tag in upper and (parsed := parse_datetime(upper[tag])):
            return parsed[0], tag, parsed[1]
    return None, None, False


def create_cog(src_path: Path, dst_path: Path) -> None:
    """Convert to a Cloud Optimized GeoTIFF (tiled, internal overviews), keeping the source CRS."""
    with rasterio.Env(**SAFE_GDAL_ENV, GDAL_NUM_THREADS="ALL_CPUS"):
        rio_copy(
            str(src_path),
            str(dst_path),
            driver="COG",
            COMPRESS="DEFLATE",
            PREDICTOR="YES",
            BLOCKSIZE=512,
            OVERVIEW_RESAMPLING="AVERAGE",
            BIGTIFF="IF_SAFER",
        )


DisplayRanges = list[tuple[float, float]]
RGB_INTERP = (ColorInterp.red.name, ColorInterp.green.name, ColorInterp.blue.name)


def display_bands_for(color_interpretation: Sequence[str], count: int) -> list[int]:
    """Bands (1-based) used for visual display.

    Uses the bands tagged red/green/blue if present (e.g. NAIP RGB+NIR); otherwise the
    first three bands; single-band rasters are shown as grayscale. Other bands (NIR, etc.)
    are kept in the stored raster but not displayed.
    """
    interp = list(color_interpretation)
    try:
        return [interp.index(name) + 1 for name in RGB_INTERP]
    except ValueError:
        return [1, 2, 3] if count >= 3 else [1]


def display_bands(src: DatasetReader) -> list[int]:
    return display_bands_for([c.name for c in src.colorinterp], src.count)


def compute_display_ranges(data: np.ma.MaskedArray[Any, Any]) -> DisplayRanges | None:
    """Per-band 2-98 % percentile range for contrast stretching; None for 8-bit data.

    Computed once per image (from an overview) so every map tile uses the same scaling.
    """
    if data.dtype == np.uint8:
        return None
    ranges: DisplayRanges = []
    for band in data:
        valid = band.compressed().astype(np.float64)
        if valid.size == 0:
            ranges.append((0.0, 1.0))
            continue
        low, high = (float(v) for v in np.percentile(valid, [2, 98]))
        ranges.append((low, high if high > low else low + 1))
    return ranges


def to_uint8(
    data: np.ma.MaskedArray[Any, Any], ranges: DisplayRanges | None = None
) -> npt.NDArray[np.uint8]:
    """Scale bands to 0-255. 8-bit data is used as is; other types are linearly stretched."""
    if data.dtype == np.uint8:
        return np.ma.filled(data, 0).astype(np.uint8)
    ranges = ranges or compute_display_ranges(data) or []
    out = np.zeros(data.shape, dtype=np.uint8)
    for i, (band, (low, high)) in enumerate(zip(data, ranges, strict=True)):
        scaled = (np.ma.filled(band, low).astype(np.float64) - low) / (high - low) * 255
        out[i] = np.clip(scaled, 0, 255).astype(np.uint8)
    return out


@dataclass(frozen=True)
class Preview:
    png: bytes
    bands: list[int]
    display_ranges: DisplayRanges | None


def render_preview(path: Path, max_size: int = 512) -> Preview:
    """RGBA PNG thumbnail (NoData transparent), plus the band/stretch choice it used."""
    with rasterio.Env(**SAFE_GDAL_ENV), open_raster(path) as src:
        bands = display_bands(src)
        scale = max(src.width, src.height) / max_size
        width = max(1, round(src.width / max(scale, 1)))
        height = max(1, round(src.height / max(scale, 1)))
        data = src.read(
            bands, out_shape=(len(bands), height, width), masked=True, resampling=Resampling.average
        )
    ranges = compute_display_ranges(data)
    rgb = to_uint8(data, ranges)
    if len(bands) == 1:
        rgb = np.repeat(rgb, 3, axis=0)
    alpha = np.where(np.ma.getmaskarray(data).any(axis=0), 0, 255).astype(np.uint8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)  # a PNG preview has no CRS
        with MemoryFile() as memfile:
            with memfile.open(
                driver="PNG", width=width, height=height, count=4, dtype="uint8"
            ) as dst:
                dst.write(np.concatenate([rgb, alpha[np.newaxis]]))
            return Preview(bytes(memfile.read()), bands, ranges)


def _json_number(value: float | None) -> float | str | None:
    if value is None:
        return None
    return value if math.isfinite(value) else str(value)


def _sanitize_tags(tags: dict[str, str]) -> dict[str, str]:
    items = list(tags.items())[:MAX_TAGS]
    return {str(k)[:MAX_TAG_LENGTH]: str(v)[:MAX_TAG_LENGTH] for k, v in items}
