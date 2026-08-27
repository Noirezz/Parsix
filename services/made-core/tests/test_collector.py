"""Unit tests for BinanceCollector market data ingestion."""

from __future__ import annotations

import httpx
import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import RawEvent
from made_core.ingestion.collector import (
    BinanceCollector,
    CollectorConfig,
    CollectorError,
)


@pytest.mark.asyncio
async def test_binance_collector_fetch_ticker_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/ticker/24hr"
        assert request.url.params["symbol"] == "BTCUSDT"
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "lastPrice": "64250.50",
                "bidPrice": "64250.00",
                "askPrice": "64251.00",
                "volume": "1234.5678",
                "closeTime": 1700000000000,
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    collector = BinanceCollector(client=client)

    data = await collector.fetch_ticker("BTCUSDT")
    assert data["symbol"] == "BTCUSDT"
    assert data["lastPrice"] == "64250.50"
    await collector.close()


@pytest.mark.asyncio
async def test_binance_collector_retries_on_500_and_succeeds():
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(
            200,
            json={"symbol": "ETHUSDT", "bidPrice": "3400.00", "askPrice": "3401.00"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    config = CollectorConfig(max_retries=2, retry_base_delay_seconds=0.01)
    collector = BinanceCollector(config=config, client=client)

    data = await collector.fetch_ticker("ETHUSDT")
    assert data["symbol"] == "ETHUSDT"
    assert attempts == 2
    await collector.close()


@pytest.mark.asyncio
async def test_binance_collector_retries_on_429_and_succeeds():
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, text="Rate Limited")
        return httpx.Response(
            200,
            json={"symbol": "SOLUSDT", "bidPrice": "150.00", "askPrice": "150.10"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    config = CollectorConfig(max_retries=2, retry_base_delay_seconds=0.01)
    collector = BinanceCollector(config=config, client=client)

    data = await collector.fetch_ticker("SOLUSDT")
    assert data["symbol"] == "SOLUSDT"
    assert attempts == 2
    await collector.close()


@pytest.mark.asyncio
async def test_binance_collector_fails_after_max_retries():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    config = CollectorConfig(max_retries=1, retry_base_delay_seconds=0.01)
    collector = BinanceCollector(config=config, client=client)

    with pytest.raises(CollectorError, match="503"):
        await collector.fetch_ticker("BTCUSDT")

    await collector.close()


@pytest.mark.asyncio
async def test_binance_collector_collect_produces_raw_event():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "lastPrice": "64000.00",
                "bidPrice": "63999.00",
                "askPrice": "64001.00",
                "volume": "100.0",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    collector = BinanceCollector(client=client)

    raw_event = await collector.collect(symbol="BTCUSDT", asset="BTC", market_type=MarketType.SPOT)

    assert isinstance(raw_event, RawEvent)
    assert raw_event.source == EventSource.BINANCE
    assert raw_event.metadata["asset"] == "BTC"
    assert raw_event.metadata["symbol"] == "BTCUSDT"
    assert raw_event.metadata["market_type"] == "SPOT"
    assert raw_event.payload["lastPrice"] == "64000.00"
    assert raw_event.timestamp.tzinfo is not None

    await collector.close()


@pytest.mark.asyncio
async def test_binance_collector_async_context_manager():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbol": "BTCUSDT", "bidPrice": "1", "askPrice": "2"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    async with BinanceCollector(client=client) as collector:
        res = await collector.fetch_ticker("BTCUSDT")
        assert res["symbol"] == "BTCUSDT"
