"""Live integration test verifying public Bybit V5 Spot and Linear REST APIs."""

from __future__ import annotations

import pytest

from made_core.domain.enums import MarketType
from made_core.ingestion.collector import BybitCollector
from made_core.ingestion.normalizer import BybitNormalizer


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bybit_spot_and_linear():
    async with BybitCollector() as collector:
        normalizer = BybitNormalizer()

        # 1. Live Bybit Spot
        raw_spot = await collector.collect("BTCUSDT", "BTC", market_type=MarketType.SPOT)
        assert raw_spot.source.value == "BYBIT"
        norm_spot = normalizer.normalize(raw_spot)

        assert norm_spot.symbol == "BTCUSDT"
        assert norm_spot.asset == "BTC"
        assert norm_spot.market_type == MarketType.SPOT
        assert norm_spot.price > 0
        assert norm_spot.bid > 0
        assert norm_spot.ask > 0
        assert norm_spot.volume >= 0

        # 2. Live Bybit Linear (Futures)
        raw_fut = await collector.collect("BTCUSDT", "BTC", market_type=MarketType.FUTURES)
        assert raw_fut.source.value == "BYBIT"
        norm_fut = normalizer.normalize(raw_fut)

        assert norm_fut.symbol == "BTCUSDT"
        assert norm_fut.asset == "BTC"
        assert norm_fut.market_type == MarketType.FUTURES
        assert norm_fut.price > 0
        assert norm_fut.bid > 0
        assert norm_fut.ask > 0
        assert norm_fut.volume >= 0
