"""Tiled object detection over a (possibly large) georeferenced raster.

1. read the raster in overlapping windows (bounded memory; never the whole image)
2. prepare each window for the model (bands, 8-bit scaling, NoData)
3. run the detector in batches
4. shift tile-local boxes to full-image pixel coordinates
5. merge duplicates from overlapping tiles (NMS)
6. convert pixel polygons to geographic polygons (EPSG:4326)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.io import DatasetReader
from shapely.geometry import Polygon

from app.geospatial import create_raster_tiles
from app.ml.detector import ObjectDetector
from app.ml.postprocess import (
    ImageDetection,
    clip_to_image,
    merge_detections,
    pixel_polygon_to_geo,
    to_image_coordinates,
)
from app.ml.preprocess import prepare_tile
from app.raster import SAFE_GDAL_ENV, DisplayRanges, open_raster

ProgressCallback = Callable[[int, int], None]  # (tiles done, tiles total)


@dataclass(frozen=True)
class DetectionParams:
    tile_size: int = 1024
    overlap: int = 128
    batch_size: int = 4
    iou_threshold: float = 0.5
    containment_threshold: float = 0.8
    min_valid_fraction: float = 0.05
    edge_margin: float = 2.0


@dataclass(frozen=True)
class GeoDetection:
    class_id: int
    class_name: str
    confidence: float
    pixel_points: npt.NDArray[np.float64]  # (4, 2) full-image (col, row), as predicted
    geometry: Polygon  # EPSG:4326, clipped to the image extent
    clipped_to_image: bool = False


@dataclass
class DetectionResult:
    detections: list[GeoDetection]
    tiles_total: int
    tiles_skipped: int  # mostly NoData
    raw_detections: int  # before merging
    inference_seconds: float
    total_seconds: float
    per_class: dict[str, int] = field(default_factory=dict)


@dataclass
class TileStats:
    tiles_total: int
    tiles_skipped: int
    raw_detections: int
    inference_seconds: float


def detect_in_dataset(
    src: DatasetReader,
    detector: ObjectDetector,
    params: DetectionParams,
    bands: list[int],
    ranges: DisplayRanges | None,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[ImageDetection], TileStats]:
    """Steps 1-5 on an open raster: merged detections in full-image pixel coordinates."""
    inference = 0.0
    found: list[ImageDetection] = []
    skipped = 0
    windows = create_raster_tiles(src.width, src.height, params.tile_size, params.overlap)
    total = len(windows)
    for start in range(0, total, params.batch_size):
        batch = [
            prepare_tile(src, w, bands, ranges) for w in windows[start : start + params.batch_size]
        ]
        usable = [t for t in batch if t.valid_fraction >= params.min_valid_fraction]
        skipped += len(batch) - len(usable)

        t0 = time.perf_counter()
        per_tile = detector.detect([t.image for t in usable])
        inference += time.perf_counter() - t0

        for tile, detections in zip(usable, per_tile, strict=True):
            found.extend(
                to_image_coordinates(d, tile.window, src.width, src.height, params.edge_margin)
                for d in detections
            )
        if on_progress:
            on_progress(min(start + params.batch_size, total), total)

    merged = merge_detections(found, params.iou_threshold, params.containment_threshold)
    return merged, TileStats(total, skipped, len(found), inference)


def run_detection(
    raster_path: Path,
    detector: ObjectDetector,
    params: DetectionParams,
    bands: list[int],
    ranges: DisplayRanges | None,
    on_progress: ProgressCallback | None = None,
) -> DetectionResult:
    """Full pipeline on a georeferenced raster file, including step 6 (geo conversion)."""
    started = time.perf_counter()
    with rasterio.Env(**SAFE_GDAL_ENV), open_raster(raster_path) as src:
        merged, stats = detect_in_dataset(src, detector, params, bands, ranges, on_progress)
        geo = []
        for d in merged:
            inside, clipped = clip_to_image(d.points, src.width, src.height)
            geometry = pixel_polygon_to_geo(inside, src.transform, src.crs)
            geo.append(
                GeoDetection(d.class_id, d.class_name, d.confidence, d.points, geometry, clipped)
            )

    per_class: dict[str, int] = {}
    for detection in geo:
        per_class[detection.class_name] = per_class.get(detection.class_name, 0) + 1
    return DetectionResult(
        detections=geo,
        tiles_total=stats.tiles_total,
        tiles_skipped=stats.tiles_skipped,
        raw_detections=stats.raw_detections,
        inference_seconds=stats.inference_seconds,
        total_seconds=time.perf_counter() - started,
        per_class=dict(sorted(per_class.items(), key=lambda kv: -kv[1])),
    )
