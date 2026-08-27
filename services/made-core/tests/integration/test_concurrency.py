"""Concurrency and race condition integration tests for MadeCoreWorker and PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline

from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
)
from made_core.application.validator import NormalizedEventValidator
from made_core.domain.enums import ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import (
    AlertRecord,
    Base,
    DetectionResultRecord,
    ProcessedEventRecord,
)
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram.notifier import TelegramNotificationAdapter
from made_core.infrastructure.worker import MadeCoreWorker


class _DeterministicAnomalyModule(DetectionModule):
    def get_module_id(self) -> str:
        return "concurrent-module"

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        return DetectionResult(
            result_id=f"res-conc-{event.event_id}",
            event_id=event.event_id,
            module_id="concurrent-module",
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=Decimal("5.0"),
            threshold=Decimal("1.0"),
            anomaly_ratio=Decimal("5.0"),
            status=ResultStatus.ANOMALY,
            persistence=0,
        )


def _build_core_pipelines() -> tuple[EventPipeline, AnomalyProcessingPipeline]:
    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()
    registry = InMemoryRuleRegistry()
    registry.register(_DeterministicAnomalyModule())
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)
    event_pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)
    anomaly_pipeline = AnomalyProcessingPipeline()
    return event_pipeline, anomaly_pipeline


@pytest_asyncio.fixture
async def shared_storage(tmp_path):
    db_file = tmp_path / "test_concurrency.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    adapter = PostgresStorageAdapter(engine=engine, session_factory=session_factory)
    yield adapter
    await adapter.close()
    await engine.dispose()




@pytest.mark.asyncio
async def test_concurrent_duplicate_processing_is_idempotent(shared_storage: PostgresStorageAdapter):
    """Simulate two workers processing the exact same event concurrently."""
    event_pipe1, anom_pipe1 = _build_core_pipelines()
    event_pipe2, anom_pipe2 = _build_core_pipelines()

    mock_redis1 = MagicMock()
    mock_redis1.xack = AsyncMock(return_value=1)
    mock_redis2 = MagicMock()
    mock_redis2.xack = AsyncMock(return_value=1)

    consumer1 = RedisStreamConsumer(event_pipeline=event_pipe1, anomaly_pipeline=anom_pipe1, redis_client=mock_redis1)
    consumer2 = RedisStreamConsumer(event_pipeline=event_pipe2, anomaly_pipeline=anom_pipe2, redis_client=mock_redis2)

    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock()

    worker1 = MadeCoreWorker(
        consumer=consumer1,
        event_pipeline=event_pipe1,
        anomaly_pipeline=anom_pipe1,
        storage=shared_storage,
        telegram=mock_telegram,
    )
    worker2 = MadeCoreWorker(
        consumer=consumer2,
        event_pipeline=event_pipe2,
        anomaly_pipeline=anom_pipe2,
        storage=shared_storage,
        telegram=mock_telegram,
    )

    import json
    event_payload = {
        "eventId": "evt-concurrent-100",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "BINANCE",
        "marketType": "FUTURES",
        "asset": "BTC",
        "symbol": "BTCUSDT",
        "price": "64000.00",
        "bid": "63999.00",
        "ask": "64001.00",
        "volume": "10.0",
        "metadata": {},
    }
    raw_payload = {b"payload": json.dumps(event_payload).encode("utf-8")}

    # Launch both workers on the same event simultaneously
    res1, res2 = await asyncio.gather(
        worker1.process_message("msg-c-1", raw_payload),
        worker2.process_message("msg-c-2", raw_payload),
    )



    # Verify that database records are exactly 1 per table (no duplicates)
    async with shared_storage._session_factory() as session:
        # Detections
        det_count = await session.scalar(
            select(func.count(DetectionResultRecord.result_id)).where(DetectionResultRecord.event_id == "evt-concurrent-100")
        )
        assert det_count == 1

        # Processed events
        proc_count = await session.scalar(
            select(func.count(ProcessedEventRecord.event_id)).where(ProcessedEventRecord.event_id == "evt-concurrent-100")
        )
        assert proc_count == 1

        # Alerts
        alert_count = await session.scalar(
            select(func.count(AlertRecord.alert_id)).where(AlertRecord.event_id == "evt-concurrent-100")
        )
        assert alert_count == 1

        # Status must be SENT
        alert_rec = (
            await session.execute(select(AlertRecord).where(AlertRecord.event_id == "evt-concurrent-100"))
        ).scalars().first()
        assert alert_rec is not None
        assert alert_rec.notification_status == "SENT"

    # Both messages must be acknowledged
    mock_redis1.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-c-1")
    mock_redis2.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-c-2")
