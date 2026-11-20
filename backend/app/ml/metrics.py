"""Detection metrics for oriented boxes: precision, recall, F1, AP / mAP.

Matching: per image and class, predictions are taken in descending confidence and matched
greedily to the unmatched ground-truth box with the highest IoU >= threshold (TP); the rest
are FP. AP uses the all-point interpolated precision envelope (as in PASCAL VOC 2010+ and
COCO). mAP@0.5:0.95 averages AP over IoU thresholds 0.50, 0.55, ..., 0.95.

Only meaningful on labelled validation data. Model confidence scores are not proof that a
prediction is correct; these metrics are how correctness is measured.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from shapely.geometry import Polygon

IOU_THRESHOLDS = tuple(round(0.5 + 0.05 * i, 2) for i in range(10))


@dataclass(frozen=True)
class Box:
    points: npt.NDArray[np.float64]  # (4, 2)
    class_name: str
    confidence: float = 1.0  # ground truth: unused

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.points)


@dataclass(frozen=True)
class ClassMetrics:
    ground_truth: int
    predictions: int
    true_positives: int  # at IoU 0.5
    precision: float
    recall: float
    f1: float
    ap50: float
    ap50_95: float


@dataclass(frozen=True)
class EvaluationReport:
    per_class: dict[str, ClassMetrics]
    precision: float  # micro-averaged over all classes, IoU 0.5
    recall: float
    f1: float
    map50: float  # mean over classes that have ground truth
    map50_95: float
    images: int
    extra: dict[str, float] = field(default_factory=dict)


def polygon_iou(a: Polygon, b: Polygon) -> float:
    if not a.intersects(b):
        return 0.0
    inter = a.intersection(b).area
    union = a.area + b.area - inter
    return float(inter / union) if union > 0 else 0.0


def match_image(
    predictions: list[Box], ground_truth: list[Box], iou_threshold: float
) -> list[tuple[float, bool]]:
    """(confidence, is_true_positive) for each prediction of one image and class."""
    gt_polygons = [g.polygon for g in ground_truth]
    matched = [False] * len(ground_truth)
    results: list[tuple[float, bool]] = []
    for pred in sorted(predictions, key=lambda p: -p.confidence):
        polygon = pred.polygon
        best, best_iou = -1, iou_threshold
        for j, gt in enumerate(gt_polygons):
            if matched[j]:
                continue
            iou = polygon_iou(polygon, gt)
            if iou >= best_iou:
                best, best_iou = j, iou
        if best >= 0:
            matched[best] = True
        results.append((pred.confidence, best >= 0))
    return results


def average_precision(matches: list[tuple[float, bool]], n_ground_truth: int) -> float:
    if n_ground_truth == 0:
        return float("nan")
    if not matches:
        return 0.0
    ordered = sorted(matches, key=lambda m: -m[0])
    tp = np.cumsum([m[1] for m in ordered])
    fp = np.cumsum([not m[1] for m in ordered])
    recall = tp / n_ground_truth
    precision = tp / (tp + fp)
    # Precision envelope (monotonically decreasing), then area under the step curve.
    mrec = np.concatenate([[0.0], recall, [1.0]])
    mpre = np.concatenate([[1.0], precision, [0.0]])
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
    steps = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[steps + 1] - mrec[steps]) * mpre[steps + 1]))


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0


def evaluate(images: list[tuple[list[Box], list[Box]]]) -> EvaluationReport:
    """images: (predictions, ground truth) per image, in the same coordinate space."""
    classes = sorted({b.class_name for preds, gts in images for b in [*preds, *gts]})
    per_class: dict[str, ClassMetrics] = {}
    total_tp = total_pred = total_gt = 0
    for name in classes:
        matches_at: dict[float, list[tuple[float, bool]]] = defaultdict(list)
        n_gt = n_pred = 0
        for preds, gts in images:
            p = [b for b in preds if b.class_name == name]
            g = [b for b in gts if b.class_name == name]
            n_gt += len(g)
            n_pred += len(p)
            for threshold in IOU_THRESHOLDS:
                matches_at[threshold].extend(match_image(p, g, threshold))
        tp50 = sum(is_tp for _, is_tp in matches_at[0.5])
        precision = tp50 / n_pred if n_pred else 0.0
        recall = tp50 / n_gt if n_gt else 0.0
        aps = [average_precision(matches_at[t], n_gt) for t in IOU_THRESHOLDS]
        per_class[name] = ClassMetrics(
            ground_truth=n_gt,
            predictions=n_pred,
            true_positives=tp50,
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
            ap50=aps[0],
            ap50_95=float(np.mean(aps)),
        )
        total_tp += tp50
        total_pred += n_pred
        total_gt += n_gt

    with_gt = [m for m in per_class.values() if m.ground_truth > 0]
    precision = total_tp / total_pred if total_pred else 0.0
    recall = total_tp / total_gt if total_gt else 0.0
    return EvaluationReport(
        per_class=per_class,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        map50=float(np.mean([m.ap50 for m in with_gt])) if with_gt else 0.0,
        map50_95=float(np.mean([m.ap50_95 for m in with_gt])) if with_gt else 0.0,
        images=len(images),
    )
