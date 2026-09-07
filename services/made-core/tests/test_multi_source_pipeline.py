"""Unit tests for MultiSourceIngestionPipeline and concurrent ingestion."""

from __future__ import annotations

from decimal import Decimal
import pytest
import httpx

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent
from made_core.ingestion.collector import BinanceCollector, BybitCollector
from made_core.ingestion.normalizer import BinanceNormalizer, BybitNormalizer
from made_core.ingestion.pipeline import MultiSourceIngestionPipeline, SourceTarget
from made_core.infrastructure.config import InfrastructureConfig


class _FakeRedisPublisher:
    def __init__(self):
        self.published: list[NormalizedEvent] = []

    async def publish(self, event: NormalizedEvent, stream_name: str | None = None) -> str:
        self.published.append(event)
        return f"msg-{len(self.published)}"

    async def publish_batch(self, events: Sequence[NormalizedEvent], stream_name: str | None = None) -> list[str]:
        ids = []
        for e in events:
            self.published.append(e)
            ids.append(f"msg-{len(self.published)}")
        return ids

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_multi_source_pipeline_ingest_all_concurrent():
    binance_spot_data = {"symbol": "BTCUSDT", "lastPrice": "65000", "bidPrice": "64999", "askPrice": "65001", "volume": "100", "closeTime": 1724673600000}
    binance_fut_data = {"symbol": "BTCUSDT", "lastPrice": "65200", "bidPrice": "65199", "askPrice": "65201", "volume": "200", "closeTime": 1724673600000}
    bybit_fut_data = {"retCode": 0, "retMsg": "OK", "result": {"list": [{"symbol": "BTCUSDT", "lastPrice": "65300", "bid1Price": "65299", "ask1Price": "65301", "volume24h": "300", "fundingRate": "0.0001"}]}, "time": 1724673600000}

    def binance_handler(req: httpx.Request) -> httpx.Response:
        if "fapi" in str(req.url):
            if "premiumIndex" in str(req.url):
                return httpx.Response(200, json={"symbol": "BTCUSDT", "lastFundingRate": "0.0001"})
            return httpx.Response(200, json=binance_fut_data)
        return httpx.Response(200, json=binance_spot_data)

    def bybit_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bybit_fut_data)

    binance_client = httpx.AsyncClient(transport=httpx.MockTransport(binance_handler))
    bybit_client = httpx.AsyncClient(transport=httpx.MockTransport(bybit_handler))

    collectors = {
        EventSource.BINANCE: BinanceCollector(client=binance_client),
        EventSource.BYBIT: BybitCollector(client=bybit_client),
    }
    normalizers = {
        EventSource.BINANCE: BinanceNormalizer(),
        EventSource.BYBIT: BybitNormalizer(),
    }
    publisher = _FakeRedisPublisher()

    pipeline = MultiSourceIngestionPipeline(
        collectors=collectors,
        normalizers=normalizers,
        publisher=publisher,
    )

    targets = [
        SourceTarget(source=EventSource.BINANCE, market_type=MarketType.SPOT, symbol="BTCUSDT", asset="BTC"),
        SourceTarget(source=EventSource.BINANCE, market_type=MarketType.FUTURES, symbol="BTCUSDT", asset="BTC"),
        SourceTarget(source=EventSource.BYBIT, market_type=MarketType.FUTURES, symbol="BTCUSDT", asset="BTC"),
    ]

    results = await pipeline.ingest_all(targets)

    assert len(results) == 3
    for raw, norm, msg_id, err in results:
        assert err is None
        assert norm is not None
        assert msg_id is not None

    assert len(publisher.published) == 3
    sources = {e.source for e in publisher.published}
    market_types = {e.market_type for e in publisher.published}
    assert sources == {EventSource.BINANCE, EventSource.BYBIT}
    assert market_types == {MarketType.SPOT, MarketType.FUTURES}

    await pipeline.close()


@pytest.mark.asyncio
async def test_multi_source_pipeline_partial_failure_isolation():
    binance_spot_data = {"symbol": "BTCUSDT", "lastPrice": "65000", "bidPrice": "64999", "askPrice": "65001", "volume": "100", "closeTime": 1724673600000}

    def binance_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=binance_spot_data)

    def bybit_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Bybit Service Unavailable")

    binance_client = httpx.AsyncClient(transport=httpx.MockTransport(binance_handler))
    bybit_client = httpx.AsyncClient(transport=httpx.MockTransport(bybit_handler))

    collectors = {
        EventSource.BINANCE: BinanceCollector(client=binance_client),
        EventSource.BYBIT: BybitCollector(client=bybit_client),
    }
    normalizers = {
        EventSource.BINANCE: BinanceNormalizer(),
        EventSource.BYBIT: BybitNormalizer(),
    }
    publisher = _FakeRedisPublisher()

    pipeline = MultiSourceIngestionPipeline(
        collectors=collectors,
        normalizers=normalizers,
        publisher=publisher,
    )

    targets = [
        SourceTarget(source=EventSource.BINANCE, market_type=MarketType.SPOT, symbol="BTCUSDT", asset="BTC"),
        SourceTarget(source=EventSource.BYBIT, market_type=MarketType.FUTURES, symbol="BTCUSDT", asset="BTC"),
    ]

    results = await pipeline.ingest_all(targets)

    assert len(results) == 2
    # Target 0: Binance succeeded
    assert results[0][3] is None
    assert results[0][1] is not None
    # Target 1: Bybit failed but did not crash the pipeline
    assert results[1][3] is not None
    assert results[1][1] is None

    assert len(publisher.published) == 1
    assert publisher.published[0].source == EventSource.BINANCE

    await pipeline.close()


@pytest.mark.asyncio
async def test_multi_source_pipeline_ingest_bulk_all():
    binance_spot_list = [
        {"symbol": "BTCUSDT", "lastPrice": "65000", "bidPrice": "64999", "askPrice": "65001", "volume": "100", "closeTime": 1724673600000},
        {"symbol": "ETHUSDT", "lastPrice": "3500", "bidPrice": "3499", "askPrice": "3501", "volume": "50", "closeTime": 1724673600000},
    ]
    bybit_fut_list = [
        {"symbol": "BTCUSDT", "lastPrice": "65200", "bid1Price": "65199", "ask1Price": "65201", "volume24h": "300", "fundingRate": "0.0001"},
        {"symbol": "ETHUSDT", "lastPrice": "3510", "bid1Price": "3509", "ask1Price": "3511", "volume24h": "150", "fundingRate": "0.0002"},
    ]

    def binance_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=binance_spot_list)

    def bybit_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"retCode": 0, "result": {"list": bybit_fut_list}, "time": 1724673600000})

    binance_client = httpx.AsyncClient(transport=httpx.MockTransport(binance_handler))
    bybit_client = httpx.AsyncClient(transport=httpx.MockTransport(bybit_handler))

    collectors = {
        EventSource.BINANCE: BinanceCollector(client=binance_client),
        EventSource.BYBIT: BybitCollector(client=bybit_client),
    }
    normalizers = {
        EventSource.BINANCE: BinanceNormalizer(),
        EventSource.BYBIT: BybitNormalizer(),
    }
    publisher = _FakeRedisPublisher()

    pipeline = MultiSourceIngestionPipeline(
        collectors=collectors,
        normalizers=normalizers,
        publisher=publisher,
    )

    total_raw, total_norm, msg_ids = await pipeline.ingest_bulk_all(quote_currency="USDT")

    assert total_raw >= 4
    assert total_norm >= 4
    assert len(msg_ids) == total_norm
    assert len(publisher.published) == total_norm

    symbols = {e.symbol for e in publisher.published}
    assert "BTCUSDT" in symbols
    assert "ETHUSDT" in symbols

    await pipeline.close()

