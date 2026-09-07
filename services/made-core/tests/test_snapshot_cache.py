"""Unit tests for SnapshotCache in worker infrastructure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent
from made_core.infrastructure.worker import SnapshotCache

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_event(
    *,
    event_id: str = "evt-1",
    source: EventSource = EventSource.BINANCE,
    market_type: MarketType = MarketType.SPOT,
    symbol: str = "BTCUSDT",
    asset: str = "BTC",
    price: Decimal = Decimal("65000"),
    bid: Decimal = Decimal("64999"),
    ask: Decimal = Decimal("65001"),
    volume: Decimal = Decimal("10"),
    timestamp: datetime = TS,
    metadata: dict | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        timestamp=timestamp,
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


def test_snapshot_cache_update_and_get():
    cache = SnapshotCache(freshness_ttl_seconds=300.0)
    event_spot = _make_event(source=EventSource.BINANCE, market_type=MarketType.SPOT, price=Decimal("65000"))
    event_fut = _make_event(source=EventSource.BINANCE, market_type=MarketType.FUTURES, price=Decimal("65500"))

    cache.update_from_event(event_spot)
    cache.update_from_event(event_fut)

    snaps = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)
    assert len(snaps) == 2
    sources = {s.source for s in snaps}
    market_types = {s.market_type for s in snaps}
    assert sources == {EventSource.BINANCE}
    assert market_types == {MarketType.SPOT, MarketType.FUTURES}


def test_snapshot_cache_overwrites_same_key():
    cache = SnapshotCache(freshness_ttl_seconds=300.0)
    event1 = _make_event(price=Decimal("65000"), timestamp=TS)
    event2 = _make_event(price=Decimal("66000"), timestamp=TS + timedelta(seconds=10))

    cache.update_from_event(event1)
    cache.update_from_event(event2)

    snaps = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS + timedelta(seconds=10))
    assert len(snaps) == 1
    assert snaps[0].price == Decimal("66000")


def test_snapshot_cache_filters_stale_by_ttl():
    cache = SnapshotCache(freshness_ttl_seconds=60.0)
    event_old = _make_event(
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        timestamp=TS - timedelta(seconds=120),
    )
    event_fresh = _make_event(
        source=EventSource.BINANCE,
        market_type=MarketType.FUTURES,
        timestamp=TS - timedelta(seconds=10),
    )

    cache.update_from_event(event_old)
    cache.update_from_event(event_fresh)

    snaps = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)
    assert len(snaps) == 1
    assert snaps[0].market_type == MarketType.FUTURES


def test_snapshot_cache_extracts_funding_rate():
    cache = SnapshotCache(freshness_ttl_seconds=300.0)
    event = _make_event(
        market_type=MarketType.FUTURES,
        metadata={"funding_rate": "0.00015"},
    )

    snap = cache.update_from_event(event)
    assert snap.funding_rate == Decimal("0.00015")


def test_snapshot_cache_filters_different_asset_or_symbol():
    cache = SnapshotCache(freshness_ttl_seconds=300.0)
    event_btc = _make_event(asset="BTC", symbol="BTCUSDT")
    event_eth = _make_event(asset="ETH", symbol="ETHUSDT")

    cache.update_from_event(event_btc)
    cache.update_from_event(event_eth)

    btc_snaps = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)
    assert len(btc_snaps) == 1
    assert btc_snaps[0].asset == "BTC"


def test_snapshot_cache_clear():
    cache = SnapshotCache(freshness_ttl_seconds=300.0)
    event = _make_event()
    cache.update_from_event(event)
    assert len(cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)) == 1

    cache.clear()
    assert len(cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)) == 0
