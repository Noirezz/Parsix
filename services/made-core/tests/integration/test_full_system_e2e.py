"""Full System End-to-End Integration Verification Test.

Validates the complete chain:
MultiSource Ingestion -> Normalization -> Redis Stream -> MadeCoreWorker ->
SnapshotCache -> RuleEngine (4 Modules) -> Aggregator -> Correlator ->
PriorityEvaluator -> AlertGenerator -> PostgreSQL -> FastAPI Query Service -> REST API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import RawEvent
from made_core.infrastructure.entrypoint import create_default_worker
from made_core.infrastructure.postgres.models import Base
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.ingestion.collector import BinanceCollector, BybitCollector
from made_core.ingestion.normalizer import BinanceNormalizer, BybitNormalizer
from made_core.ingestion.pipeline import MultiSourceIngestionPipeline, SourceTarget
from made_core.ingestion.publisher import RedisEventPublisher

from made_api.main import create_app

TS_FIXED = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)


class InMemoryMockRedis:
    """In-memory Redis Stream mock for deterministic multi-service integration."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._counter = 0

    async def xadd(self, name: str, fields: dict[str, str], maxlen: int | None = None) -> str:
        self._counter += 1
        msg_id = f"{int(TS_FIXED.timestamp() * 1000)}-{self._counter}"
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

    async def xack(self, name: str, groupname: str, *ids: str) -> int:
        return len(ids)

    async def xgroup_create(self, name: str, groupname: str, id: str = "$", mkstream: bool = False) -> bool:
        if name not in self.streams and mkstream:
            self.streams[name] = []
        return True

    async def xautoclaim(self, *args: Any, **kwargs: Any) -> tuple[str, list[Any], list[Any]]:
        return ("0-0", [], [])

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_full_system_lifecycle_ingest_to_api():
    """Verify complete lifecycle from multi-source market ingestion to FastAPI presentation."""
    # 1. Setup in-memory database and storage
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = PostgresStorageAdapter(engine=engine, session_factory=session_factory)

    # 2. Setup mock Redis stream bus
    mock_redis = InMemoryMockRedis()

    # 3. Setup Multi-Source Ingestion Pipeline
    binance_col = BinanceCollector()
    bybit_col = BybitCollector()
    binance_norm = BinanceNormalizer()
    bybit_norm = BybitNormalizer()

    async def mock_binance_collect(symbol: str, asset: str, market_type: MarketType = MarketType.SPOT) -> RawEvent:
        if market_type == MarketType.SPOT:
            return RawEvent(
                timestamp=TS_FIXED,
                event_id="raw:binance:spot:btc:1",
                source=EventSource.BINANCE,
                payload={"symbol": symbol, "lastPrice": "50000.00", "bidPrice": "49990.00", "askPrice": "50010.00", "volume": "100.0"},
                metadata={"symbol": symbol, "asset": asset, "market_type": market_type.value},
            )
        return RawEvent(
            timestamp=TS_FIXED,
            event_id="raw:binance:futures:btc:1",
            source=EventSource.BINANCE,
            payload={"symbol": symbol, "lastPrice": "60000.00", "bidPrice": "59990.00", "askPrice": "60010.00", "volume": "200.0", "fundingRate": "0.0003"},
            metadata={"symbol": symbol, "asset": asset, "market_type": market_type.value},
        )

    binance_col.collect = mock_binance_collect # type: ignore

    publisher = RedisEventPublisher(redis_client=mock_redis) # type: ignore
    ingest_pipeline = MultiSourceIngestionPipeline(
        collectors={EventSource.BINANCE: binance_col, EventSource.BYBIT: bybit_col},
        normalizers={EventSource.BINANCE: binance_norm, EventSource.BYBIT: bybit_norm},
        publisher=publisher,
    )

    # Ingest Binance Spot & Futures
    targets = [
        SourceTarget(source=EventSource.BINANCE, market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT"),
        SourceTarget(source=EventSource.BINANCE, market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSDT"),
    ]
    results = await ingest_pipeline.ingest_all(targets)
    assert len(results) == 2
    assert all(err is None for _, _, _, err in results)

    # 4. Setup MADE Core Worker
    class MockTelegram:
        def __init__(self):
            self.sent_alerts = []
        async def send_alert(self, alert):
            self.sent_alerts.append(alert)
            return True
        async def close(self):
            pass

    mock_telegram = MockTelegram()
    worker = create_default_worker()
    worker._storage = storage
    worker._consumer._redis = mock_redis
    worker._telegram = mock_telegram # type: ignore

    # Process batch in worker
    batch_results = await worker.process_batch()
    assert len(batch_results) == 2
    assert len(mock_telegram.sent_alerts) == 1
    assert mock_telegram.sent_alerts[0].priority.value == "HIGH"

    # 5. Query via FastAPI REST API
    app = create_app(storage=storage)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # A. Health & Readiness
        ready_resp = await client.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json() == {"status": "ready", "database": "connected"}

        # B. Events
        events_resp = await client.get("/api/v1/events")
        assert events_resp.status_code == 200
        assert events_resp.json()["total"] == 2

        # C. Detections
        det_resp = await client.get("/api/v1/detections")
        assert det_resp.status_code == 200
        assert det_resp.json()["total"] > 0

        # D. Aggregates
        agg_resp = await client.get("/api/v1/aggregates")
        assert agg_resp.status_code == 200
        assert agg_resp.json()["total"] == 1
        assert agg_resp.json()["items"][0]["priority"] == "HIGH"

        # E. Alerts
        alerts_resp = await client.get("/api/v1/alerts")
        assert alerts_resp.status_code == 200
        assert alerts_resp.json()["total"] == 1
        assert alerts_resp.json()["items"][0]["title"] == "[HIGH] BTC anomaly detected"
        assert alerts_resp.json()["items"][0]["notification_status"] == "SENT"

        # F. Modules
        mod_resp = await client.get("/api/v1/modules")
        assert mod_resp.status_code == 200
        assert len(mod_resp.json()) == 4

        # G. Metrics
        metrics_resp = await client.get("/api/v1/metrics")
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert metrics["total_processed_events"] == 2
        assert metrics["total_alerts"] == 1
        assert metrics["alerts_by_priority"]["HIGH"] == 1

    await storage.close()
    await ingest_pipeline.close()
