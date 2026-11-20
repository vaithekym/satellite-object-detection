"""Tile-local predictions → de-duplicated detections in image and geographic coordinates."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from affine import Affine
from rasterio.crs import CRS
from shapely import make_valid
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

from app.geospatial import TileWindow, pixel_to_geo
from app.ml.detector import PixelDetection


@dataclass(frozen=True)
class ImageDetection:
    """Detection in full-image pixel coordinates."""

    points: npt.NDArray[np.float64]  # (4, 2) (col, row)
    class_id: int
    class_name: str
    confidence: float
    # Box touches a tile edge that is inside the image, so it may be cut off.
    at_inner_edge: bool = False


def to_image_coordinates(
    detection: PixelDetection,
    window: TileWindow,
    raster_width: int,
    raster_height: int,
    edge_margin: float = 2.0,
) -> ImageDetection:
    points = detection.points + np.array([window.col_off, window.row_off], dtype=np.float64)
    min_col, min_row = points.min(axis=0)
    max_col, max_row = points.max(axis=0)
    right, bottom = window.col_off + window.width, window.row_off + window.height
    at_inner_edge = bool(
        (window.col_off > 0 and min_col <= window.col_off + edge_margin)
        or (window.row_off > 0 and min_row <= window.row_off + edge_margin)
        or (right < raster_width and max_col >= right - edge_margin)
        or (bottom < raster_height and max_row >= bottom - edge_margin)
    )
    return ImageDetection(
        points, detection.class_id, detection.class_name, detection.confidence, at_inner_edge
    )


def merge_detections(
    detections: list[ImageDetection],
    iou_threshold: float = 0.5,
    containment_threshold: float = 0.8,
) -> list[ImageDetection]:
    """Class-aware greedy NMS on oriented boxes, for duplicates from overlapping tiles.

    A box is suppressed by a kept box of the same class if their IoU exceeds iou_threshold,
    or if most of the smaller box lies inside the other (containment_threshold) — this
    removes partial boxes of objects cut by a tile edge. Boxes not touching an inner tile
    edge are preferred over boxes that do, then higher confidence wins. Objects larger than
    the tile overlap therefore keep their (possibly partial) detection instead of vanishing.
    """
    kept: list[ImageDetection] = []
    for class_id in sorted({d.class_id for d in detections}):
        group = [d for d in detections if d.class_id == class_id]
        group.sort(key=lambda d: (d.at_inner_edge, -d.confidence))
        polygons = [Polygon(d.points) for d in group]
        areas = np.array([p.area for p in polygons])
        bounds = np.array(
            [d.points.min(axis=0).tolist() + d.points.max(axis=0).tolist() for d in group]
        )
        suppressed = np.zeros(len(group), dtype=bool)
        for i, det in enumerate(group):
            if suppressed[i] or areas[i] <= 0:
                suppressed[i] = True
                continue
            kept.append(det)
            rest = np.arange(i + 1, len(group))
            overlapping = rest[
                ~suppressed[rest]
                & (bounds[rest, 0] < bounds[i, 2])
                & (bounds[rest, 2] > bounds[i, 0])
                & (bounds[rest, 1] < bounds[i, 3])
                & (bounds[rest, 3] > bounds[i, 1])
            ]
            for j in overlapping:
                inter = polygons[i].intersection(polygons[j]).area
                if inter <= 0:
                    continue
                iou = inter / (areas[i] + areas[j] - inter)
                containment = inter / min(areas[i], areas[j])
                if iou > iou_threshold or containment > containment_threshold:
                    suppressed[j] = True
    kept.sort(key=lambda d: -d.confidence)
    return kept


def pixel_polygon_to_geo(
    points: npt.NDArray[np.float64], transform: Affine, crs: CRS | str
) -> Polygon:
    """Image pixel corner points → polygon in EPSG:4326 (lon/lat), counter-clockwise."""
    lons, lats = pixel_to_geo(transform, crs, points[:, 0], points[:, 1])
    polygon = Polygon(zip(np.asarray(lons), np.asarray(lats), strict=True))
    if not polygon.is_valid:
        fixed = make_valid(polygon)
        polygon = fixed if isinstance(fixed, Polygon) else polygon.convex_hull
    return orient(polygon)


def clip_to_image(
    points: npt.NDArray[np.float64], width: int, height: int
) -> tuple[npt.NDArray[np.float64], bool]:
    """Clip a pixel polygon to the image extent [0, width] x [0, height].

    Models may extend boxes of objects cut by the image border beyond the imagery; stored
    geometries must not claim areas without image data. Returns (points, was_clipped).
    """
    if points.min() >= 0 and points[:, 0].max() <= width and points[:, 1].max() <= height:
        return points, False
    clipped = Polygon(points).intersection(box(0, 0, width, height))
    if not isinstance(clipped, Polygon) or clipped.is_empty:
        return points, False
    return np.asarray(clipped.exterior.coords[:-1], dtype=np.float64), True
