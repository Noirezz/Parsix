from __future__ import annotations

from decimal import Decimal

import pytest

from made_core.domain.enums import EventSource, MarketType, ReferencePriceMode, ResultStatus
from made_core.domain.models import EnrichedEvent, MarketContext, MarketSnapshot
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig, FuturesFuturesSpreadModule


def snapshot(timestamp, source: EventSource, price: Decimal, symbol: str = "BTCUSDT", market_type: MarketType = MarketType.FUTURES) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp, source=source, market_type=market_type, asset="BTC", symbol=symbol,
        price=price, bid=price, ask=price, volume=Decimal("1"),
    )


def event_with_snapshots(timestamp, normalized_event, snapshots: tuple[MarketSnapshot, ...]) -> EnrichedEvent:
    context = MarketContext.model_construct(asset="BTC", symbol="BTCUSDT", snapshots=snapshots, metadata={})
    return EnrichedEvent(
        event_id=normalized_event.event_id, timestamp=timestamp, asset="BTC", market_context=context,
        normalized_data=normalized_event,
    )


@pytest.fixture
def module() -> FuturesFuturesSpreadModule:
    return FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1")))


def test_module_has_stable_identifier(module):
    assert module.get_module_id() == "futures-futures-spread"


def test_normal_spread_is_below_threshold(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("100.5")),
    )))
    assert result.status is ResultStatus.NORMAL
    assert result.metric_value == Decimal("0.4987531172069825436408977556")


def test_anomalous_spread_is_above_threshold(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("103")),
    )))
    assert result.status is ResultStatus.ANOMALY
    assert result.metric_value == Decimal("2.955665024630541871921182266")


def test_threshold_boundary_is_anomaly(timestamp, normalized_event):
    module = FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(Decimal("1"), ReferencePriceMode.FIRST))
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("101")),
    )))
    assert result.status is ResultStatus.ANOMALY
    assert result.metric_value == Decimal("1")


def test_one_futures_observation_is_normal_insufficient_context(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (snapshot(timestamp, EventSource.BINANCE, Decimal("100")),)))
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_futures_context"


def test_different_pair_is_normal_insufficient_context(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("101"), "ETHUSDT"),
    )))
    assert result.status is ResultStatus.NORMAL


def test_missing_price_is_normal_insufficient_context(module, timestamp, normalized_event):
    missing_price = MarketSnapshot.model_construct(
        timestamp=timestamp, source=EventSource.BYBIT, market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSDT",
        price=None, bid=Decimal("1"), ask=Decimal("1"), volume=Decimal("1"), funding_rate=None, metadata={},
    )
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), missing_price,
    )))
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "missing_price"


def test_unusable_reference_price_is_normal_insufficient_context(timestamp, normalized_event):
    module = FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(Decimal("1"), ReferencePriceMode.FIRST))
    invalid_price = MarketSnapshot.model_construct(
        timestamp=timestamp, source=EventSource.BINANCE, market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSDT",
        price=Decimal("0"), bid=Decimal("0"), ask=Decimal("0"), volume=Decimal("1"), funding_rate=None, metadata={},
    )
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        invalid_price, snapshot(timestamp, EventSource.BYBIT, Decimal("101")),
    )))
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "invalid_reference_price"


def test_zero_spread_is_normal(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("100")),
    )))
    assert result.metric_value == Decimal("0")
    assert result.status is ResultStatus.NORMAL


def test_very_small_spread_is_normal(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("100.000001")),
    )))
    assert result.status is ResultStatus.NORMAL
    assert result.metric_value > Decimal("0")


def test_multiple_observations_selects_first_distinct_source_pair(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BINANCE, Decimal("200")),
        snapshot(timestamp, EventSource.BYBIT, Decimal("101")),
    )))
    assert result.metadata["sources"] == ["BINANCE", "BYBIT"]
    assert result.metric_value == Decimal("0.9950248756218905472636815920")


def test_result_contains_required_detection_information(module, timestamp, normalized_event):
    result = module.detect(event_with_snapshots(timestamp, normalized_event, (
        snapshot(timestamp, EventSource.BINANCE, Decimal("100")), snapshot(timestamp, EventSource.BYBIT, Decimal("101")),
    )))
    assert result.module_id == module.get_module_id()
    assert result.event_id == normalized_event.event_id
    assert result.threshold == Decimal("1")
    assert result.metadata["referencePriceMode"] == "AVERAGE"
