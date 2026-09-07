"""Live integration test verifying public Binance Spot and Futures REST APIs."""

from __future__ import annotations

import pytest

from made_core.domain.enums import MarketType
from made_core.ingestion.collector import BinanceCollector
from made_core.ingestion.normalizer import BinanceNormalizer


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_binance_spot_and_futures():
    async with BinanceCollector() as collector:
        normalizer = BinanceNormalizer()

        # 1. Live Binance Spot
        raw_spot = await collector.collect("BTCUSDT", "BTC", market_type=MarketType.SPOT)
        assert raw_spot.source.value == "BINANCE"
        norm_spot = normalizer.normalize(raw_spot)

        assert norm_spot.symbol == "BTCUSDT"
        assert norm_spot.asset == "BTC"
        assert norm_spot.market_type == MarketType.SPOT
        assert norm_spot.price > 0
        assert norm_spot.bid > 0
        assert norm_spot.ask > 0
        assert norm_spot.ask >= norm_spot.bid
        assert norm_spot.volume >= 0

        # 2. Live Binance USDⓈ-M Futures
        raw_fut = await collector.collect("BTCUSDT", "BTC", market_type=MarketType.FUTURES)
        assert raw_fut.source.value == "BINANCE"
        norm_fut = normalizer.normalize(raw_fut)

        assert norm_fut.symbol == "BTCUSDT"
        assert norm_fut.asset == "BTC"
        assert norm_fut.market_type == MarketType.FUTURES
        assert norm_fut.price > 0
        assert norm_fut.bid > 0
        assert norm_fut.ask > 0
        assert norm_fut.ask >= norm_fut.bid
        assert norm_fut.volume >= 0

        # Funding rate might be present for futures
        funding_rate = norm_fut.metadata.get("funding_rate")
        if funding_rate is not None:
            assert float(funding_rate) is not None
