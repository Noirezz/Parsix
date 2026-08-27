"""End-to-end integration test connecting Ingestion (Collector + Normalizer + Publisher) with MadeCoreWorker."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from made_core.application.aggregator import DefaultResultAggregator
from made_core.application.alerting import DefaultAlertGenerator
from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline
from made_core.application.priority import DefaultPriorityEvaluator

from made_core.application.rule_engine import InMemoryRuleRegistry, RegistryModuleLoader, RuleEngineExecutor
from made_core.application.validator import NormalizedEventValidator
from made_core.domain.enums import MarketType
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import Base
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram import TelegramNotificationAdapter
from made_core.infrastructure.worker import MadeCoreWorker
from made_core.ingestion.collector import BinanceCollector
from made_core.ingestion.normalizer import BinanceNormalizer
from made_core.ingestion.pipeline import IngestionPipeline
from made_core.ingestion.publisher import RedisEventPublisher
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig, FuturesFuturesSpreadModule


def _build_core_pipelines():
    registry = InMemoryRuleRegistry()
    module = FuturesFuturesSpreadModule(
        FuturesFuturesSpreadConfig(
            threshold=Decimal("1.0"),  # Trigger anomaly on > 1% spread
        )
    )
    registry.register(module)

    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()
    event_pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)

    correlation = DefaultCorrelationEngine()
    aggregator = DefaultResultAggregator()
    priority = DefaultPriorityEvaluator()
    alerting = DefaultAlertGenerator()

    anomaly_pipeline = AnomalyProcessingPipeline(
        aggregator=aggregator,
        correlation_engine=correlation,
        priority_evaluator=priority,
        alert_generator=alerting,
    )

    return event_pipeline, anomaly_pipeline


@pytest_asyncio.fixture
async def memory_storage(tmp_path):
    db_file = tmp_path / "test_ingestion_e2e.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    adapter = PostgresStorageAdapter(engine=engine, session_factory=session_factory)
    yield adapter
    await adapter.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_ingestion_to_detection_and_storage_e2e(memory_storage: PostgresStorageAdapter):
    """Test full pipeline: Mock Binance -> Collector -> Normalizer -> Publisher -> RedisStreamConsumer -> Worker -> DB -> Telegram."""

    # 1. Mock Binance Exchange API
    def mock_binance_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "lastPrice": "64000.00",
                "bidPrice": "63999.00",
                "askPrice": "64001.00",
                "volume": "150.0",
                "closeTime": 1700000000000,
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_binance_handler))
    collector = BinanceCollector(client=http_client)
    normalizer = BinanceNormalizer()

    # 2. Redis in-memory mock simulating Stream buffer
    stream_buffer: list[tuple[str, dict]] = []

    mock_redis = MagicMock()

    async def mock_xadd(stream_name, fields):
        msg_id = f"1700000000000-{len(stream_buffer)}"
        stream_buffer.append((msg_id, fields))
        return msg_id.encode("utf-8")

    async def mock_xreadgroup(groupname, consumername, streams, count, block):
        if not stream_buffer:
            return []
        msgs = list(stream_buffer)
        stream_buffer.clear()
        return [("events:normalized", [(msg_id.encode("utf-8"), fields) for msg_id, fields in msgs])]

    mock_redis.xadd = AsyncMock(side_effect=mock_xadd)
    mock_redis.xreadgroup = AsyncMock(side_effect=mock_xreadgroup)
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xautoclaim = AsyncMock(return_value=[b"0-0", [], []])

    publisher = RedisEventPublisher(redis_client=mock_redis)
    ingestion_pipeline = IngestionPipeline(collector=collector, normalizer=normalizer, publisher=publisher)

    # 3. Core Pipelines and Worker setup
    event_pipe, anom_pipe = _build_core_pipelines()
    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock()

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    # 4. Ingestion Step: Collect, Normalize, Publish
    raw_event, normalized_event, msg_id = await ingestion_pipeline.ingest(
        symbol="BTCUSDT",
        asset="BTC",
        market_type=MarketType.SPOT,
    )

    assert raw_event.source.value == "BINANCE"
    assert normalized_event.price == Decimal("64000.00")
    assert msg_id == "1700000000000-0"
    assert len(stream_buffer) == 1

    # 5. Worker Step: Consume from Redis, Execute Core, Persist in DB, ACK
    results = await worker.process_batch()

    assert len(results) == 1
    pipe_res, alert = results[0]
    assert pipe_res is not None
    assert pipe_res.event_id == normalized_event.event_id

    # 6. Verify Database Persistence
    assert await memory_storage.is_event_processed(normalized_event.event_id) is True
    from sqlalchemy import select
    from made_core.infrastructure.postgres.models import DetectionResultRecord
    async with memory_storage._session_factory() as session:
        stmt = select(DetectionResultRecord).where(DetectionResultRecord.event_id == normalized_event.event_id)
        res = await session.execute(stmt)
        detections = res.scalars().all()
        assert len(detections) == 1
        assert detections[0].asset == "BTC"


    # 7. Verify Redis ACK
    mock_redis.xack.assert_awaited_once_with(
        "events:normalized",
        "made-core-processors",
        "1700000000000-0",
    )

    await ingestion_pipeline.close()
