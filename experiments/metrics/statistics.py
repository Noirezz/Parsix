"""Statistical calculations and classification metrics for benchmark evaluation."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class StatisticalSummary:
    """Summary statistics for numeric series."""

    count: int
    mean: float
    median: float
    min: float
    max: float
    stddev: float
    p50: float
    p90: float
    p95: float
    p99: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "mean": round(self.mean, 4),
            "median": round(self.median, 4),
            "min": round(self.min, 4),
            "max": round(self.max, 4),
            "stddev": round(self.stddev, 4),
            "p50": round(self.p50, 4),
            "p90": round(self.p90, 4),
            "p95": round(self.p95, 4),
            "p99": round(self.p99, 4),
        }


def _percentile(sorted_data: list[float], p: float) -> float:
    """Calculate percentile p (0..100) on sorted data using standard linear interpolation (NumPy method 7)."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]
    
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def calculate_statistics(values: Sequence[float | int | Decimal]) -> StatisticalSummary:
    """Compute count, mean, median, min, max, stddev, and percentiles."""
    if not values:
        return StatisticalSummary(
            count=0,
            mean=0.0,
            median=0.0,
            min=0.0,
            max=0.0,
            stddev=0.0,
            p50=0.0,
            p90=0.0,
            p95=0.0,
            p99=0.0,
        )

    float_values = [float(v) for v in values]
    n = len(float_values)
    sorted_vals = sorted(float_values)

    mean_val = sum(float_values) / n
    min_val = sorted_vals[0]
    max_val = sorted_vals[-1]

    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in float_values) / (n - 1)
        stddev_val = math.sqrt(variance)
    else:
        stddev_val = 0.0

    p50_val = _percentile(sorted_vals, 50.0)
    p90_val = _percentile(sorted_vals, 90.0)
    p95_val = _percentile(sorted_vals, 95.0)
    p99_val = _percentile(sorted_vals, 99.0)
    median_val = p50_val

    return StatisticalSummary(
        count=n,
        mean=mean_val,
        median=median_val,
        min=min_val,
        max=max_val,
        stddev=stddev_val,
        p50=p50_val,
        p90=p90_val,
        p95=p95_val,
        p99=p99_val,
    )


@dataclass(frozen=True)
class ClassificationMetrics:
    """Standard classification evaluation metrics."""

    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1_score: float
    fpr: float
    fnr: float
    accuracy: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "fpr": round(self.fpr, 4),
            "fnr": round(self.fnr, 4),
            "accuracy": round(self.accuracy, 4),
        }


def calculate_classification_metrics(tp: int, fp: int, tn: int, fn: int) -> ClassificationMetrics:
    """Compute classification metrics handling zero division safely."""
    total = tp + fp + tn + fn
    if total == 0:
        return ClassificationMetrics(
            tp=0, fp=0, tn=0, fn=0,
            precision=0.0, recall=0.0, f1_score=0.0,
            fpr=0.0, fnr=0.0, accuracy=0.0,
        )

    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fp == 0 and tp == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else (1.0 if fn == 0 and tp == 0 else 0.0)
    
    if (precision + recall) > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    accuracy = (tp + tn) / total

    return ClassificationMetrics(
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        f1_score=f1,
        fpr=fpr,
        fnr=fnr,
        accuracy=accuracy,
    )


def pool_and_aggregate_latencies(trial_samples: list[list[float]]) -> StatisticalSummary:
    """Pool raw observations from all trials to avoid simple averaging of averages."""
    pooled: list[float] = []
    for samples in trial_samples:
        pooled.extend(samples)
    return calculate_statistics(pooled)
