from __future__ import annotations

from decimal import Decimal

import pytest

from made_core.domain.enums import EventSource, MarketType, ReferencePriceMode, ResultStatus
from made_core.domain.models import EnrichedEvent, MarketContext, MarketSnapshot, NormalizedEvent
from made_core.modules.spot_futures_spread import SpotFuturesSpreadConfig, SpotFuturesSpreadModule


def snapshot(
    timestamp,
    source: EventSource,
    price: Decimal,
    *,
    symbol: str = "BTCUSDT",
    market_type: MarketType,
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp,
        source=source,
        market_type=market_type,
        asset="BTC",
        symbol=symbol,
        price=price,
        bid=price,
        ask=price,
        volume=Decimal("1"),
    )


def event_with_snapshots(
    timestamp,
    normalized_event: NormalizedEvent,
    snapshots: tuple[MarketSnapshot, ...],
) -> EnrichedEvent:
    context = MarketContext.model_construct(
        asset="BTC",
        symbol="BTCUSDT",
        snapshots=snapshots,
        metadata={},
    )
    return EnrichedEvent(
        event_id=normalized_event.event_id,
        timestamp=timestamp,
        asset="BTC",
        market_context=context,
        normalized_data=normalized_event,
    )


@pytest.fixture
def spot_normalized_event(timestamp) -> NormalizedEvent:
    return NormalizedEvent(
        event_id="event-1",
        timestamp=timestamp,
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("64000"),
        bid=Decimal("63999"),
        ask=Decimal("64001"),
        volume=Decimal("12"),
    )


@pytest.fixture
def module() -> SpotFuturesSpreadModule:
    return SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1")))


def test_module_has_stable_identifier(module):
    assert module.get_module_id() == "spot-futures-spread"


def test_normal_spread_is_below_threshold(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("100.5"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metric_value == Decimal("0.4987531172069825436408977556")


def test_anomalous_spread_is_above_threshold(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.status is ResultStatus.ANOMALY
    assert result.metric_value == Decimal("2.955665024630541871921182266")


def test_threshold_boundary_is_anomaly(timestamp, spot_normalized_event):
    module = SpotFuturesSpreadModule(
        SpotFuturesSpreadConfig(Decimal("1"), ReferencePriceMode.FIRST)
    )
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("101"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.status is ResultStatus.ANOMALY
    assert result.metric_value == Decimal("1")


def test_zero_spread_is_normal(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("100"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.metric_value == Decimal("0")
    assert result.status is ResultStatus.NORMAL


def test_very_small_spread_is_normal(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("100.000001"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metric_value > Decimal("0")


def test_missing_spot_observation_is_normal_insufficient_context(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (snapshot(timestamp, EventSource.BYBIT, Decimal("100"), market_type=MarketType.FUTURES),),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_spot_futures_context"


def test_missing_futures_observation_is_normal_insufficient_context(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_spot_futures_context"


def test_only_spot_observation_is_normal_insufficient_context(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),),
        )
    )
    assert result.status is ResultStatus.NORMAL


def test_only_futures_observation_is_normal_insufficient_context(module, timestamp, normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            normalized_event,
            (snapshot(timestamp, EventSource.BYBIT, Decimal("100"), market_type=MarketType.FUTURES),),
        )
    )
    assert result.status is ResultStatus.NORMAL


def test_different_pair_is_normal_insufficient_context(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(
                    timestamp,
                    EventSource.BYBIT,
                    Decimal("101"),
                    symbol="ETHUSDT",
                    market_type=MarketType.FUTURES,
                ),
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_spot_futures_context"


def test_spot_plus_spot_is_non_applicable(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.SPOT),
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_spot_futures_context"


def test_futures_plus_futures_is_non_applicable(module, timestamp, normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.FUTURES),
                snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_spot_futures_context"


def test_missing_price_is_normal_insufficient_context(module, timestamp, spot_normalized_event):
    missing_price = MarketSnapshot.model_construct(
        timestamp=timestamp,
        source=EventSource.BYBIT,
        market_type=MarketType.FUTURES,
        asset="BTC",
        symbol="BTCUSDT",
        price=None,
        bid=Decimal("1"),
        ask=Decimal("1"),
        volume=Decimal("1"),
        funding_rate=None,
        metadata={},
    )
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                missing_price,
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "missing_price"


def test_unusable_reference_price_is_normal_insufficient_context(timestamp, spot_normalized_event):
    module = SpotFuturesSpreadModule(
        SpotFuturesSpreadConfig(Decimal("1"), ReferencePriceMode.FIRST)
    )
    invalid_price = MarketSnapshot.model_construct(
        timestamp=timestamp,
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("0"),
        bid=Decimal("0"),
        ask=Decimal("0"),
        volume=Decimal("1"),
        funding_rate=None,
        metadata={},
    )
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                invalid_price,
                snapshot(timestamp, EventSource.BYBIT, Decimal("101"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "invalid_reference_price"


def test_result_contains_required_detection_information(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("101"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.module_id == module.get_module_id()
    assert result.event_id == spot_normalized_event.event_id
    assert result.threshold == Decimal("1")
    assert result.metadata["referencePriceMode"] == "AVERAGE"
    assert result.metadata["spotSource"] == "BINANCE"
    assert result.metadata["futuresSource"] == "BYBIT"
    assert result.metadata["marketTypes"] == ["SPOT", "FUTURES"]
    assert "referencePrice" in result.metadata


def test_multiple_observations_selects_first_spot_and_first_futures(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.OKX, Decimal("200"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("101"), market_type=MarketType.FUTURES),
                snapshot(timestamp, EventSource.OKX, Decimal("300"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.metadata["spotSource"] == "BINANCE"
    assert result.metadata["futuresSource"] == "BYBIT"
    assert result.metadata["sources"] == ["BINANCE", "BYBIT"]
    assert result.metric_value == Decimal("0.9950248756218905472636815920")


def test_deterministic_selection_ignores_later_spot_futures_pairs(module, timestamp, spot_normalized_event):
    result = module.detect(
        event_with_snapshots(
            timestamp,
            spot_normalized_event,
            (
                snapshot(timestamp, EventSource.OKX, Decimal("100"), market_type=MarketType.FUTURES),
                snapshot(timestamp, EventSource.BINANCE, Decimal("110"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BYBIT, Decimal("120"), market_type=MarketType.SPOT),
                snapshot(timestamp, EventSource.BINANCE, Decimal("200"), market_type=MarketType.FUTURES),
            ),
        )
    )
    assert result.metadata["spotSource"] == "BINANCE"
    assert result.metadata["futuresSource"] == "OKX"
    assert result.metric_value == abs(Decimal("110") - Decimal("100")) / (
        (Decimal("110") + Decimal("100")) / Decimal("2")
    ) * Decimal("100")
