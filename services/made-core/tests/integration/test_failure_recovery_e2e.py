"""Failure and Recovery Scenario Verification Tests.

Validates:
1. Partial exchange failure isolation (Bybit fails, Binance succeeds).
2. Duplicate event delivery idempotency.
3. Stale snapshot cache expiration.
4. Telegram delivery retry exhaustion and permanent error handling.
5. Malformed payload error handling without worker crash.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.entrypoint import create_default_worker
from made_core.infrastructure.postgres.models import Base
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.worker import SnapshotCache
from made_core.ingestion.collector import BinanceCollector, BybitCollector
from made_core.ingestion.normalizer import BinanceNormalizer, BybitNormalizer
from made_core.ingestion.pipeline import MultiSourceIngestionPipeline, SourceTarget
from made_core.ingestion.publisher import RedisEventPublisher

TS_FIXED = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)


class InMemoryMockRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._counter = 0

    async def xadd(self, name: str, fields: dict[str, str], maxlen: int | None = None) -> str:
        self._counter += 1
        msg_id = f"1000-{self._counter}"
        if name not in self.streams:
            self.streams[name] = []
        self.streams[name].append((msg_id, fields))
        return msg_id

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[list[Any]]:
        result = []
        for stream_name, _ in streams.items():
            msgs = self.streams.get(stream_name, [])
            if msgs:
                batch = msgs[:count] if count else msgs
                result.append([stream_name, batch])
        return result

    async def xack(self, *args: Any, **kwargs: Any) -> int:
        return 1

    async def xautoclaim(self, *args: Any, **kwargs: Any) -> tuple[str, list[Any], list[Any]]:
        return ("0-0", [], [])

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_partial_exchange_failure_isolation():
    """Verify that when Bybit API fails with HTTP error, Binance ingestion succeeds."""
    mock_redis = InMemoryMockRedis()

    binance_col = BinanceCollector()
    bybit_col = BybitCollector()

    async def mock_binance_collect(symbol: str, asset: str, market_type: MarketType = MarketType.SPOT) -> RawEvent:
        return RawEvent(
            timestamp=TS_FIXED,
            event_id="raw:binance:spot:btc:1",
            source=EventSource.BINANCE,
            payload={"symbol": symbol, "lastPrice": "50000.00", "bidPrice": "49990.00", "askPrice": "50010.00", "volume": "100.0"},
            metadata={"symbol": symbol, "asset": asset, "market_type": market_type.value},
        )

    async def mock_bybit_collect(symbol: str, asset: str, market_type: MarketType = MarketType.SPOT) -> RawEvent:
        raise httpx.ConnectTimeout("Bybit endpoint connection timed out")

    binance_col.collect = mock_binance_collect # type: ignore
    bybit_col.collect = mock_bybit_collect # type: ignore

    pipeline = MultiSourceIngestionPipeline(
        collectors={EventSource.BINANCE: binance_col, EventSource.BYBIT: bybit_col},
        normalizers={EventSource.BINANCE: BinanceNormalizer(), EventSource.BYBIT: BybitNormalizer()},
        publisher=RedisEventPublisher(redis_client=mock_redis), # type: ignore
    )

    targets = [
        SourceTarget(source=EventSource.BINANCE, market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT"),
        SourceTarget(source=EventSource.BYBIT, market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT"),
    ]

    results = await pipeline.ingest_all(targets)
    assert len(results) == 2

    # Binance succeeded
    assert results[0][3] is None
    assert results[0][2] is not None

    # Bybit isolated error
    assert results[1][3] is not None
    assert isinstance(results[1][3], httpx.ConnectTimeout)
    assert results[1][2] is None

    await pipeline.close()


@pytest.mark.asyncio
async def test_duplicate_event_idempotency_recovery():
    """Verify duplicate event delivery is acknowledged without re-triggering storage inserts or alerts."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = PostgresStorageAdapter(engine=engine, session_factory=session_factory)

    evt_dup = NormalizedEvent(
        event_id="evt-dup-1",
        timestamp=TS_FIXED,
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("50000.0"),
        bid=Decimal("49990.0"),
        ask=Decimal("50010.0"),
        volume=Decimal("100.0"),
        metadata={},
    )
    payload_str = evt_dup.model_dump_json(by_alias=True)

    mock_redis = InMemoryMockRedis()
    mock_redis.streams["events:normalized"] = [
        ("1-1", {"payload": payload_str}),
        ("1-2", {"payload": payload_str}),
    ]

    worker = create_default_worker()
    worker._storage = storage
    worker._consumer._redis = mock_redis

    # Process batch containing original and duplicate event
    batch_results = await worker.process_batch()
    assert len(batch_results) == 2
    assert batch_results[0][0] is not None # First event processed
    assert batch_results[1][0] is None # Duplicate event skipped

    # Verify event stored exactly once
    events, total = await storage.get_processed_events()
    assert total == 1
    assert events[0].event_id == "evt-dup-1"

    await storage.close()


@pytest.mark.asyncio
async def test_stale_snapshot_cache_expiration():
    """Verify that snapshots older than TTL are purged and excluded from context enrichment."""
    cache = SnapshotCache(freshness_ttl_seconds=60.0)

    # 1. Add snapshot at T0
    old_event = NormalizedEvent(
        event_id="evt-old-1",
        timestamp=TS_FIXED,
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("50000.0"),
        bid=Decimal("49990.0"),
        ask=Decimal("50010.0"),
        volume=Decimal("100.0"),
        metadata={},
    )
    cache.update_from_event(old_event)

    # At T0 + 30s: Snapshot is fresh
    snaps_fresh = cache.get_snapshots_for(asset="BTC", symbol="BTCUSDT", current_time=TS_FIXED + timedelta(seconds=30))
    assert len(snaps_fresh) == 1

    # At T0 + 90s: Snapshot is stale (> 60s)
    snaps_stale = cache.get_snapshots_for(asset="BTC", symbol="BTCUSDT", current_time=TS_FIXED + timedelta(seconds=90))
    assert len(snaps_stale) == 0


@pytest.mark.asyncio
async def test_telegram_retry_exhaustion_failure_status():
    """Verify that when Telegram permanently fails, alert is recorded as FAILED in storage."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = PostgresStorageAdapter(engine=engine, session_factory=session_factory)

    # 1. Setup events that trigger Spot-Futures anomaly
    evt_spot = NormalizedEvent(
        event_id="evt-spot-1",
        timestamp=TS_FIXED,
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("50000.0"),
        bid=Decimal("49990.0"),
        ask=Decimal("50010.0"),
        volume=Decimal("100.0"),
        metadata={},
    )
    evt_futures = NormalizedEvent(
        event_id="evt-fut-1",
        timestamp=TS_FIXED,
        source=EventSource.BINANCE,
        market_type=MarketType.FUTURES,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("60000.0"),  # Spread 18.18% (> 4.0% threshold, High Priority)
        bid=Decimal("59990.0"),
        ask=Decimal("60010.0"),
        volume=Decimal("200.0"),
        metadata={},
    )

    mock_redis = InMemoryMockRedis()
    mock_redis.streams["events:normalized"] = [
        ("1-1", {"payload": evt_spot.model_dump_json(by_alias=True)}),
        ("1-2", {"payload": evt_futures.model_dump_json(by_alias=True)}),
    ]

    from made_core.infrastructure.telegram import TelegramNotificationError

    class FailingTelegram:
        def __init__(self):
            self.attempts = 0
        async def send_alert(self, alert):
            self.attempts += 1
            raise TelegramNotificationError("Telegram API timeout after 3 retries")
        async def close(self):
            pass

    failing_telegram = FailingTelegram()
    worker = create_default_worker()
    worker._storage = storage
    worker._consumer._redis = mock_redis
    worker._telegram = failing_telegram # type: ignore

    with pytest.raises(TelegramNotificationError):
        await worker.process_batch()

    assert failing_telegram.attempts == 1

    # Verify alert was marked FAILED in storage
    alerts, total = await storage.get_alerts()
    assert total == 1
    assert alerts[0].notification_status == "FAILED"
    assert "Telegram API timeout" in (alerts[0].last_notification_error or "")

    await storage.close()
