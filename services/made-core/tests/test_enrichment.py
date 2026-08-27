"""Unit tests for DefaultContextEnricher and context enrichment contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.application.enrichment import DefaultContextEnricher
from made_core.domain.enums import EventSource, MarketType
from made_core.domain.interfaces import ContextEnricher
from made_core.domain.models import EnrichedEvent, MarketContext, MarketSnapshot, NormalizedEvent

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_event(
    *,
    event_id: str = "evt-1",
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
    source: EventSource = EventSource.BINANCE,
    market_type: MarketType = MarketType.FUTURES,
    price: Decimal = Decimal("64000"),
    bid: Decimal = Decimal("63999"),
    ask: Decimal = Decimal("64001"),
    volume: Decimal = Decimal("10"),
    metadata: dict | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        timestamp=TS,
        source=source,
        market_type=market_type,
        asset=asset,
        symbol=symbol,
        price=price,
        bid=bid,
        ask=ask,
        volume=volume,
        metadata=metadata or {},
    )


def _make_snapshot(
    *,
    source: EventSource = EventSource.BYBIT,
    market_type: MarketType = MarketType.FUTURES,
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("64050"),
    bid: Decimal = Decimal("64049"),
    ask: Decimal = Decimal("64051"),
    volume: Decimal = Decimal("15"),
    funding_rate: Decimal | None = Decimal("0.0001"),
    metadata: dict | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=TS,
        source=source,
        market_type=market_type,
        asset=asset,
        symbol=symbol,
        price=price,
        bid=bid,
        ask=ask,
        volume=volume,
        funding_rate=funding_rate,
        metadata=metadata or {},
    )


def test_enricher_implements_context_enricher_protocol():
    assert ContextEnricher in DefaultContextEnricher.__mro__
    enricher = DefaultContextEnricher()
    assert callable(getattr(enricher, "enrich", None))


def test_valid_event_is_enriched():
    enricher = DefaultContextEnricher()
    event = _make_event()
    snapshot = _make_snapshot()

    enriched = enricher.enrich(event, (snapshot,))

    assert isinstance(enriched, EnrichedEvent)
    assert enriched.event_id == event.event_id
    assert enriched.timestamp == event.timestamp
    assert enriched.asset == event.asset
    assert enriched.normalized_data is event
    assert isinstance(enriched.market_context, MarketContext)
    assert enriched.market_context.asset == event.asset
    assert enriched.market_context.symbol == event.symbol
    assert enriched.market_context.snapshots == (snapshot,)


def test_market_context_contains_matching_snapshots():
    enricher = DefaultContextEnricher()
    event = _make_event()
    snap1 = _make_snapshot(source=EventSource.BYBIT, price=Decimal("64050"))
    snap2 = _make_snapshot(source=EventSource.OKX, price=Decimal("64100"))

    enriched = enricher.enrich(event, (snap1, snap2))

    assert enriched.market_context.snapshots == (snap1, snap2)


def test_mismatched_asset_snapshot_is_filtered():
    enricher = DefaultContextEnricher()
    event = _make_event(asset="BTC", symbol="BTCUSDT")
    matching_snap = _make_snapshot(asset="BTC", symbol="BTCUSDT")
    mismatched_snap = _make_snapshot(asset="ETH", symbol="BTCUSDT")

    enriched = enricher.enrich(event, (matching_snap, mismatched_snap))

    assert enriched.market_context.snapshots == (matching_snap,)


def test_mismatched_symbol_snapshot_is_filtered():
    enricher = DefaultContextEnricher()
    event = _make_event(asset="BTC", symbol="BTCUSDT")
    matching_snap = _make_snapshot(asset="BTC", symbol="BTCUSDT")
    mismatched_snap = _make_snapshot(asset="BTC", symbol="BTCUSD")

    enriched = enricher.enrich(event, (matching_snap, mismatched_snap))

    assert enriched.market_context.snapshots == (matching_snap,)


def test_different_market_types_are_allowed():
    enricher = DefaultContextEnricher()
    event = _make_event()
    spot_snap = _make_snapshot(source=EventSource.BINANCE, market_type=MarketType.SPOT)
    futures_snap = _make_snapshot(source=EventSource.BYBIT, market_type=MarketType.FUTURES)
    dex_snap = _make_snapshot(source=EventSource.UNISWAP, market_type=MarketType.DEX)

    enriched = enricher.enrich(event, (spot_snap, futures_snap, dex_snap))

    assert len(enriched.market_context.snapshots) == 3
    assert enriched.market_context.snapshots == (spot_snap, futures_snap, dex_snap)


def test_different_sources_are_allowed():
    enricher = DefaultContextEnricher()
    event = _make_event()
    binance_snap = _make_snapshot(source=EventSource.BINANCE)
    bybit_snap = _make_snapshot(source=EventSource.BYBIT)
    okx_snap = _make_snapshot(source=EventSource.OKX)

    enriched = enricher.enrich(event, (binance_snap, bybit_snap, okx_snap))

    assert len(enriched.market_context.snapshots) == 3
    assert enriched.market_context.snapshots == (binance_snap, bybit_snap, okx_snap)


def test_empty_snapshots_creates_fallback_snapshot():
    enricher = DefaultContextEnricher()
    event = _make_event(
        event_id="evt-42",
        asset="BTC",
        symbol="BTCUSDT",
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        price=Decimal("64000"),
        bid=Decimal("63999"),
        ask=Decimal("64001"),
        volume=Decimal("12"),
        metadata={"feed": "primary"},
    )

    enriched = enricher.enrich(event, ())

    assert len(enriched.market_context.snapshots) == 1
    fallback = enriched.market_context.snapshots[0]
    assert fallback.timestamp == event.timestamp
    assert fallback.source == EventSource.BINANCE
    assert fallback.market_type == MarketType.SPOT
    assert fallback.asset == "BTC"
    assert fallback.symbol == "BTCUSDT"
    assert fallback.price == Decimal("64000")
    assert fallback.bid == Decimal("63999")
    assert fallback.ask == Decimal("64001")
    assert fallback.volume == Decimal("12")
    assert fallback.funding_rate is None
    assert fallback.metadata == {"feed": "primary"}


def test_only_mismatched_snapshots_creates_fallback_snapshot():
    enricher = DefaultContextEnricher()
    event = _make_event(asset="BTC", symbol="BTCUSDT")
    mismatched1 = _make_snapshot(asset="ETH", symbol="ETHUSDT")
    mismatched2 = _make_snapshot(asset="BTC", symbol="BTCUSD")

    enriched = enricher.enrich(event, (mismatched1, mismatched2))

    assert len(enriched.market_context.snapshots) == 1
    fallback = enriched.market_context.snapshots[0]
    assert fallback.asset == event.asset
    assert fallback.symbol == event.symbol
    assert fallback.price == event.price


def test_none_event_is_rejected():
    enricher = DefaultContextEnricher()
    with pytest.raises(TypeError, match="event must not be None"):
        enricher.enrich(None)  # type: ignore[arg-type]


def test_invalid_event_type_is_rejected():
    enricher = DefaultContextEnricher()
    with pytest.raises(TypeError, match="event must be an instance of NormalizedEvent"):
        enricher.enrich({"asset": "BTC"})  # type: ignore[arg-type]


def test_event_is_not_mutated():
    enricher = DefaultContextEnricher()
    event = _make_event(metadata={"key": "val"})
    enricher.enrich(event, ())

    assert event.event_id == "evt-1"
    assert event.metadata == {"key": "val"}


def test_snapshots_are_not_mutated():
    enricher = DefaultContextEnricher()
    event = _make_event()
    snap = _make_snapshot(metadata={"flag": 1})
    snapshots_tuple = (snap,)

    enricher.enrich(event, snapshots_tuple)

    assert snap.metadata == {"flag": 1}
    assert snapshots_tuple == (snap,)


def test_enrichment_is_deterministic():
    enricher = DefaultContextEnricher()
    event = _make_event()
    snap1 = _make_snapshot(source=EventSource.BYBIT)
    snap2 = _make_snapshot(source=EventSource.OKX)

    enriched1 = enricher.enrich(event, (snap1, snap2))
    enriched2 = enricher.enrich(event, (snap1, snap2))

    assert enriched1 == enriched2


def test_enriched_event_preserves_event_metadata():
    enricher = DefaultContextEnricher()
    event = _make_event(metadata={"trace_id": "abc-123"})

    enriched = enricher.enrich(event, ())

    fallback = enriched.market_context.snapshots[0]
    assert fallback.metadata == {"trace_id": "abc-123"}
    # Modifying fallback metadata does not affect original event
    fallback.metadata["new_key"] = "test"
    assert "new_key" not in event.metadata
