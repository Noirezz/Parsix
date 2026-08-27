"""External market data collector for Binance and other exchanges."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import RawEvent

logger = logging.getLogger(__name__)


class CollectorConfig(BaseModel):
    """Configuration settings for exchange market data collector."""

    base_url: str = "https://api.binance.com"
    timeout_seconds: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0)


class CollectorError(Exception):
    """Base exception for market data collection failures."""


class BinanceCollector:
    """Asynchronously collects raw market data tickers from Binance REST APIs."""

    def __init__(
        self,
        config: CollectorConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or CollectorConfig()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._config.timeout_seconds)
        return self._client

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch 24hr / book ticker data for a symbol from Binance with retries."""
        client = await self._get_client()
        url = f"{self._config.base_url.rstrip('/')}/api/v3/ticker/24hr"
        params = {"symbol": symbol.upper()}

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    return response.json()

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self._config.max_retries:
                        delay = self._config.retry_base_delay_seconds * (2**attempt)
                        logger.warning(
                            "Binance API HTTP %d for %s. Retrying in %.2fs (attempt %d/%d)",
                            response.status_code,
                            symbol,
                            delay,
                            attempt + 1,
                            self._config.max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue

                raise CollectorError(
                    f"Binance API request failed with HTTP {response.status_code}: {response.text}"
                )

            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    logger.warning(
                        "Network error connecting to Binance for %s (%s). Retrying in %.2fs (attempt %d/%d)",
                        symbol,
                        exc,
                        delay,
                        attempt + 1,
                        self._config.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

                raise CollectorError(f"Network error collecting Binance data for {symbol}: {exc}") from exc

        raise CollectorError(f"Failed to collect Binance data for {symbol} after {self._config.max_retries} retries")

    async def collect(
        self,
        symbol: str,
        asset: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> RawEvent:
        """Collect market data and package into a canonical RawEvent."""
        payload = await self.fetch_ticker(symbol)
        now = datetime.now(UTC)
        event_id = f"raw:binance:{symbol.upper()}:{int(now.timestamp() * 1000)}:{uuid4().hex[:6]}"

        return RawEvent(
            event_id=event_id,
            timestamp=now,
            source=EventSource.BINANCE,
            payload=payload,
            metadata={
                "asset": asset.upper(),
                "symbol": symbol.upper(),
                "market_type": market_type.value,
            },
        )

    async def close(self) -> None:
        """Close HTTP client resources if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BinanceCollector:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
