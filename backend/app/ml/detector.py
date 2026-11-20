"""Object detector interface and the Ultralytics YOLO adapter.

The pipeline only depends on `ObjectDetector`, so a remote-sensing model trained on another
dataset (xView, a DOTA fine-tune, ...) or another framework can be plugged in by adding an
adapter. Model loading is separate from inference and happens once per process.
"""

import hashlib
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class PixelDetection:
    """One detection in pixel coordinates of the image it was predicted on."""

    points: npt.NDArray[np.float64]  # (4, 2) corner points (col, row); oriented box
    class_id: int
    class_name: str
    confidence: float


class ObjectDetector(ABC):
    """Detects objects in RGB uint8 images of shape (H, W, 3)."""

    name: str
    version: str

    @abstractmethod
    def load_model(self) -> None: ...

    @abstractmethod
    def predict(self, images: list[npt.NDArray[np.uint8]]) -> list[Any]:
        """Raw model output, one entry per image."""

    @abstractmethod
    def postprocess(self, predictions: list[Any]) -> list[list[PixelDetection]]: ...

    def detect(self, images: list[npt.NDArray[np.uint8]]) -> list[list[PixelDetection]]:
        if not images:
            return []
        return self.postprocess(self.predict(images))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class UltralyticsDetector(ObjectDetector):
    """YOLO (Ultralytics) adapter. Supports oriented (OBB) and axis-aligned detect models."""

    def __init__(
        self,
        weights: Path,
        device: str = "cpu",
        confidence: float = 0.25,
        iou: float = 0.5,
        imgsz: int = 1024,
        expected_sha256: str | None = None,
    ) -> None:
        self.weights = weights
        self.device = device
        self.confidence = confidence
        self.iou = iou
        self.imgsz = imgsz
        self.expected_sha256 = expected_sha256
        self.name = weights.stem
        self.version = "unloaded"
        self._model: Any = None
        self._lock = threading.Lock()  # a YOLO model instance is not safe for concurrent use

    def load_model(self) -> None:
        if not self.weights.is_file():
            raise FileNotFoundError(
                f"Model weights not found: {self.weights} (run `make model` to download)"
            )
        sha256 = file_sha256(self.weights)
        if self.expected_sha256 and sha256 != self.expected_sha256:
            raise ValueError(f"Checksum mismatch for {self.weights.name}: {sha256}")

        from ultralytics import YOLO  # heavy import, only when a model is needed
        from ultralytics.utils import SETTINGS

        SETTINGS.update({"sync": False})  # no usage analytics sent to Ultralytics
        self._model = YOLO(str(self.weights))
        if self._model.task not in {"obb", "detect"}:
            raise ValueError(f"Unsupported model task: {self._model.task}")
        self.version = f"sha256:{sha256[:12]}"

    @property
    def class_names(self) -> dict[int, str]:
        if self._model is None:
            raise RuntimeError("Model is not loaded")
        return dict(self._model.names)

    def predict(self, images: list[npt.NDArray[np.uint8]]) -> list[Any]:
        if self._model is None:
            raise RuntimeError("Model is not loaded")
        # Ultralytics treats numpy input as BGR (OpenCV convention).
        bgr = [np.ascontiguousarray(image[:, :, ::-1]) for image in images]
        with self._lock:
            return list(
                self._model.predict(
                    bgr,
                    imgsz=self.imgsz,
                    conf=self.confidence,
                    iou=self.iou,
                    device=self.device,
                    verbose=False,
                )
            )

    def postprocess(self, predictions: list[Any]) -> list[list[PixelDetection]]:
        results: list[list[PixelDetection]] = []
        for prediction in predictions:
            names = prediction.names
            if prediction.obb is not None:
                corners = prediction.obb.xyxyxyxy.cpu().numpy().astype(np.float64)
                classes = prediction.obb.cls.cpu().numpy()
                scores = prediction.obb.conf.cpu().numpy()
            else:
                boxes = prediction.boxes.xyxy.cpu().numpy().astype(np.float64)
                corners = np.stack(
                    [
                        boxes[:, [0, 1]],
                        boxes[:, [2, 1]],
                        boxes[:, [2, 3]],
                        boxes[:, [0, 3]],
                    ],
                    axis=1,
                )
                classes = prediction.boxes.cls.cpu().numpy()
                scores = prediction.boxes.conf.cpu().numpy()
            results.append(
                [
                    PixelDetection(points, int(cls), str(names[int(cls)]), float(score))
                    for points, cls, score in zip(corners, classes, scores, strict=True)
                ]
            )
        return results


@lru_cache(maxsize=2)
def get_detector(
    weights: Path,
    device: str,
    confidence: float,
    iou: float,
    imgsz: int,
    expected_sha256: str | None,
) -> UltralyticsDetector:
    """Loaded detector, cached per process so the model is loaded once, not per job/tile."""
    detector = UltralyticsDetector(weights, device, confidence, iou, imgsz, expected_sha256)
    detector.load_model()
    return detector
