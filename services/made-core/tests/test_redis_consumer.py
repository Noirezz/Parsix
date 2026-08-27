"""Unit tests for RedisStreamConsumer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline
from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
)
from made_core.application.validator import NormalizedEventValidator
from made_core.domain.enums import EventSource, MarketType, Priority, ResultStatus
from made_core.domain.models import NormalizedEvent
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _build_core_pipelines() -> tuple[EventPipeline, AnomalyProcessingPipeline]:
    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1.0"))))
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)
    event_pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)
    anomaly_pipeline = AnomalyProcessingPipeline()
    return event_pipeline, anomaly_pipeline


def _make_sample_event_dict() -> dict[str, Any]:
    return {
        "eventId": "evt-redis-1",
        "timestamp": TS.isoformat(),
        "source": "BINANCE",
        "marketType": "FUTURES",
        "asset": "BTC",
        "symbol": "BTCUSDT",
        "price": "64000.00",
        "bid": "63999.00",
        "ask": "64001.00",
        "volume": "15.5",
        "metadata": {},
    }



@pytest.mark.asyncio
async def test_consumer_group_initialization_success():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(return_value=True)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    await consumer.initialize()
    mock_redis.xgroup_create.assert_awaited_once_with(
        name="events:normalized",
        groupname="made-core-processors",
        id="0",
        mkstream=True,
    )


@pytest.mark.asyncio
async def test_consumer_group_already_exists_is_ignored():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP Consumer Group name already exists"))

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    # Should not raise exception
    await consumer.initialize()


@pytest.mark.asyncio
async def test_consumer_group_unexpected_error_raises():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(side_effect=Exception("NOPERM Authentication required"))

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    with pytest.raises(Exception, match="NOPERM Authentication required"):
        await consumer.initialize()


def test_deserialize_message_from_json_payload():
    event_pipe, anom_pipe = _build_core_pipelines()
    consumer = RedisStreamConsumer(event_pipeline=event_pipe, anomaly_pipeline=anom_pipe)

    event_data = _make_sample_event_dict()
    raw_redis_msg = {b"payload": json.dumps(event_data).encode("utf-8")}

    event = consumer.deserialize_message(raw_redis_msg)

    assert isinstance(event, NormalizedEvent)
    assert event.event_id == "evt-redis-1"
    assert event.asset == "BTC"
    assert event.price == Decimal("64000.00")
    assert event.bid == Decimal("63999.00")
    assert event.ask == Decimal("64001.00")


def test_deserialize_message_from_key_value_dict():
    event_pipe, anom_pipe = _build_core_pipelines()
    consumer = RedisStreamConsumer(event_pipeline=event_pipe, anomaly_pipeline=anom_pipe)

    event_data = _make_sample_event_dict()
    raw_redis_msg = {
        k.encode("utf-8"): (json.dumps(v).encode("utf-8") if isinstance(v, (dict, list)) else str(v).encode("utf-8"))
        for k, v in event_data.items()
    }

    event = consumer.deserialize_message(raw_redis_msg)

    assert isinstance(event, NormalizedEvent)
    assert event.event_id == "evt-redis-1"
    assert event.source is EventSource.BINANCE
    assert event.market_type is MarketType.FUTURES


@pytest.mark.asyncio
async def test_handle_valid_message_success_and_ack():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xadd = AsyncMock(return_value=b"1-0")

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    event_data = _make_sample_event_dict()
    raw_msg = {b"payload": json.dumps(event_data).encode("utf-8")}

    pipe_res, alert = await consumer.handle_message(b"1700000000-1", raw_msg)

    assert pipe_res is not None
    assert pipe_res.event_id == "evt-redis-1"
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", b"1700000000-1")
    # DLQ should not be called
    mock_redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_malformed_json_publishes_to_dlq_and_acks():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xadd = AsyncMock(return_value=b"1-0")

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    malformed_msg = {b"payload": b"invalid json content {"}

    pipe_res, alert = await consumer.handle_message(b"msg-bad-1", malformed_msg)

    assert pipe_res is None
    assert alert is None

    # Should publish to DLQ
    mock_redis.xadd.assert_awaited_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "events:dead-letter"
    assert "error" in call_args[0][1]

    # Should ACK to unblock stream
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", b"msg-bad-1")


@pytest.mark.asyncio
async def test_handle_invalid_event_schema_publishes_to_dlq_and_acks():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xack = AsyncMock(return_value=1)
    mock_redis.xadd = AsyncMock(return_value=b"1-0")

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    # Missing price and negative volume
    invalid_schema = {"eventId": "123", "volume": "-10.0"}
    raw_msg = {b"payload": json.dumps(invalid_schema).encode("utf-8")}

    pipe_res, alert = await consumer.handle_message("msg-invalid-schema", raw_msg)

    assert pipe_res is None
    assert alert is None
    mock_redis.xadd.assert_awaited_once()
    mock_redis.xack.assert_awaited_once_with("events:normalized", "made-core-processors", "msg-invalid-schema")


@pytest.mark.asyncio
async def test_read_and_process_batch():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    event_data = _make_sample_event_dict()
    raw_payload = {b"payload": json.dumps(event_data).encode("utf-8")}

    mock_redis.xreadgroup = AsyncMock(
        return_value=[
            [
                b"events:normalized",
                [
                    (b"1700000000-1", raw_payload),
                    (b"1700000000-2", raw_payload),
                ],
            ]
        ]
    )
    mock_redis.xack = AsyncMock(return_value=1)

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    results = await consumer.process_one_batch()

    assert len(results) == 2
    assert mock_redis.xack.await_count == 2


@pytest.mark.asyncio
async def test_run_with_max_iterations_and_stop():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(return_value=True)
    mock_redis.xreadgroup = AsyncMock(return_value=[])

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    await consumer.run(max_iterations=2)
    assert mock_redis.xreadgroup.await_count == 2


@pytest.mark.asyncio
async def test_async_context_manager_and_close():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xgroup_create = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock()

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    async with consumer:
        assert consumer._redis is mock_redis

    consumer.stop()


@pytest.mark.asyncio
async def test_claim_stale_messages_success():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xautoclaim = AsyncMock(
        return_value=[
            b"0-0",
            [
                (b"msg-stale-1", {b"payload": b'{"eventId":"evt-1"}'}),
                (b"msg-stale-2", {b"payload": b'{"eventId":"evt-2"}'}),
            ],
            [],
        ]
    )

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    claimed = await consumer.claim_stale_messages(min_idle_ms=5000)

    assert len(claimed) == 2
    assert claimed[0][0] == "msg-stale-1"
    assert claimed[1][0] == "msg-stale-2"
    mock_redis.xautoclaim.assert_awaited_once_with(
        name="events:normalized",
        groupname="made-core-processors",
        consumername="made-core-worker-1",
        min_idle_time=5000,
        start_id="0-0",
        count=10,
    )


@pytest.mark.asyncio
async def test_claim_stale_messages_error_returns_empty():
    event_pipe, anom_pipe = _build_core_pipelines()
    mock_redis = MagicMock()
    mock_redis.xautoclaim = AsyncMock(side_effect=Exception("Redis connection error"))

    consumer = RedisStreamConsumer(
        event_pipeline=event_pipe,
        anomaly_pipeline=anom_pipe,
        redis_client=mock_redis,
    )

    claimed = await consumer.claim_stale_messages()
    assert claimed == []

