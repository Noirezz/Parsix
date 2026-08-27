"""Unit tests for IngestionPipeline."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.ingestion.collector import BinanceCollector
from made_core.ingestion.normalizer import BinanceNormalizer
from made_core.ingestion.pipeline import IngestionPipeline
from made_core.ingestion.publisher import RedisEventPublisher



@pytest.mark.asyncio
async def test_ingestion_pipeline_end_to_end():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "lastPrice": "64500.00",
                "bidPrice": "64499.00",
                "askPrice": "64501.00",
                "volume": "500.0",
                "closeTime": 1700000000000,
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    collector = BinanceCollector(client=http_client)
    normalizer = BinanceNormalizer()

    mock_redis = MagicMock()
    mock_redis.xadd = AsyncMock(return_value=b"1700000000000-1")
    publisher = RedisEventPublisher(redis_client=mock_redis)

    pipeline = IngestionPipeline(collector=collector, normalizer=normalizer, publisher=publisher)

    raw, norm, msg_id = await pipeline.ingest(symbol="BTCUSDT", asset="BTC", market_type=MarketType.SPOT)

    assert isinstance(raw, RawEvent)
    assert raw.source == EventSource.BINANCE

    assert isinstance(norm, NormalizedEvent)
    assert norm.asset == "BTC"
    assert norm.symbol == "BTCUSDT"
    assert norm.price == Decimal("64500.00")
    assert norm.bid == Decimal("64499.00")
    assert norm.ask == Decimal("64501.00")
    assert norm.volume == Decimal("500.0")

    assert msg_id == "1700000000000-1"
    mock_redis.xadd.assert_awaited_once()

    await pipeline.close()
