"""Unit tests for PriorityEvaluator and DefaultPriorityEvaluator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.application.priority import DefaultPriorityEvaluator
from made_core.domain.enums import Priority, ResultStatus
fromメイド_interfaces = None
from made_core.domain.interfaces import PriorityEvaluator
from made_core.domain.models import (
    AggregatedResult,
    CorrelatedGroup,
    DetectionResult,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_aggregate(
    *,
    module_count: int = 1,
    max_anomaly_ratio: Decimal = Decimal("1.2"),
    triggered_modules: tuple[str, ...] = ("futures-futures-spread",),
) -> AggregatedResult:
    result = DetectionResult(
        result_id="res-1",
        event_id="evt-1",
        module_id=triggered_modules[0],
        timestamp=TS,
        asset="BTC",
        metric_value=max_anomaly_ratio,
        threshold=Decimal("1.0"),
        anomaly_ratio=max_anomaly_ratio,
        status=ResultStatus.ANOMALY,
        persistence=0,
    )
    group = CorrelatedGroup(
        correlation_id="corr-1",
        asset="BTC",
        window_start=TS,
        window_end=TS,
        results=(result,),
    )
    return AggregatedResult(
        aggregation_id="agg-1",
        timestamp=TS,
        asset="BTC",
        correlation_window=group,
        triggered_modules=triggered_modules,
        module_count=module_count,
        composite_anomaly_score=max_anomaly_ratio,
        max_anomaly_ratio=max_anomaly_ratio,
        average_anomaly_ratio=max_anomaly_ratio,
        priority=Priority.LOW,
        source_results=(result,),
    )


def test_priority_evaluator_protocol_conformance():
    evaluator = DefaultPriorityEvaluator()
    assert PriorityEvaluator in DefaultPriorityEvaluator.__mro__ or hasattr(evaluator, "evaluate")


def test_single_anomaly_ratio_1_0_is_low():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("1.0"))
    assert evaluator.evaluate(agg) is Priority.LOW


def test_single_anomaly_ratio_1_4_is_low():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("1.4"))
    assert evaluator.evaluate(agg) is Priority.LOW


def test_single_anomaly_ratio_1_5_is_medium():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("1.5"))
    assert evaluator.evaluate(agg) is Priority.MEDIUM


def test_single_anomaly_ratio_2_0_is_medium():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("2.0"))
    assert evaluator.evaluate(agg) is Priority.MEDIUM


def test_single_anomaly_ratio_2_99_is_medium():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("2.99"))
    assert evaluator.evaluate(agg) is Priority.MEDIUM


def test_single_anomaly_ratio_3_0_is_high():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("3.0"))
    assert evaluator.evaluate(agg) is Priority.HIGH


def test_single_anomaly_ratio_5_0_is_high():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("5.0"))
    assert evaluator.evaluate(agg) is Priority.HIGH


def test_multiple_modules_is_high_even_with_low_ratio():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(
        module_count=2,
        max_anomaly_ratio=Decimal("1.1"),
        triggered_modules=("futures-futures-spread", "spot-futures-spread"),
    )
    assert evaluator.evaluate(agg) is Priority.HIGH


def test_multiple_modules_with_high_ratio_is_high():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(
        module_count=3,
        max_anomaly_ratio=Decimal("4.0"),
        triggered_modules=("futures-futures-spread", "spot-futures-spread", "dex-futures-spread"),
    )
    assert evaluator.evaluate(agg) is Priority.HIGH


def test_priority_evaluator_is_deterministic():
    evaluator = DefaultPriorityEvaluator()
    agg = _make_aggregate(module_count=1, max_anomaly_ratio=Decimal("2.0"))
    assert evaluator.evaluate(agg) == evaluator.evaluate(agg)


def test_rejects_none_aggregate():
    evaluator = DefaultPriorityEvaluator()
    with pytest.raises(TypeError, match="aggregate must not be None"):
        evaluator.evaluate(None)  # type: ignore[arg-type]


def test_rejects_invalid_aggregate_type():
    evaluator = DefaultPriorityEvaluator()
    with pytest.raises(TypeError, match="aggregate must be an instance of AggregatedResult"):
        evaluator.evaluate({"priority": "HIGH"})  # type: ignore[arg-type]


def test_evaluate_metrics_helper():
    evaluator = DefaultPriorityEvaluator()
    assert evaluator.evaluate_metrics(1, Decimal("1.2")) is Priority.LOW
    assert evaluator.evaluate_metrics(1, Decimal("1.5")) is Priority.MEDIUM
    assert evaluator.evaluate_metrics(1, Decimal("3.5")) is Priority.HIGH
    assert evaluator.evaluate_metrics(2, Decimal("1.0")) is Priority.HIGH
