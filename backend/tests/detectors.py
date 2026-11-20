"""Deterministic test detector: finds pure red squares (no ML, exact expected output)."""

from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from app.ml.detector import ObjectDetector, PixelDetection

RED = (255, 0, 0)


class RedSquareDetector(ObjectDetector):
    name = "red-square-test-detector"
    version = "test"

    def __init__(self) -> None:
        self.calls = 0

    def load_model(self) -> None:
        pass

    def predict(self, images: list[npt.NDArray[np.uint8]]) -> list[Any]:
        self.calls += 1
        return images

    def postprocess(self, predictions: list[Any]) -> list[list[PixelDetection]]:
        out = []
        for image in predictions:
            mask = ((image[:, :, 0] > 200) & (image[:, :, 1] < 50) & (image[:, :, 2] < 50)).astype(
                np.uint8
            )
            count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
            detections = []
            for x, y, w, h, _area in stats[1:count]:
                corners = np.array(
                    [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float64
                )
                detections.append(PixelDetection(corners, 0, "red square", 0.9))
            out.append(detections)
        return out


class FailingDetector(RedSquareDetector):
    def predict(self, images: list[npt.NDArray[np.uint8]]) -> list[Any]:
        raise RuntimeError("model crashed")


def image_with_squares(
    width: int, height: int, squares: list[tuple[int, int, int]]
) -> npt.NDArray[np.uint8]:
    """RGB (3, H, W) gray image with red squares at (col, row, size)."""
    data = np.full((3, height, width), 120, dtype=np.uint8)
    for col, row, size in squares:
        data[:, row : row + size, col : col + size] = np.array(RED, dtype=np.uint8)[:, None, None]
    return data
