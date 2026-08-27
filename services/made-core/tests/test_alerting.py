"""Unit tests for AlertGenerator, DefaultAlertGenerator, and downstream integration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.application.alerting import DefaultAlertGenerator
fromメイド_interfaces = None
from made_core.application.aggregator import DefaultResultAggregator
from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.priority import DefaultPriorityEvaluator
from made_core.domain.enums import Priority, ResultStatus
from made_core.domain.interfaces import AlertGenerator
from made_core.domain.models import (
    AggregatedResult,
    Alert,
    CorrelatedGroup,
    DetectionResult,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_aggregate(
    *,
    asset: str = "BTC",
    priority: Priority = Priority.MEDIUM,
    module_count: int = 1,
    composite_anomaly_score: Decimal = Decimal("2.5"),
    max_anomaly_ratio: Decimal = Decimal("2.5"),
    triggered_modules: tuple[str, ...] = ("futures-futures-spread",),
) -> AggregatedResult:
    result = DetectionResult(
        result_id="res-1",
        event_id="evt-1",
        module_id=triggered_modules[0],
        timestamp=TS,
        asset=asset,
        metric_value=max_anomaly_ratio,
        threshold=Decimal("1.0"),
        anomaly_ratio=max_anomaly_ratio,
        status=ResultStatus.ANOMALY,
        persistence=0,
    )
    group = CorrelatedGroup(
        correlation_id="corr-1",
        asset=asset,
        window_start=TS,
        window_end=TS,
        results=(result,),
    )
    return AggregatedResult(
        aggregation_id="agg-1",
        timestamp=TS,
        asset=asset,
        correlation_window=group,
        triggered_modules=triggered_modules,
        module_count=module_count,
        composite_anomaly_score=composite_anomaly_score,
        max_anomaly_ratio=max_anomaly_ratio,
        average_anomaly_ratio=max_anomaly_ratio,
        priority=priority,
        source_results=(result,),
    )


def test_alert_generator_protocol_conformance():
    generator = DefaultAlertGenerator()
    assert AlertGenerator in DefaultAlertGenerator.__mro__ or hasattr(generator, "generate")


def test_medium_priority_aggregate_generates_alert():
    generator = DefaultAlertGenerator()
    agg = _make_aggregate(priority=Priority.MEDIUM, composite_anomaly_score=Decimal("2.0"))

    alert = generator.generate(agg)

    assert isinstance(alert, Alert)
    assert alert.priority is Priority.MEDIUM
    assert alert.asset == "BTC"
    assert alert.anomaly_score == Decimal("2.0")
    assert alert.triggered_modules == ("futures-futures-spread",)


def test_high_priority_aggregate_generates_alert():
    generator = DefaultAlertGenerator()
    agg = _make_aggregate(
        priority=Priority.HIGH,
        module_count=2,
        composite_anomaly_score=Decimal("4.4"),
        triggered_modules=("futures-futures-spread", "spot-futures-spread"),
    )

    alert = generator.generate(agg)

    assert isinstance(alert, Alert)
    assert alert.priority is Priority.HIGH
    assert alert.title == "[HIGH] BTC anomaly detected"
    assert alert.summary == "BTC anomaly detected by 2 module(s). Composite score: 4.4."


def test_low_priority_aggregate_returns_none():
    generator = DefaultAlertGenerator()
    agg = _make_aggregate(priority=Priority.LOW, composite_anomaly_score=Decimal("1.2"))

    assert generator.generate(agg) is None


def test_alert_formatting_templates():
    generator = DefaultAlertGenerator()
    agg = _make_aggregate(
        asset="ETH",
        priority=Priority.MEDIUM,
        module_count=1,
        composite_anomaly_score=Decimal("2.25"),
    )

    alert = generator.generate(agg)

    assert alert is not None
    assert alert.title == "[MEDIUM] ETH anomaly detected"
    assert alert.summary == "ETH anomaly detected by 1 module(s). Composite score: 2.25."


def test_alert_propagates_fields_and_structured_details():
    generator = DefaultAlertGenerator()
    agg = _make_aggregate(priority=Priority.HIGH)

    alert = generator.generate(agg)

    assert alert is not None
    assert alert.timestamp == TS
    assert alert.asset == "BTC"
    assert alert.priority is Priority.HIGH
    assert alert.anomaly_score == agg.composite_anomaly_score
    assert alert.triggered_modules == agg.triggered_modules
    assert alert.details["aggregationId"] == agg.aggregation_id
    assert alert.details["correlationId"] == agg.correlation_window.correlation_id
    assert alert.details["compositeAnomalyScore"] == str(agg.composite_anomaly_score)


def test_alert_deterministic_id():
    generator = DefaultAlertGenerator()
    agg = _make_aggregate(priority=Priority.HIGH)

    alert1 = generator.generate(agg)
    alert2 = generator.generate(agg)

    assert alert1 is not None and alert2 is not None
    assert alert1.alert_id == alert2.alert_id
    assert alert1.alert_id == f"alert:{agg.asset}:{agg.aggregation_id}"


def test_rejects_none_aggregate():
    generator = DefaultAlertGenerator()
    with pytest.raises(TypeError, match="aggregate must not be None"):
        generator.generate(None)  # type: ignore[arg-type]


def test_rejects_invalid_aggregate_type():
    generator = DefaultAlertGenerator()
    with pytest.raises(TypeError, match="aggregate must be an instance of AggregatedResult"):
        generator.generate({"priority": "HIGH"})  # type: ignore[arg-type]


def test_downstream_integration_anomalous_flow():
    # End-to-end downstream result processing
    r1 = DetectionResult(
        result_id="res-1",
        event_id="evt-100",
        module_id="futures-futures-spread",
        timestamp=TS,
        asset="BTC",
        metric_value=Decimal("2.0"),
        threshold=Decimal("1.0"),
        anomaly_ratio=Decimal("2.0"),
        status=ResultStatus.ANOMALY,
        persistence=0,
    )
    r2 = DetectionResult(
        result_id="res-2",
        event_id="evt-100",
        module_id="spot-futures-spread",
        timestamp=TS,
        asset="BTC",
        metric_value=Decimal("3.5"),
        threshold=Decimal("1.0"),
        anomaly_ratio=Decimal("3.5"),
        status=ResultStatus.ANOMALY,
        persistence=0,
    )

    results = (r1, r2)

    # 1. Correlation
    correlation_engine = DefaultCorrelationEngine()
    group = correlation_engine.correlate(results)
    assert group.asset == "BTC"

    # 2. Aggregation
    aggregator = DefaultResultAggregator()
    aggregate = aggregator.aggregate(results, correlation_window=group)
    assert aggregate is not None
    assert aggregate.module_count == 2
    assert aggregate.priority is Priority.HIGH

    # 3. Priority Evaluator
    evaluator = DefaultPriorityEvaluator()
    evaluated_priority = evaluator.evaluate(aggregate)
    assert evaluated_priority is Priority.HIGH

    # 4. Alert Generator
    alert_generator = DefaultAlertGenerator()
    alert = alert_generator.generate(aggregate)
    assert alert is not None
    assert alert.priority is Priority.HIGH
    assert alert.title == "[HIGH] BTC anomaly detected"
    assert "Composite score:" in alert.summary


def test_downstream_integration_normal_flow_stops():
    # Normal result -> Aggregation returns None -> no alert
    r_norm = DetectionResult(
        result_id="res-1",
        event_id="evt-200",
        module_id="futures-futures-spread",
        timestamp=TS,
        asset="BTC",
        metric_value=Decimal("0.5"),
        threshold=Decimal("1.0"),
        anomaly_ratio=Decimal("0.5"),
        status=ResultStatus.NORMAL,
        persistence=0,
    )

    aggregator = DefaultResultAggregator()
    aggregate = aggregator.aggregate((r_norm,))
    assert aggregate is None
