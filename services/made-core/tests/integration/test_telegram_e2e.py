"""End-to-end Telegram integration tests using mock HTTP transports and real persistence state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
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
from made_core.domain.enums import Priority, ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent

from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import AlertRecord, Base
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram.notifier import (
    TelegramNotificationAdapter,
    TelegramNotificationError,
)
from made_core.infrastructure.worker import MadeCoreWorker


class _DeterministicAnomalyModule(DetectionModule):
    def get_module_id(self) -> str:
        return "tg-e2e-module"

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        return DetectionResult(
            result_id=f"res-tg-{event.event_id}",
            event_id=event.event_id,
            module_id="tg-e2e-module",
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=Decimal("4.0"),
            threshold=Decimal("1.0"),
            anomaly_ratio=Decimal("4.0"),
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
async def memory_storage():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    adapter = PostgresStorageAdapter(engine=engine, session_factory=session_factory)
    yield adapter
    await adapter.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_telegram_e2e_success_lifecycle(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    sent_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 12345}})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    telegram = TelegramNotificationAdapter(
        config=InfrastructureConfig(telegram_bot_token="test_token", telegram_chat_id="12345"),
        client=http_client,
    )

    consumer = RedisStreamConsumer(event_pipeline=event_pipe, anomaly_pipeline=anom_pipe, redis_client=mock_redis)

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=telegram,
    )

    event_payload = {
        "eventId": "evt-tg-e2e-1",
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

    res, alert = await worker.process_message("msg-tg-1", raw_payload)

    assert alert is not None
    assert len(sent_requests) == 1
    assert mock_redis.xack.await_count == 1

    # Verify notification state
    alert_rec = await memory_storage.get_alert(alert.alert_id)
    assert alert_rec is not None
    assert alert_rec.notification_status == "SENT"
    assert alert_rec.notified_at is not None

    await worker.close()


@pytest.mark.asyncio
async def test_telegram_e2e_failure_then_redelivery_retry(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    telegram_server_down = True

    def mock_flaky_handler(request: httpx.Request) -> httpx.Response:
        if telegram_server_down:
            return httpx.Response(500, json={"ok": False, "description": "Internal server error"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 54321}})

    transport = httpx.MockTransport(mock_flaky_handler)
    http_client = httpx.AsyncClient(transport=transport)
    telegram = TelegramNotificationAdapter(
        config=InfrastructureConfig(
            telegram_bot_token="test_token",
            telegram_chat_id="12345",
            telegram_max_retries=1,
            telegram_retry_base_delay_seconds=0.01,
        ),
        client=http_client,
    )


    consumer = RedisStreamConsumer(event_pipeline=event_pipe, anomaly_pipeline=anom_pipe, redis_client=mock_redis)

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=telegram,
    )

    event_payload = {
        "eventId": "evt-tg-e2e-2",
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

    # First attempt -> Telegram fails
    with pytest.raises(TelegramNotificationError):
        await worker.process_message("msg-tg-2", raw_payload)

    # Message must NOT be ACKed
    mock_redis.xack.assert_not_awaited()

    # Alert record must be FAILED
    pending = await memory_storage.get_pending_alert_for_event("evt-tg-e2e-2")
    assert pending is not None
    assert pending.notification_status == "FAILED"

    # Redeliver the message -> Attempt 2 succeeds!
    telegram_server_down = False
    res, alert = await worker.process_message("msg-tg-2", raw_payload)


    # Message must now be ACKed
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-tg-2")

    # Alert record must now be SENT
    alert_rec = await memory_storage.get_alert(pending.alert_id)
    assert alert_rec is not None
    assert alert_rec.notification_status == "SENT"
    assert alert_rec.notified_at is not None

    await worker.close()
