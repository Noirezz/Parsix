"""Unit tests for CorrelationEngine and DefaultCorrelationEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from made_core.application.correlation import DefaultCorrelationEngine
from made_core.domain.enums import ResultStatus
from made_core.domain.interfaces import CorrelationEngine
from made_core.domain.models import CorrelatedGroup, DetectionResult

TS1 = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
TS2 = TS1 + timedelta(seconds=10)
TS3 = TS1 + timedelta(seconds=20)


def _make_result(
    *,
    result_id: str = "res-1",
    event_id: str = "evt-1",
    module_id: str = "futures-futures-spread",
    timestamp: datetime = TS1,
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


def test_correlation_engine_protocol_conformance():
    engine = DefaultCorrelationEngine()
    assert CorrelationEngine in DefaultCorrelationEngine.__mro__ or hasattr(engine, "correlate")


def test_single_event_correlation():
    engine = DefaultCorrelationEngine()
    r1 = _make_result(result_id="res-1", timestamp=TS1)
    r2 = _make_result(result_id="res-2", module_id="spot-futures-spread", timestamp=TS1)

    group = engine.correlate((r1, r2))

    assert isinstance(group, CorrelatedGroup)
    assert group.asset == "BTC"
    assert group.window_start == TS1
    assert group.window_end == TS1
    assert group.results == (r1, r2)


def test_multi_event_timestamps_window_boundaries():
    engine = DefaultCorrelationEngine()
    r1 = _make_result(result_id="res-1", timestamp=TS1)
    r2 = _make_result(result_id="res-2", timestamp=TS3)
    r3 = _make_result(result_id="res-3", timestamp=TS2)

    group = engine.correlate((r1, r2, r3))

    assert group.window_start == TS1
    assert group.window_end == TS3
    assert group.results == (r1, r2, r3)


def test_explicit_time_window():
    engine = DefaultCorrelationEngine()
    r1 = _make_result(timestamp=TS2)
    custom_start = TS1 - timedelta(minutes=1)
    custom_end = TS3 + timedelta(minutes=1)

    group = engine.correlate((r1,), window_start=custom_start, window_end=custom_end)

    assert group.window_start == custom_start
    assert group.window_end == custom_end


def test_rejects_empty_input():
    engine = DefaultCorrelationEngine()
    with pytest.raises(ValueError, match="results must contain at least one DetectionResult"):
        engine.correlate(())


def test_rejects_none_input():
    engine = DefaultCorrelationEngine()
    with pytest.raises(TypeError, match="results must not be None"):
        engine.correlate(None)  # type: ignore[arg-type]


def test_rejects_invalid_element_type():
    engine = DefaultCorrelationEngine()
    with pytest.raises(TypeError, match="all elements in results must be DetectionResult instances"):
        engine.correlate(["invalid_type"])  # type: ignore[list-item]


def test_rejects_mismatched_assets():
    engine = DefaultCorrelationEngine()
    r1 = _make_result(asset="BTC")
    r2 = _make_result(asset="ETH")
    with pytest.raises(ValueError, match="all detection results must belong to the same asset"):
        engine.correlate((r1, r2))


def test_rejects_window_end_before_window_start():
    engine = DefaultCorrelationEngine()
    r1 = _make_result(timestamp=TS2)
    with pytest.raises(ValueError, match="window_end must not precede window_start"):
        engine.correlate((r1,), window_start=TS3, window_end=TS1)


def test_deterministic_correlation_id_and_order():
    engine = DefaultCorrelationEngine()
    r1 = _make_result(result_id="res-1", module_id="mod-1")
    r2 = _make_result(result_id="res-2", module_id="mod-2")

    group1 = engine.correlate((r1, r2))
    group2 = engine.correlate((r1, r2))

    assert group1.correlation_id == group2.correlation_id
    assert group1.results == (r1, r2)
