"""Unit tests for MadeCoreWorker end-to-end infrastructure orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

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
from made_core.domain.enums import Priority
from made_core.domain.models import Alert
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import (
    AlertRecord,
    Base,
    DetectionResultRecord,
    ProcessedEventRecord,
)
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram.notifier import (
    TelegramNotificationAdapter,
    TelegramNotificationError,
)
from made_core.infrastructure.worker import MadeCoreWorker
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent
from made_core.domain.enums import ResultStatus

class _DeterministicAnomalyModule(DetectionModule):
    def __init__(self, anomaly_ratio: Decimal = Decimal("4.0")) -> None:
        self._anomaly_ratio = anomaly_ratio

    def get_module_id(self) -> str:
        return "test-anomaly-module"

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        return DetectionResult(
            result_id=f"res-{event.event_id}",
            event_id=event.event_id,
            module_id="test-anomaly-module",
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=Decimal("4.0"),
            threshold=Decimal("1.0"),
            anomaly_ratio=self._anomaly_ratio,
            status=ResultStatus.ANOMALY,
            persistence=0,
        )


def _build_core_pipelines(
    threshold: Decimal = Decimal("1.0"),
    force_anomaly: bool = False,
    anomaly_ratio: Decimal = Decimal("4.0"),
) -> tuple[EventPipeline, AnomalyProcessingPipeline]:
    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()
    registry = InMemoryRuleRegistry()
    if force_anomaly:
        registry.register(_DeterministicAnomalyModule(anomaly_ratio=anomaly_ratio))
    else:
        registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=threshold)))
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)
    event_pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)
    anomaly_pipeline = AnomalyProcessingPipeline()
    return event_pipeline, anomaly_pipeline



def _make_event_dict(
    event_id: str = "evt-w-1",
    bid: str = "63999.00",
    ask: str = "64001.00",
) -> dict[str, str | dict[str, str]]:
    return {
        "eventId": event_id,
        "timestamp": TS.isoformat(),
        "source": "BINANCE",
        "marketType": "FUTURES",
        "asset": "BTC",
        "symbol": "BTCUSDT",
        "price": "64000.00",
        "bid": bid,
        "ask": ask,
        "volume": "10.0",
        "metadata": {},
    }


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
async def test_worker_successful_valid_event_without_anomaly(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(threshold=Decimal("10.0"))
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xgroup_create = AsyncMock(return_value=True)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock()
    mock_telegram.close = AsyncMock()

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    event_dict = _make_event_dict(event_id="evt-normal-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    res, alert = await worker.process_message(b"msg-1", raw_payload)

    assert res is not None
    assert alert is None
    assert await memory_storage.is_event_processed("evt-normal-1") is True
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", b"msg-1")
    mock_telegram.send_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_successful_valid_event_with_alert(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(force_anomaly=True, anomaly_ratio=Decimal("4.0"))

    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xgroup_create = AsyncMock(return_value=True)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock()
    mock_telegram.close = AsyncMock()

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    event_dict = _make_event_dict(event_id="evt-alert-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    res, alert = await worker.process_message("msg-alert-1", raw_payload)

    assert res is not None
    assert alert is not None
    assert isinstance(alert, Alert)
    assert await memory_storage.is_event_processed("evt-alert-1") is True

    # Check alert was stored in DB
    async with memory_storage._session_factory() as session:
        alert_rec = await session.get(AlertRecord, alert.alert_id)
        assert alert_rec is not None
        assert alert_rec.asset == "BTC"

    mock_telegram.send_alert.assert_awaited_once_with(alert)
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-alert-1")


@pytest.mark.asyncio
async def test_worker_invalid_event_persists_and_acks_without_telegram(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

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

    # Invalid event: bid exceeds ask
    event_dict = _make_event_dict(event_id="evt-invalid-1", bid="65000.00", ask="64000.00")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    res, alert = await worker.process_message("msg-inv-1", raw_payload)

    assert res is not None
    assert alert is None
    assert await memory_storage.is_event_processed("evt-invalid-1") is True
    mock_telegram.send_alert.assert_not_awaited()
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-inv-1")


@pytest.mark.asyncio
async def test_worker_duplicate_event_skips_processing_and_acks(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock()

    # Pre-mark event as processed
    await memory_storage.mark_event_processed("evt-dup-1", "VALID")

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    event_dict = _make_event_dict(event_id="evt-dup-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    res, alert = await worker.process_message("msg-dup-1", raw_payload)

    assert res is None
    assert alert is None
    mock_telegram.send_alert.assert_not_awaited()
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-dup-1")


@pytest.mark.asyncio
async def test_worker_malformed_message_publishes_to_dlq_and_acks(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xadd = AsyncMock(return_value=b"1-0")

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    raw_payload = {b"payload": b"malformed json content {{{"}

    res, alert = await worker.process_message("msg-bad-1", raw_payload)

    assert res is None
    assert alert is None
    mock_redis.xadd.assert_awaited_once()
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-bad-1")


@pytest.mark.asyncio
async def test_worker_postgresql_persistence_failure_does_not_ack(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_storage = MagicMock(spec=PostgresStorageAdapter)
    mock_storage.is_event_processed = AsyncMock(return_value=False)
    mock_storage.persist_processing_result = AsyncMock(side_effect=Exception("DB Connection Refused"))

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=mock_storage,
        telegram=mock_telegram,
    )

    event_dict = _make_event_dict(event_id="evt-db-fail-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    with pytest.raises(Exception, match="DB Connection Refused"):
        await worker.process_message("msg-db-fail-1", raw_payload)

    # Must NOT ACK on database error
    mock_redis.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_telegram_failure_preserves_db_and_does_not_ack(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(force_anomaly=True, anomaly_ratio=Decimal("4.0"))

    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock(side_effect=TelegramNotificationError("Network timeout on Telegram Bot API"))

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    event_dict = _make_event_dict(event_id="evt-tg-fail-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    with pytest.raises(TelegramNotificationError, match="Network timeout on Telegram Bot API"):
        await worker.process_message("msg-tg-fail-1", raw_payload)

    # 1. DB data must remain committed!
    assert await memory_storage.is_event_processed("evt-tg-fail-1") is True
    # 2. Redis message must NOT be ACKed!
    mock_redis.xack.assert_not_awaited()

    # 3. Notification status must be recorded as FAILED with error details
    pending_alert = await memory_storage.get_pending_alert_for_event("evt-tg-fail-1")
    assert pending_alert is not None
    assert pending_alert.notification_status == "FAILED"
    assert pending_alert.notification_attempts == 1
    assert "Network timeout" in (pending_alert.last_notification_error or "")


@pytest.mark.asyncio
async def test_redelivery_after_telegram_failure_retries_notification_and_succeeds(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(force_anomaly=True, anomaly_ratio=Decimal("4.0"))

    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    # Attempt 1: Telegram fails
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.send_alert = AsyncMock(side_effect=TelegramNotificationError("Telegram Outage"))

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    event_dict = _make_event_dict(event_id="evt-retry-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    with pytest.raises(TelegramNotificationError):
        await worker.process_message("msg-retry-1", raw_payload)

    # Attempt 2: Redelivered message -> Telegram now succeeds!
    mock_telegram.send_alert = AsyncMock()  # success

    res, alert = await worker.process_message("msg-retry-1", raw_payload)

    # Core was skipped (res is None because event was already in DB), alert was delivered!
    assert res is None
    assert alert is not None
    assert alert.asset == "BTC"
    mock_telegram.send_alert.assert_awaited_once()
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-retry-1")

    # Notification status must now be SENT
    pending_alert = await memory_storage.get_pending_alert_for_event("evt-retry-1")
    assert pending_alert is None  # No longer pending
    alert_rec = await memory_storage.get_alert(alert.alert_id)
    assert alert_rec is not None
    assert alert_rec.notification_status == "SENT"
    assert alert_rec.notified_at is not None


@pytest.mark.asyncio
async def test_duplicate_completed_event_skips_telegram(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(force_anomaly=True, anomaly_ratio=Decimal("4.0"))

    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

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

    event_dict = _make_event_dict(event_id="evt-sent-1")
    raw_payload = {b"payload": json.dumps(event_dict).encode("utf-8")}

    # Initial successful processing
    await worker.process_message("msg-1", raw_payload)
    assert mock_telegram.send_alert.await_count == 1
    assert mock_redis.xack.await_count == 1

    # Redelivery after successful notification
    mock_telegram.send_alert.reset_mock()
    mock_redis.xack.reset_mock()

    res, alert = await worker.process_message("msg-1", raw_payload)

    assert res is None
    assert alert is None
    # Must NOT send Telegram again!
    mock_telegram.send_alert.assert_not_awaited()
    # Must ACK the duplicate
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-1")


@pytest.mark.asyncio
async def test_worker_batch_processing(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(threshold=Decimal("10.0"))
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    event_dict1 = _make_event_dict(event_id="evt-batch-1")
    event_dict2 = _make_event_dict(event_id="evt-batch-2")

    mock_redis.xreadgroup = AsyncMock(
        return_value=[
            [
                b"events:normalized",
                [
                    (b"msg-b-1", {b"payload": json.dumps(event_dict1).encode("utf-8")}),
                    (b"msg-b-2", {b"payload": json.dumps(event_dict2).encode("utf-8")}),
                ],
            ]
        ]
    )

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    results = await worker.process_batch()

    assert len(results) == 2
    assert await memory_storage.is_event_processed("evt-batch-1") is True
    assert await memory_storage.is_event_processed("evt-batch-2") is True
    assert mock_redis.xack.await_count == 2


@pytest.mark.asyncio
async def test_worker_lifecycle_and_graceful_shutdown(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(return_value=True)
    mock_redis.xreadgroup = AsyncMock(return_value=[])
    mock_redis.aclose = AsyncMock()

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)
    mock_telegram.close = AsyncMock()

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    async with worker:
        await worker.run(max_iterations=1)

    worker.stop()
    assert worker._running is False


@pytest.mark.asyncio
async def test_worker_process_batch_reclaims_and_processes_stale_pel_messages(memory_storage: PostgresStorageAdapter):
    event_pipe, anom_pipe = _build_core_pipelines(threshold=Decimal("10.0"))
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)

    event_dict_stale = _make_event_dict(event_id="evt-pel-1")
    event_dict_new = _make_event_dict(event_id="evt-new-1")

    # Stale message reclaimed from PEL
    mock_redis.xautoclaim = AsyncMock(
        return_value=[
            b"0-0",
            [(b"msg-pel-1", {b"payload": json.dumps(event_dict_stale).encode("utf-8")})],
            [],
        ]
    )
    # New message from XREADGROUP
    mock_redis.xreadgroup = AsyncMock(
        return_value=[
            [
                b"events:normalized",
                [(b"msg-new-1", {b"payload": json.dumps(event_dict_new).encode("utf-8")})],
            ]
        ]
    )

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )
    mock_telegram = MagicMock(spec=TelegramNotificationAdapter)

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=memory_storage,
        telegram=mock_telegram,
    )

    results = await worker.process_batch()

    assert len(results) == 2
    # Both stale and new events are processed & ACKed
    assert await memory_storage.is_event_processed("evt-pel-1") is True
    assert await memory_storage.is_event_processed("evt-new-1") is True
    assert mock_redis.xack.await_count == 2


