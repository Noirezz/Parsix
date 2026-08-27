"""Unit tests for RedisEventPublisher."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent
from made_core.infrastructure.config import InfrastructureConfig
from made_core.ingestion.publisher import PublisherError, RedisEventPublisher


def _make_sample_event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="norm-pub-1",
        timestamp=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("64000.50"),
        bid=Decimal("64000.00"),
        ask=Decimal("64001.00"),
        volume=Decimal("100.0"),
    )


@pytest.mark.asyncio
async def test_redis_event_publisher_publishes_canonical_json():
    mock_redis = MagicMock()
    mock_redis.xadd = AsyncMock(return_value=b"1700000000000-0")

    publisher = RedisEventPublisher(
        config=InfrastructureConfig(input_stream="events:normalized"),
        redis_client=mock_redis,
    )

    event = _make_sample_event()
    msg_id = await publisher.publish(event)

    assert msg_id == "1700000000000-0"
    mock_redis.xadd.assert_awaited_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "events:normalized"
    payload = call_args[0][1]["payload"]
    assert "norm-pub-1" in payload
    assert "BTCUSDT" in payload
    assert "64000.50" in payload


@pytest.mark.asyncio
async def test_redis_event_publisher_rejects_none():
    publisher = RedisEventPublisher()
    with pytest.raises(PublisherError, match="event must not be None"):
        await publisher.publish(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_redis_event_publisher_error_handling():
    mock_redis = MagicMock()
    mock_redis.xadd = AsyncMock(side_effect=Exception("Redis Connection Refused"))

    publisher = RedisEventPublisher(redis_client=mock_redis)
    event = _make_sample_event()

    with pytest.raises(PublisherError, match="Failed to publish event"):
        await publisher.publish(event)


@pytest.mark.asyncio
async def test_redis_event_publisher_lifecycle():
    mock_redis = MagicMock()
    mock_redis.aclose = AsyncMock()

    publisher = RedisEventPublisher(redis_client=mock_redis)
    publisher._owns_redis = True

    async with publisher:
        assert publisher._redis is mock_redis

    mock_redis.aclose.assert_awaited_once()
