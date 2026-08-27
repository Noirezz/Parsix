"""End-to-end integration tests using real Redis and PostgreSQL."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
import os
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy import select
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
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent
from made_core.domain.enums import ResultStatus
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
        return "futures-futures-spread"

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        return DetectionResult(
            result_id=f"res-{event.event_id}",
            event_id=event.event_id,
            module_id="futures-futures-spread",
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=Decimal("4.5000000000"),
            threshold=Decimal("1.0000000000"),
            anomaly_ratio=Decimal("4.5000000000"),
            status=ResultStatus.ANOMALY,
            persistence=0,
        )


def _build_test_pipelines() -> tuple[EventPipeline, AnomalyProcessingPipeline]:
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
async def e2e_infra_config():
    redis_host = os.environ.get("MADE_REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("MADE_REDIS_PORT", "6379"))
    pg_host = os.environ.get("MADE_POSTGRES_HOST", "localhost")
    pg_port = int(os.environ.get("MADE_POSTGRES_PORT", "5432"))
    pg_db = os.environ.get("MADE_POSTGRES_DATABASE", "made_db")
    pg_user = os.environ.get("MADE_POSTGRES_USERNAME", "made_user")
    pg_pass = os.environ.get("MADE_POSTGRES_PASSWORD", "made_password")

    config = InfrastructureConfig(
        redis_host=redis_host,
        redis_port=redis_port,
        postgres_host=pg_host,
        postgres_port=pg_port,
        postgres_database=pg_db,
        postgres_username=pg_user,
        postgres_password=pg_pass,
        input_stream="test:events:normalized",
        consumer_group="test:made-core-processors",
        consumer_name="test-worker-1",
        dead_letter_stream="test:events:dead-letter",
    )
    return config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_real_redis_postgres_success_flow(e2e_infra_config: InfrastructureConfig):
    try:
        r = aioredis.from_url(e2e_infra_config.get_redis_url())
        await r.ping()
    except Exception as exc:
        pytest.skip(f"Real Redis not reachable: {exc}")

    try:
        storage = PostgresStorageAdapter(config=e2e_infra_config)
        await storage.create_tables()
    except Exception as exc:
        pytest.skip(f"Real PostgreSQL not reachable: {exc}")

    event_pipe, anom_pipe = _build_test_pipelines()
    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        config=e2e_infra_config,
    )
    # Using dummy mock transport for Telegram
    import httpx
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True, "result": {"message_id": 999}}))
    telegram = TelegramNotificationAdapter(config=e2e_infra_config, client=httpx.AsyncClient(transport=transport))

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=storage,
        telegram=telegram,
        config=e2e_infra_config,
    )

    await worker.initialize()

    # Clean test streams
    await r.delete(e2e_infra_config.input_stream)
    await r.delete(e2e_infra_config.dead_letter_stream)

    event_id = f"e2e-evt-{int(datetime.now(UTC).timestamp())}"
    payload = {
        "eventId": event_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "BINANCE",
        "marketType": "FUTURES",
        "asset": "BTC",
        "symbol": "BTCUSDT",
        "price": "65000.00",
        "bid": "64999.00",
        "ask": "65001.00",
        "volume": "100.0",
        "metadata": {"test": "e2e"},
    }

    # Publish message to Redis Stream
    msg_id = await r.xadd(e2e_infra_config.input_stream, {"payload": json.dumps(payload)})

    # Process batch with Worker
    results = await worker.process_batch()
    assert len(results) == 1
    pipe_res, alert = results[0]

    assert pipe_res is not None
    assert alert is not None
    assert alert.priority == Priority.HIGH

    # Verify PostgreSQL records
    assert await storage.is_event_processed(event_id) is True
    alert_rec = await storage.get_alert(alert.alert_id)
    assert alert_rec is not None
    assert alert_rec.notification_status == "SENT"
    assert alert_rec.notified_at is not None
    assert alert_rec.anomaly_score == Decimal("4.5000000000")

    # Cleanup
    await worker.close()
    await r.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_e2e_real_redis_malformed_message_diverts_to_dlq(e2e_infra_config: InfrastructureConfig):
    try:
        r = aioredis.from_url(e2e_infra_config.get_redis_url())
        await r.ping()
    except Exception as exc:
        pytest.skip(f"Real Redis not reachable: {exc}")

    try:
        storage = PostgresStorageAdapter(config=e2e_infra_config)
        await storage.create_tables()
    except Exception as exc:
        pytest.skip(f"Real PostgreSQL not reachable: {exc}")

    event_pipe, anom_pipe = _build_test_pipelines()
    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        config=e2e_infra_config,
    )
    import httpx
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    telegram = TelegramNotificationAdapter(config=e2e_infra_config, client=httpx.AsyncClient(transport=transport))

    worker = MadeCoreWorker(
        consumer=consumer,
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        storage=storage,
        telegram=telegram,
        config=e2e_infra_config,
    )

    await worker.initialize()
    await r.delete(e2e_infra_config.input_stream)
    await r.delete(e2e_infra_config.dead_letter_stream)

    # Publish malformed message
    msg_id = await r.xadd(e2e_infra_config.input_stream, {"payload": "invalid-json-payload-{"})

    results = await worker.process_batch()
    assert len(results) == 1
    assert results[0] == (None, None)

    # Verify DLQ received the malformed entry
    dlq_messages = await r.xrange(e2e_infra_config.dead_letter_stream)
    assert len(dlq_messages) == 1
    _, dlq_data = dlq_messages[0]
    assert b"rawPayload" in dlq_data

    await worker.close()
    await r.aclose()
