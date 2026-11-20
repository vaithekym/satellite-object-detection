"""Computer vision pipeline: preprocessing, box transforms, merging, metrics, real model."""

from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from app.geospatial import TileWindow
from app.ml.detector import PixelDetection, UltralyticsDetector
from app.ml.metrics import Box, average_precision, evaluate
from app.ml.pipeline import DetectionParams, run_detection
from app.ml.postprocess import (
    ImageDetection,
    clip_to_image,
    merge_detections,
    pixel_polygon_to_geo,
    to_image_coordinates,
)
from app.ml.preprocess import prepare_tile
from app.raster import open_raster
from tests.detectors import RedSquareDetector, image_with_squares
from tests.rasters import SAMPLES_DIR, UTM_TRANSFORM, write_geotiff

MODEL = Path(__file__).resolve().parents[2] / "data" / "models" / "yolo26s-obb.pt"
NAIP = SAMPLES_DIR / "naip_san_2024.tif"
TO_WGS84 = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)


def square(col: float, row: float, size: float) -> np.ndarray:
    return np.array(
        [[col, row], [col + size, row], [col + size, row + size], [col, row + size]],
        dtype=np.float64,
    )


def det(points: np.ndarray, conf: float = 0.9, cls: int = 0, edge: bool = False) -> ImageDetection:
    return ImageDetection(points, cls, f"class{cls}", conf, edge)


# --- preprocessing -------------------------------------------------------------------


def test_prepare_tile_uses_rgb_bands_and_masks_nodata(tmp_path: Path) -> None:
    data = np.zeros((4, 64, 64), dtype="uint8")
    data[0], data[1], data[2], data[3] = 10, 20, 30, 250  # R, G, B, NIR
    data[:, :, :16] = 0  # NoData strip
    # 4th band is NIR, not alpha (GDAL would otherwise treat it as an alpha channel).
    path = write_geotiff(
        tmp_path / "rgbn.tif", count=4, data=data, nodata=0, photometric="RGB", alpha="UNSPECIFIED"
    )

    with open_raster(path) as src:
        tile = prepare_tile(src, TileWindow(0, 0, 64, 64), [1, 2, 3], None)
    assert tile.image.shape == (64, 64, 3)
    assert tile.image.dtype == np.uint8
    assert tuple(tile.image[10, 40]) == (10, 20, 30)  # RGB order, NIR ignored
    assert tile.image[:, :16].max() == 0  # NoData → black
    assert tile.valid_fraction == pytest.approx(48 / 64)


def test_prepare_tile_scales_16_bit_with_image_wide_range(tmp_path: Path) -> None:
    data = np.full((1, 32, 32), 3000, dtype="uint16")
    path = write_geotiff(
        tmp_path / "u16.tif", count=1, dtype="uint16", data=data, width=32, height=32
    )
    with open_raster(path) as src:
        tile = prepare_tile(src, TileWindow(0, 0, 32, 32), [1], [(2000.0, 4000.0)])
    assert tile.image.shape == (32, 32, 3)  # grayscale repeated to 3 channels
    assert int(tile.image[0, 0, 0]) == pytest.approx(127, abs=1)


# --- box transforms and merging --------------------------------------------------------


def test_tile_offsets_are_added_and_inner_edges_flagged() -> None:
    window = TileWindow(896, 0, 1024, 1024)
    inside = PixelDetection(square(100, 100, 50), 0, "plane", 0.9)
    at_left_edge = PixelDetection(square(0, 100, 50), 0, "plane", 0.9)

    moved = to_image_coordinates(inside, window, raster_width=2500, raster_height=1024)
    assert moved.points[0].tolist() == [996, 100]
    assert not moved.at_inner_edge
    # The tile's left edge (col 896) is inside the image → partial box.
    assert to_image_coordinates(at_left_edge, window, 2500, 1024).at_inner_edge
    # Top edge of this tile is the image edge → not an inner edge.
    at_top = PixelDetection(square(100, 0, 50), 0, "plane", 0.9)
    assert not to_image_coordinates(at_top, window, 2500, 1024).at_inner_edge


def test_merge_removes_duplicates_from_overlapping_tiles() -> None:
    a = det(square(1000, 500, 40), conf=0.9)
    a_again = det(square(1001, 501, 40), conf=0.8)  # same object seen in the next tile
    other = det(square(1200, 500, 40), conf=0.7)
    other_class = det(square(1000, 500, 40), conf=0.6, cls=1)  # same place, different class
    merged = merge_detections([a_again, other, a, other_class])
    assert len(merged) == 3
    assert merged[0] is a
    assert any(m is other for m in merged)
    assert any(m is other_class for m in merged)


def test_merge_prefers_complete_box_over_partial_box_at_tile_edge() -> None:
    complete = det(square(1000, 500, 60), conf=0.6)
    partial = det(square(1000, 500, 25), conf=0.95, edge=True)  # cut by a tile edge
    assert merge_detections([partial, complete]) == [complete]


def test_merge_keeps_partial_box_when_no_complete_box_exists() -> None:
    partial = det(square(1000, 500, 25), conf=0.9, edge=True)  # object larger than overlap
    assert merge_detections([partial]) == [partial]


def test_pixel_polygon_to_geo() -> None:
    polygon = pixel_polygon_to_geo(square(100, 200, 10), UTM_TRANSFORM, "EPSG:32632")
    expected_corner = TO_WGS84.transform(500_000 + 100 * 10, 6_650_000 - 200 * 10)
    assert polygon.is_valid
    assert polygon.exterior.is_ccw
    corners = np.array(polygon.exterior.coords)
    assert np.min(np.hypot(*(corners - expected_corner).T)) < 1e-9


def test_clip_to_image() -> None:
    inside = square(10, 10, 20)
    assert clip_to_image(inside, 100, 100) == (inside, False)
    points, clipped = clip_to_image(square(-10, 50, 30), 100, 100)
    assert clipped
    assert points[:, 0].min() == 0 and points[:, 0].max() == 20


# --- full pipeline with a deterministic detector ---------------------------------------------


def test_pipeline_detects_each_object_once_at_correct_location(tmp_path: Path) -> None:
    # 2500x1800 px, 1024 tiles with 128 overlap → tile edges at cols 896/1024/1792/1920.
    squares = [(300, 300, 40), (1000, 400, 40), (1900, 1000, 40), (2400, 1700, 40)]
    path = write_geotiff(
        tmp_path / "squares.tif",
        width=2500,
        height=1800,
        data=image_with_squares(2500, 1800, squares),
    )
    progress: list[tuple[int, int]] = []
    result = run_detection(
        path,
        RedSquareDetector(),
        DetectionParams(tile_size=1024, overlap=128, batch_size=2),
        [1, 2, 3],
        None,
        lambda done, total: progress.append((done, total)),
    )

    assert result.tiles_total == 6
    assert result.raw_detections > len(squares)  # objects in overlaps are seen twice
    assert len(result.detections) == len(squares)
    assert progress[-1] == (6, 6)
    assert [p[0] for p in progress] == sorted(p[0] for p in progress)

    for col, row, size in squares:
        centre = TO_WGS84.transform(
            500_000 + (col + size / 2) * 10, 6_650_000 - (row + size / 2) * 10
        )
        nearest = min(result.detections, key=lambda d: d.geometry.centroid.distance(_point(centre)))
        assert nearest.geometry.centroid.distance(_point(centre)) < 1e-7  # ~1 cm
        assert nearest.pixel_points.min(axis=0).tolist() == [col, row]


def _point(lonlat: tuple[float, float]):  # type: ignore[no-untyped-def]
    from shapely.geometry import Point

    return Point(lonlat)


# --- metrics ---------------------------------------------------------------------------


def test_metrics_perfect_predictions() -> None:
    gt = [Box(square(0, 0, 10), "plane"), Box(square(50, 50, 10), "ship")]
    preds = [Box(b.points, b.class_name, 0.9) for b in gt]
    report = evaluate([(preds, gt)])
    assert (report.precision, report.recall, report.f1) == (1.0, 1.0, 1.0)
    assert report.map50 == 1.0
    assert report.map50_95 == 1.0


def test_metrics_false_positive_missed_object_and_duplicate() -> None:
    gt = [Box(square(0, 0, 10), "plane"), Box(square(100, 0, 10), "plane")]
    preds = [
        Box(square(0, 0, 10), "plane", 0.9),  # TP
        Box(square(0.2, 0, 10), "plane", 0.8),  # duplicate → FP
        Box(square(500, 500, 10), "plane", 0.7),  # FP
    ]  # second ground truth missed
    report = evaluate([(preds, gt)])
    m = report.per_class["plane"]
    assert (m.true_positives, m.predictions, m.ground_truth) == (1, 3, 2)
    assert m.precision == pytest.approx(1 / 3)
    assert m.recall == pytest.approx(0.5)
    assert m.f1 == pytest.approx(0.4)
    assert m.ap50 == pytest.approx(0.5)


def test_average_precision_depends_on_ranking() -> None:
    # One ground truth; a false positive ranked above the true positive halves AP.
    assert average_precision([(0.9, True), (0.8, False)], 1) == pytest.approx(1.0)
    assert average_precision([(0.9, False), (0.8, True)], 1) == pytest.approx(0.5)


def test_map50_95_rewards_tighter_boxes() -> None:
    gt = [Box(square(0, 0, 10), "plane")]
    loose = [Box(square(1.5, 0, 10), "plane", 0.9)]  # IoU ≈ 0.74
    report = evaluate([(loose, gt)])
    assert report.map50 == 1.0
    assert report.map50_95 == pytest.approx(0.5)  # matches at 0.50..0.70, not 0.75..0.95


# --- real model --------------------------------------------------------------------------

needs_model = pytest.mark.skipif(
    not (MODEL.exists() and NAIP.exists()), reason="run make model && make samples"
)


@pytest.fixture(scope="module")
def yolo() -> UltralyticsDetector:
    detector = UltralyticsDetector(MODEL, imgsz=1024)
    detector.load_model()
    return detector


@needs_model
def test_model_loads_with_dota_classes(yolo: UltralyticsDetector) -> None:
    names = set(yolo.class_names.values())
    assert {"plane", "ship", "storage tank", "small vehicle", "large vehicle"} <= names
    assert yolo.version.startswith("sha256:")


@needs_model
def test_model_inference_result_structure(yolo: UltralyticsDetector) -> None:
    with open_raster(NAIP) as src:
        tile = prepare_tile(src, TileWindow(0, 1000, 1024, 1024), [1, 2, 3], None)
    [detections] = yolo.detect([tile.image])
    assert detections
    for d in detections:
        assert d.points.shape == (4, 2)
        assert 0 <= d.confidence <= 1
        assert d.class_name == yolo.class_names[d.class_id]
    # The gate area of San Diego airport has several parked aircraft.
    assert sum(d.class_name == "plane" for d in detections) >= 5


@needs_model
def test_real_pipeline_on_naip_places_planes_inside_image(yolo: UltralyticsDetector) -> None:
    result = run_detection(NAIP, yolo, DetectionParams(), [1, 2, 3], None)
    planes = [d for d in result.detections if d.class_name == "plane"]
    assert len(planes) >= 5
    with open_raster(NAIP) as src:
        from app.raster import footprint_wgs84

        footprint = footprint_wgs84(src.crs, src.bounds)
    # Boxes of planes cut by the image border are clipped to the imagery.
    assert all(footprint.buffer(1e-9).contains(p.geometry) for p in planes)
    assert any(p.clipped_to_image for p in planes)
    # Planes are tens of metres long: polygon area sanity check (in degrees² → rough m²).
    for plane in planes:
        area_m2 = plane.geometry.area * (111_320**2) * np.cos(np.radians(32.73))
        assert 100 < area_m2 < 10_000
