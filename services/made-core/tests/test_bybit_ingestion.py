"""Unit tests for BybitCollector, BybitNormalizer, and Bybit ingestion flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.ingestion.collector import (
    BybitCollector,
    BybitCollectorConfig,
    CollectorError,
)
from made_core.ingestion.normalizer import BybitNormalizer, NormalizerError

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_bybit_collector_spot_ticker_success():
    mock_payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "spot",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "bid1Price": "64999.00",
                    "ask1Price": "65001.00",
                    "lastPrice": "65000.00",
                    "volume24h": "1234.5",
                }
            ],
        },
        "time": 1724673600000,
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_payload))
    client = httpx.AsyncClient(transport=transport)
    collector = BybitCollector(client=client)

    raw_event = await collector.collect("BTCUSDT", "BTC", market_type=MarketType.SPOT)

    assert raw_event.source == EventSource.BYBIT
    assert raw_event.metadata["symbol"] == "BTCUSDT"
    assert raw_event.metadata["market_type"] == "SPOT"
    assert raw_event.payload["lastPrice"] == "65000.00"
    assert raw_event.payload["serverTime"] == 1724673600000
    await collector.close()


@pytest.mark.asyncio
async def test_bybit_collector_linear_futures_with_funding_rate():
    mock_payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "linear",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "bid1Price": "65100.00",
                    "ask1Price": "65102.00",
                    "lastPrice": "65101.00",
                    "volume24h": "4567.8",
                    "fundingRate": "0.00015",
                }
            ],
        },
        "time": 1724673600000,
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_payload))
    client = httpx.AsyncClient(transport=transport)
    collector = BybitCollector(client=client)

    raw_event = await collector.collect("BTCUSDT", "BTC", market_type=MarketType.FUTURES)

    assert raw_event.source == EventSource.BYBIT
    assert raw_event.metadata["market_type"] == "FUTURES"
    assert raw_event.payload["fundingRate"] == "0.00015"
    await collector.close()


@pytest.mark.asyncio
async def test_bybit_collector_retry_on_500_and_succeed():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"list": [{"symbol": "BTCUSDT", "bid1Price": "65000", "ask1Price": "65001", "lastPrice": "65000.5", "volume24h": "100"}]},
                "time": 1724673600000,
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    config = BybitCollectorConfig(retry_base_delay_seconds=0.01)
    collector = BybitCollector(config=config, client=client)

    raw_event = await collector.collect("BTCUSDT", "BTC")
    assert calls == 2
    assert raw_event.payload["lastPrice"] == "65000.5"
    await collector.close()


@pytest.mark.asyncio
async def test_bybit_collector_error_on_retcode():
    mock_payload = {"retCode": 10001, "retMsg": "Invalid params", "result": {}}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_payload))
    client = httpx.AsyncClient(transport=transport)
    collector = BybitCollector(client=client)

    with pytest.raises(CollectorError, match="Bybit API error code 10001"):
        await collector.collect("UNKNOWN", "UNK")
    await collector.close()


def test_bybit_normalizer_spot():
    normalizer = BybitNormalizer()
    raw = RawEvent(
        event_id="raw-1",
        timestamp=TS,
        source=EventSource.BYBIT,
        payload={
            "symbol": "BTCUSDT",
            "bid1Price": "64999.00",
            "ask1Price": "65001.00",
            "lastPrice": "65000.00",
            "volume24h": "1200.5",
            "serverTime": 1724673600000,
        },
        metadata={"asset": "BTC", "symbol": "BTCUSDT", "market_type": "SPOT"},
    )

    norm = normalizer.normalize(raw)

    assert norm.source == EventSource.BYBIT
    assert norm.market_type == MarketType.SPOT
    assert norm.asset == "BTC"
    assert norm.symbol == "BTCUSDT"
    assert norm.price == Decimal("65000.00")
    assert norm.bid == Decimal("64999.00")
    assert norm.ask == Decimal("65001.00")
    assert norm.volume == Decimal("1200.5")
    assert norm.event_id == "norm:bybit:BTCUSDT:spot:1724673600000"


def test_bybit_normalizer_linear_futures_funding():
    normalizer = BybitNormalizer()
    raw = RawEvent(
        event_id="raw-2",
        timestamp=TS,
        source=EventSource.BYBIT,
        payload={
            "symbol": "BTCUSDT",
            "bid1Price": "65100.00",
            "ask1Price": "65102.00",
            "lastPrice": "65101.00",
            "volume24h": "3500.0",
            "fundingRate": "0.00015",
            "serverTime": 1724673600000,
        },
        metadata={"asset": "BTC", "symbol": "BTCUSDT", "market_type": "FUTURES"},
    )

    norm = normalizer.normalize(raw)

    assert norm.source == EventSource.BYBIT
    assert norm.market_type == MarketType.FUTURES
    assert norm.event_id == "norm:bybit:BTCUSDT:futures:1724673600000"
    assert norm.metadata.get("funding_rate") == "0.00015"


def test_bybit_normalizer_deterministic_event_id_duplicate_stability():
    normalizer = BybitNormalizer()
    payload = {
        "symbol": "BTCUSDT",
        "bid1Price": "65000",
        "ask1Price": "65001",
        "lastPrice": "65000.5",
        "volume24h": "100",
        "serverTime": 1724673600000,
    }
    raw1 = RawEvent(event_id="raw-a", timestamp=TS, source=EventSource.BYBIT, payload=payload, metadata={"market_type": "SPOT"})
    raw2 = RawEvent(event_id="raw-b", timestamp=TS, source=EventSource.BYBIT, payload=payload, metadata={"market_type": "SPOT"})

    norm1 = normalizer.normalize(raw1)
    norm2 = normalizer.normalize(raw2)

    assert norm1.event_id == norm2.event_id == "norm:bybit:BTCUSDT:spot:1724673600000"


def test_bybit_normalizer_missing_bid_raises_error():
    normalizer = BybitNormalizer()
    raw = RawEvent(
        event_id="raw-3",
        timestamp=TS,
        source=EventSource.BYBIT,
        payload={"symbol": "BTCUSDT", "ask1Price": "65001", "lastPrice": "65000"},
        metadata={"market_type": "SPOT"},
    )
    with pytest.raises(NormalizerError, match="Missing required field 'bid1Price'"):
        normalizer.normalize(raw)
