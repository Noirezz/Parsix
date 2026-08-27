"""Unit tests for ResultAggregator and DefaultResultAggregator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.application.aggregator import DefaultResultAggregator
from made_core.domain.enums import Priority, ResultStatus
from made_core.domain.interfaces import ResultAggregator
from made_core.domain.models import AggregatedResult, CorrelatedGroup, DetectionResult

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_result(
    *,
    result_id: str = "res-1",
    event_id: str = "evt-1",
    module_id: str = "futures-futures-spread",
    timestamp: datetime = TS,
    asset: str = "BTC",
    metric_value: Decimal = Decimal("2.0"),
    threshold: Decimal = Decimal("1.0"),
    anomaly_ratio: Decimal = Decimal("2.0"),
    status: ResultStatus = ResultStatus.ANOMALY,
) -> DetectionResult:
    return DetectionResult(
        result_id=result_id,
        event_id=event_id,
        module_id=module_id,
        timestamp=timestamp,
        asset=asset,
        metric_value=metric_value,
        threshold=threshold,
        anomaly_ratio=anomaly_ratio,
        status=status,
        persistence=0,
    )


def test_aggregator_protocol_conformance():
    aggregator = DefaultResultAggregator()
    assert ResultAggregator in DefaultResultAggregator.__mro__ or hasattr(aggregator, "aggregate")


def test_single_anomaly_aggregation():
    aggregator = DefaultResultAggregator()
    r = _make_result(anomaly_ratio=Decimal("2.0"))

    agg = aggregator.aggregate((r,))

    assert isinstance(agg, AggregatedResult)
    assert agg.asset == "BTC"
    assert agg.module_count == 1
    assert agg.triggered_modules == ("futures-futures-spread",)
    assert agg.max_anomaly_ratio == Decimal("2.0")
    assert agg.average_anomaly_ratio == Decimal("2.0")
    assert agg.composite_anomaly_score == Decimal("2.0")
    assert agg.priority is Priority.MEDIUM
    assert agg.source_results == (r,)


def test_multiple_anomalies_aggregation_and_formula():
    aggregator = DefaultResultAggregator()
    r1 = _make_result(
        result_id="res-1",
        module_id="futures-futures-spread",
        anomaly_ratio=Decimal("2.0"),
    )
    r2 = _make_result(
        result_id="res-2",
        module_id="spot-futures-spread",
        anomaly_ratio=Decimal("4.0"),
    )

    agg = aggregator.aggregate((r1, r2))

    assert agg is not None
    assert agg.module_count == 2
    assert agg.triggered_modules == ("futures-futures-spread", "spot-futures-spread")
    assert agg.max_anomaly_ratio == Decimal("4.0")
    assert agg.average_anomaly_ratio == Decimal("3.0")
    # composite_anomaly_score = 4.0 * (1 + 0.1 * (2 - 1)) = 4.0 * 1.1 = 4.4
    assert agg.composite_anomaly_score == Decimal("4.4")
    assert agg.priority is Priority.HIGH


def test_three_anomalies_composite_score():
    aggregator = DefaultResultAggregator()
    r1 = _make_result(result_id="res-1", module_id="mod-1", anomaly_ratio=Decimal("3.0"))
    r2 = _make_result(result_id="res-2", module_id="mod-2", anomaly_ratio=Decimal("2.0"))
    r3 = _make_result(result_id="res-3", module_id="mod-3", anomaly_ratio=Decimal("1.0"))

    agg = aggregator.aggregate((r1, r2, r3))

    assert agg is not None
    assert agg.module_count == 3
    assert agg.max_anomaly_ratio == Decimal("3.0")
    assert agg.average_anomaly_ratio == Decimal("2.0")
    # composite_anomaly_score = 3.0 * (1 + 0.1 * (3 - 1)) = 3.0 * 1.2 = 3.6
    assert agg.composite_anomaly_score == Decimal("3.6")
    assert agg.priority is Priority.HIGH


def test_mixed_normal_and_anomaly_results():
    aggregator = DefaultResultAggregator()
    r_normal = _make_result(
        result_id="res-norm",
        module_id="futures-futures-spread",
        status=ResultStatus.NORMAL,
        anomaly_ratio=Decimal("0.5"),
    )
    r_anomaly = _make_result(
        result_id="res-anom",
        module_id="spot-futures-spread",
        status=ResultStatus.ANOMALY,
        anomaly_ratio=Decimal("2.5"),
    )

    agg = aggregator.aggregate((r_normal, r_anomaly))

    assert agg is not None
    assert agg.module_count == 1
    assert agg.triggered_modules == ("spot-futures-spread",)
    assert agg.source_results == (r_anomaly,)
    assert agg.max_anomaly_ratio == Decimal("2.5")
    assert agg.average_anomaly_ratio == Decimal("2.5")


def test_all_normal_returns_none():
    aggregator = DefaultResultAggregator()
    r1 = _make_result(result_id="res-1", status=ResultStatus.NORMAL)
    r2 = _make_result(result_id="res-2", status=ResultStatus.NORMAL)

    assert aggregator.aggregate((r1, r2)) is None


def test_empty_input_returns_none():
    aggregator = DefaultResultAggregator()
    assert aggregator.aggregate(()) is None


def test_rejects_none_input():
    aggregator = DefaultResultAggregator()
    with pytest.raises(TypeError, match="results must not be None"):
        aggregator.aggregate(None)  # type: ignore[arg-type]


def test_rejects_invalid_element_type():
    aggregator = DefaultResultAggregator()
    with pytest.raises(TypeError, match="all elements in results must be DetectionResult instances"):
        aggregator.aggregate(["not_a_result"])  # type: ignore[list-item]


def test_rejects_mismatched_anomalous_assets():
    aggregator = DefaultResultAggregator()
    r1 = _make_result(asset="BTC", status=ResultStatus.ANOMALY)
    r2 = _make_result(asset="ETH", status=ResultStatus.ANOMALY)
    with pytest.raises(ValueError, match="all anomalous detection results must belong to the same asset"):
        aggregator.aggregate((r1, r2))


def test_explicit_correlation_window_provided():
    aggregator = DefaultResultAggregator()
    r = _make_result()
    custom_window = CorrelatedGroup(
        correlation_id="custom-group-1",
        asset="BTC",
        window_start=TS,
        window_end=TS,
        results=(r,),
    )

    agg = aggregator.aggregate((r,), correlation_window=custom_window)

    assert agg is not None
    assert agg.correlation_window is custom_window
    assert agg.correlation_window.correlation_id == "custom-group-1"


def test_deterministic_triggered_modules_and_source_order():
    aggregator = DefaultResultAggregator()
    r1 = _make_result(result_id="res-1", module_id="mod-a")
    r2 = _make_result(result_id="res-2", module_id="mod-b")

    agg1 = aggregator.aggregate((r1, r2))
    agg2 = aggregator.aggregate((r1, r2))

    assert agg1 == agg2
    assert agg1.triggered_modules == ("mod-a", "mod-b")
