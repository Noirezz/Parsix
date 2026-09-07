"""Unit tests for DexScreenerCollector and DexNormalizer."""

from __future__ import annotations

from decimal import Decimal
import pytest
import httpx

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import RawEvent
from made_core.ingestion.dex_collector import DexCollectorConfig, DexScreenerCollector
from made_core.ingestion.dex_normalizer import DexNormalizer
from made_core.ingestion.normalizer import NormalizerError


@pytest.fixture
def sample_dexscreener_response() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "pairs": [
            {
                "chainId": "solana",
                "dexId": "raydium",
                "url": "https://dexscreener.com/solana/58o1b9q5wpwfwturfuk8h8uydg58j",
                "pairAddress": "58o1b9q5wpwfwturfuk8h8uydg58j",
                "baseToken": {"address": "So11111111111111111111111111111111111111112", "name": "Wrapped SOL", "symbol": "SOL"},
                "quoteToken": {"address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "name": "USD Coin", "symbol": "USDC"},
                "priceNative": "135.5",
                "priceUsd": "135.50",
                "volume": {"h24": 15000000.0},
                "liquidity": {"usd": 5000000.0, "base": 36900.0, "quote": 5000000.0},
            },
            {
                "chainId": "solana",
                "dexId": "orca",
                "url": "https://dexscreener.com/solana/orca_low_liq",
                "pairAddress": "orca_low_liq",
                "baseToken": {"symbol": "SOL"},
                "quoteToken": {"symbol": "USDT"},
                "priceUsd": "135.40",
                "liquidity": {"usd": 500.0}, # Low liquidity -> filtered out
            },
        ],
    }


@pytest.mark.asyncio
async def test_dex_collector_fetches_and_selects_highest_liquidity_pool(sample_dexscreener_response):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "SOL/USDT" in str(request.url) or "SOL" in str(request.url)
        return httpx.Response(200, json=sample_dexscreener_response)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    collector = DexScreenerCollector(config=DexCollectorConfig(min_liquidity_usd=1000.0), client=client)

    raw_event = await collector.fetch_dex_ticker("SOL", "USDT")
    assert raw_event is not None
    assert raw_event.source == EventSource.RAYDIUM
    assert raw_event.payload["symbol"] == "SOLUSDT"
    assert raw_event.payload["lastPrice"] == "135.50"
    assert raw_event.payload["dexId"] == "raydium"
    assert raw_event.metadata["market_type"] == MarketType.DEX.value
    assert raw_event.metadata["liquidity_usd"] == "5000000.0"


@pytest.mark.asyncio
async def test_dex_collector_returns_none_when_no_liquid_pairs():
    empty_resp = {"schemaVersion": "1.0.0", "pairs": []}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=empty_resp)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    collector = DexScreenerCollector(client=client)

    raw_event = await collector.fetch_dex_ticker("UNKNOWNCOIN", "USDT")
    assert raw_event is None


def test_dex_normalizer_valid_payload():
    normalizer = DexNormalizer()
    raw = RawEvent(
        timestamp="2026-08-31T12:00:00Z",
        event_id="raw:dex:raydium:SOLUSDT:1",
        source=EventSource.RAYDIUM,
        payload={
            "symbol": "SOLUSDT",
            "lastPrice": "135.50",
            "bidPrice": "135.43",
            "askPrice": "135.57",
            "volume": "1500000.0",
            "dexId": "raydium",
            "chainId": "solana",
            "url": "https://dexscreener.com/solana/123",
            "liquidityUsd": "5000000",
        },
        metadata={"asset": "SOL", "symbol": "SOLUSDT", "market_type": "DEX"},
    )

    norm = normalizer.normalize(raw)
    assert norm.market_type == MarketType.DEX
    assert norm.asset == "SOL"
    assert norm.symbol == "SOLUSDT"
    assert norm.price == Decimal("135.50")
    assert norm.bid == Decimal("135.43")
    assert norm.ask == Decimal("135.57")
    assert norm.volume == Decimal("1500000.0")
    assert norm.metadata["dex"] == "raydium"
    assert norm.metadata["chain"] == "solana"
    assert norm.metadata["pair_url"] == "https://dexscreener.com/solana/123"


def test_dex_normalizer_invalid_payload_raises_error():
    normalizer = DexNormalizer()
    raw = RawEvent(
        timestamp="2026-08-31T12:00:00Z",
        event_id="raw:dex:invalid:1",
        source=EventSource.UNISWAP,
        payload={"symbol": "SOLUSDT", "lastPrice": "invalid_price"},
        metadata={},
    )
    with pytest.raises(NormalizerError):
        normalizer.normalize(raw)
