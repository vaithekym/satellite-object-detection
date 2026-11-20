"""Evaluate the detector on labelled validation data and measure speed.

Run from backend/:  python -m scripts.evaluate_model   (or `make evaluate`)

1. Ultralytics' own validation of the model on DOTA8 (val split).
2. Our full pipeline (tiling + merging) on the same labelled images, scored with
   app.ml.metrics — also a cross-check of our metric implementation.
3. Speed on the NAIP sample (inference time per tile, throughput, peak memory).

Caveats, printed with the results:
- DOTA8 is 8 images (4 for validation) published by Ultralytics as a smoke-test dataset.
  Its images come from DOTA v1, which the pretrained model was trained on, so scores are
  NOT an unbiased accuracy estimate. Real evaluation needs a held-out labelled set from the
  target imagery (e.g. hand-labelled NAIP tiles).
- DOTA is licensed for academic use only; data is downloaded to data/datasets (git-ignored).
"""

import json
import resource
import sys
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from app.config import REPO_ROOT, get_settings
from app.ml.detector import UltralyticsDetector
from app.ml.jobs import detection_params
from app.ml.metrics import Box, EvaluationReport, evaluate
from app.ml.pipeline import detect_in_dataset
from app.raster import open_raster

DATASETS_DIR = REPO_ROOT / "data" / "datasets"
REPORTS_DIR = REPO_ROOT / "data" / "eval"
NAIP_SAMPLE = REPO_ROOT / "data" / "samples" / "naip_san_2024.tif"


def load_dota8() -> tuple[list[Path], Path, dict[int, str], Path]:
    import ultralytics.data.utils as data_utils

    # Ultralytics resolves its dataset directory at import time; point it at data/datasets
    # (git-ignored) for this process only, without changing the user's global settings.
    data_utils.DATASETS_DIR = DATASETS_DIR
    data = data_utils.check_det_dataset("dota8.yaml")  # downloads ~1 MB on first run
    val_dir = Path(data["val"])
    images = sorted(p for p in val_dir.iterdir() if p.suffix.lower() in {".jpg", ".png"})
    labels_dir = Path(str(val_dir).replace("/images/", "/labels/"))
    return images, labels_dir, dict(data["names"]), Path(data["yaml_file"])


def read_labels(path: Path, width: int, height: int, names: dict[int, str]) -> list[Box]:
    boxes = []
    for line in path.read_text().splitlines():
        values = line.split()
        if len(values) != 9:
            continue
        coords = np.array(values[1:], dtype=np.float64).reshape(4, 2) * [width, height]
        boxes.append(Box(coords, names[int(values[0])]))
    return boxes


def image_as_dataset(path: Path) -> MemoryFile:
    import cv2

    bgr = cv2.imread(str(path))
    if bgr is None:
        raise ValueError(f"Could not read image {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)
    memfile = MemoryFile()
    with memfile.open(
        driver="GTiff", width=rgb.shape[2], height=rgb.shape[1], count=3, dtype="uint8"
    ) as dst:
        dst.write(rgb)
    return memfile


def report_dict(report: EvaluationReport) -> dict[str, Any]:
    return {
        "images": report.images,
        "precision": report.precision,
        "recall": report.recall,
        "f1": report.f1,
        "map50": report.map50,
        "map50_95": report.map50_95,
        "per_class": {name: vars(m) for name, m in report.per_class.items()},
    }


def main() -> None:
    settings = get_settings()
    detector = UltralyticsDetector(
        settings.detection_model_path,
        settings.detection_device,
        settings.detection_confidence,
        settings.detection_iou_threshold,
        settings.detection_tile_size,
        settings.detection_model_sha256,
    )
    detector.load_model()
    params = detection_params(settings)
    images, labels_dir, names, yaml_file = load_dota8()
    results: dict[str, Any] = {
        "created": datetime.now(UTC).isoformat(),
        "model": detector.name,
        "model_version": detector.version,
        "device": settings.detection_device,
        "dataset": "DOTA8 val (Ultralytics sample of DOTA v1; overlaps the model's training data)",
    }

    # 1. Ultralytics validation (model only, no tiling).
    val = detector._model.val(
        data=str(yaml_file),
        split="val",
        imgsz=settings.detection_tile_size,
        device=settings.detection_device,
        plots=False,
        verbose=False,
        project=str(REPORTS_DIR / "ultralytics"),  # keep Ultralytics output inside data/
        name="val",
        exist_ok=True,
    )
    p, r = float(val.box.mp), float(val.box.mr)
    results["ultralytics_val"] = {
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else 0.0,
        "map50": float(val.box.map50),
        "map50_95": float(val.box.map),
    }

    # 2. Our pipeline + metrics on the same images.
    pairs: list[tuple[list[Box], list[Box]]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        for image in images:
            with image_as_dataset(image) as memfile, memfile.open() as src:
                merged, _ = detect_in_dataset(src, detector, params, [1, 2, 3], None)
                gts = read_labels(labels_dir / f"{image.stem}.txt", src.width, src.height, names)
            preds = [Box(d.points, d.class_name, d.confidence) for d in merged]
            pairs.append((preds, gts))
    results["pipeline_eval"] = report_dict(evaluate(pairs))

    # 3. Speed on real NAIP imagery.
    if NAIP_SAMPLE.exists():
        with rasterio.Env(), open_raster(NAIP_SAMPLE) as src:
            detect_in_dataset(src, detector, params, [1, 2, 3], None)  # warm-up
            runs = []
            for _ in range(3):
                t0 = time.perf_counter()
                _, stats = detect_in_dataset(src, detector, params, [1, 2, 3], None)
                runs.append((time.perf_counter() - t0, stats))
        best_total, stats = min(runs, key=lambda r: r[0])
        megapixels = src.width * src.height / 1e6
        results["speed_naip"] = {
            "image": NAIP_SAMPLE.name,
            "size_px": [src.width, src.height],
            "tiles": stats.tiles_total,
            "tile_size": params.tile_size,
            "best_total_seconds": round(best_total, 3),
            "inference_ms_per_tile": round(1000 * stats.inference_seconds / stats.tiles_total, 1),
            "megapixels_per_second": round(megapixels / best_total, 2),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1),
        }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"eval-{detector.name}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(results, indent=2))
    json.dump(results, sys.stdout, indent=2)
    print(f"\n\nSaved to {out}")
    print(__doc__.split("Caveats, printed with the results:")[1])


if __name__ == "__main__":
    main()
