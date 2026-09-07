"""External on-chain market data collector for decentralized exchanges via DEXScreener API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Sequence
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import RawEvent

logger = logging.getLogger(__name__)


class DexCollectorConfig(BaseModel):
    """Configuration settings for DEXScreener market data collector."""

    base_url: str = "https://api.dexscreener.com"
    min_liquidity_usd: float = Field(default=10000.0, ge=0)
    timeout_seconds: float = Field(default=8.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0)


def _map_dex_to_event_source(dex_id: str | None) -> EventSource:
    """Map DEX identifier string to domain EventSource enum."""
    if not dex_id:
        return EventSource.DEXSCREENER
    d = dex_id.lower()
    if "uniswap" in d:
        return EventSource.UNISWAP
    if "raydium" in d:
        return EventSource.RAYDIUM
    if "pancake" in d:
        return EventSource.PANCAKESWAP
    if "aerodrome" in d:
        return EventSource.AERODROME
    return EventSource.DEXSCREENER


class DexScreenerCollector:
    """Asynchronously collects on-chain liquidity pool tickers across Solana and EVM chains."""

    def __init__(
        self,
        config: DexCollectorConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or DexCollectorConfig()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._config.timeout_seconds)
        return self._client

    async def fetch_dex_ticker(
        self,
        asset: str,
        quote_currency: str = "USDT",
    ) -> RawEvent | None:
        """Fetch the deepest liquidity pool for a given asset across DEXes."""
        client = await self._get_client()
        query = f"{asset.upper()}/{quote_currency.upper()}"
        url = f"{self._config.base_url.rstrip('/')}/latest/dex/search"

        data: dict[str, Any] | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url, params={"q": query})
                if response.status_code == 200:
                    data = response.json()
                    break
                logger.warning(
                    "DEXScreener API returned HTTP %d for query %s (attempt %d/%d)",
                    response.status_code,
                    query,
                    attempt + 1,
                    self._config.max_retries + 1,
                )
            except Exception as err:
                if attempt == self._config.max_retries:
                    logger.error("DEXScreener fetch error for %s after %d retries: %s", query, attempt + 1, err)
                    return None
                await asyncio.sleep(self._config.retry_base_delay_seconds * (2 ** attempt))

        if not data or not isinstance(data.get("pairs"), list) or not data["pairs"]:
            return None

        # Filter for exact base token symbol and valid quote currencies
        asset_norm = asset.strip().upper()
        allowed_quotes = {"USDT", "USDC", "USD", quote_currency.upper()}
        valid_pairs: list[dict[str, Any]] = []

        for p in data["pairs"]:
            if not isinstance(p, dict):
                continue
            base_sym = str(p.get("baseToken", {}).get("symbol") or "").strip().upper()
            quote_sym = str(p.get("quoteToken", {}).get("symbol") or "").strip().upper()
            price_usd = p.get("priceUsd")
            liquidity_usd = (p.get("liquidity") or {}).get("usd", 0) or 0

            if base_sym == asset_norm and quote_sym in allowed_quotes and price_usd is not None:
                if float(liquidity_usd) >= self._config.min_liquidity_usd:
                    valid_pairs.append(p)

        if not valid_pairs:
            return None

        # Sort by liquidity USD descending to select deepest pool
        valid_pairs.sort(key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0, reverse=True)
        best_pair = valid_pairs[0]

        price_str = str(best_pair["priceUsd"])
        price_dec = Decimal(price_str)
        bid_str = str(price_dec * Decimal("0.9995"))
        ask_str = str(price_dec * Decimal("1.0005"))

        dex_id = best_pair.get("dexId") or "dex"
        chain_id = best_pair.get("chainId") or "chain"
        pair_url = best_pair.get("url") or f"https://dexscreener.com/{chain_id}/{best_pair.get('pairAddress')}"
        liq_usd_str = str((best_pair.get("liquidity") or {}).get("usd", 0) or 0)
        source = _map_dex_to_event_source(dex_id)

        symbol = f"{asset_norm}{quote_currency.upper()}"
        ts = datetime.now(UTC)

        payload = {
            "symbol": symbol,
            "lastPrice": price_str,
            "bidPrice": bid_str,
            "askPrice": ask_str,
            "volume": str(best_pair.get("volume", {}).get("h24", 0) or 0),
            "pairAddress": best_pair.get("pairAddress"),
            "chainId": chain_id,
            "dexId": dex_id,
            "url": pair_url,
            "liquidityUsd": liq_usd_str,
        }

        metadata = {
            "symbol": symbol,
            "asset": asset_norm,
            "market_type": MarketType.DEX.value,
            "source": source.value,
            "dex": dex_id,
            "chain": chain_id,
            "pair_url": pair_url,
            "liquidity_usd": liq_usd_str,
        }

        return RawEvent(
            timestamp=ts,
            event_id=f"raw:dex:{dex_id}:{symbol}:{uuid4().hex[:8]}",
            source=source,
            payload=payload,
            metadata=metadata,
        )

    async def fetch_bulk_dex_tickers(
        self,
        assets: Sequence[str],
        quote_currency: str = "USDT",
    ) -> list[RawEvent]:
        """Fetch tickers for multiple assets concurrently."""
        tasks = [self.fetch_dex_ticker(asset, quote_currency) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid: list[RawEvent] = []
        for r in results:
            if isinstance(r, RawEvent):
                valid.append(r)
        return valid

    async def close(self) -> None:
        """Close underlying HTTP client if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
