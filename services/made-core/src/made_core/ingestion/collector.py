"""External market data collectors for Binance and Bybit exchanges."""

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
    """Configuration settings for Binance market data collector."""

    base_url: str = "https://api.binance.com"
    futures_base_url: str = "https://fapi.binance.com"
    timeout_seconds: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0)


class BybitCollectorConfig(BaseModel):
    """Configuration settings for Bybit market data collector."""

    base_url: str = "https://api.bybit.com"
    timeout_seconds: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0)


class CollectorError(Exception):
    """Base exception for market data collection failures."""


class BinanceCollector:
    """Asynchronously collects raw market data tickers from Binance Spot and Futures REST APIs."""

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

    async def fetch_ticker(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> dict[str, Any]:
        """Fetch 24hr ticker data for a symbol from Binance Spot or Futures with retries."""
        client = await self._get_client()
        if market_type is MarketType.FUTURES:
            url = f"{self._config.futures_base_url.rstrip('/')}/fapi/v1/ticker/24hr"
        else:
            url = f"{self._config.base_url.rstrip('/')}/api/v3/ticker/24hr"
        params = {"symbol": symbol.upper()}

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if market_type is MarketType.FUTURES and ("bidPrice" not in data or "askPrice" not in data):
                        try:
                            book_url = f"{self._config.futures_base_url.rstrip('/')}/fapi/v1/ticker/bookTicker"
                            book_resp = await client.get(book_url, params=params)
                            if book_resp.status_code == 200:
                                book_data = book_resp.json()
                                if "bidPrice" in book_data:
                                    data["bidPrice"] = book_data["bidPrice"]
                                if "askPrice" in book_data:
                                    data["askPrice"] = book_data["askPrice"]
                        except Exception:
                            pass
                    return data

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self._config.max_retries:
                        delay = self._config.retry_base_delay_seconds * (2**attempt)
                        logger.warning(
                            "Binance API HTTP %d for %s (%s). Retrying in %.2fs (attempt %d/%d)",
                            response.status_code,
                            symbol,
                            market_type.value,
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

    async def fetch_funding_rate(self, symbol: str) -> str | None:
        """Fetch the latest funding rate for a USDⓈ-M Futures symbol from Binance."""
        client = await self._get_client()
        url = f"{self._config.futures_base_url.rstrip('/')}/fapi/v1/premiumIndex"
        params = {"symbol": symbol.upper()}

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("lastFundingRate")

                if response.status_code in (429, 500, 502, 503, 504) and attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

                logger.warning(
                    "Binance premiumIndex API failed with HTTP %d for %s",
                    response.status_code,
                    symbol,
                )
                return None
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                logger.warning("Network error fetching Binance funding rate for %s: %s", symbol, exc)
                return None

        return None

    async def collect(
        self,
        symbol: str,
        asset: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> RawEvent:
        """Collect market data and package into a canonical RawEvent."""
        payload = await self.fetch_ticker(symbol, market_type=market_type)
        if market_type is MarketType.FUTURES:
            funding_rate = await self.fetch_funding_rate(symbol)
            if funding_rate is not None:
                payload["fundingRate"] = funding_rate

        now = datetime.now(UTC)
        event_id = f"raw:binance:{symbol.upper()}:{market_type.value.lower()}:{int(now.timestamp() * 1000)}:{uuid4().hex[:6]}"

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

    async def fetch_all_tickers(
        self,
        market_type: MarketType = MarketType.SPOT,
    ) -> list[dict[str, Any]]:
        """Fetch all 24hr tickers in bulk in a single HTTP request."""
        client = await self._get_client()
        if market_type is MarketType.FUTURES:
            url = f"{self._config.futures_base_url.rstrip('/')}/fapi/v1/ticker/24hr"
        else:
            url = f"{self._config.base_url.rstrip('/')}/api/v3/ticker/24hr"

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    return []
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise CollectorError(f"Binance bulk ticker failed: HTTP {response.status_code}")
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise CollectorError(f"Network error fetching bulk Binance tickers: {exc}") from exc
        return []

    async def fetch_all_funding_rates(self) -> dict[str, str]:
        """Fetch all latest funding rates in bulk for Binance USD-M Futures."""
        client = await self._get_client()
        url = f"{self._config.futures_base_url.rstrip('/')}/fapi/v1/premiumIndex"
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return {item["symbol"]: item.get("lastFundingRate", "0") for item in data if "symbol" in item}
                    return {}
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                return {}
            except Exception:
                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_base_delay_seconds)
                    continue
                return {}
        return {}

    async def collect_all(
        self,
        market_type: MarketType = MarketType.SPOT,
        quote_currency: str = "USDT",
    ) -> list[RawEvent]:
        """Collect all active tickers for a market type and package into RawEvent instances."""
        tickers = await self.fetch_all_tickers(market_type=market_type)
        funding_map: dict[str, str] = {}
        if market_type is MarketType.FUTURES:
            funding_map = await self.fetch_all_funding_rates()

        now = datetime.now(UTC)
        ts_ms = int(now.timestamp() * 1000)
        events: list[RawEvent] = []

        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith(quote_currency.upper()):
                continue
            base_asset = sym[: -len(quote_currency)].upper()
            if not base_asset:
                continue

            payload = dict(t)
            if market_type is MarketType.FUTURES and sym in funding_map:
                payload["fundingRate"] = funding_map[sym]

            event_id = f"raw:binance:{sym}:{market_type.value.lower()}:{ts_ms}:{uuid4().hex[:6]}"
            events.append(
                RawEvent(
                    event_id=event_id,
                    timestamp=now,
                    source=EventSource.BINANCE,
                    payload=payload,
                    metadata={
                        "asset": base_asset,
                        "symbol": sym,
                        "market_type": market_type.value,
                    },
                )
            )
        return events

    async def close(self) -> None:
        """Close HTTP client resources if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BinanceCollector:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class BybitCollector:
    """Asynchronously collects raw market data tickers from Bybit V5 REST APIs (Spot and Linear)."""

    def __init__(
        self,
        config: BybitCollectorConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or BybitCollectorConfig()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._config.timeout_seconds)
        return self._client

    async def fetch_ticker(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> dict[str, Any]:
        """Fetch ticker data for a symbol from Bybit V5 public market tickers."""
        client = await self._get_client()
        url = f"{self._config.base_url.rstrip('/')}/v5/market/tickers"
        category = "spot" if market_type is MarketType.SPOT else "linear"
        params = {"category": category, "symbol": symbol.upper()}

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("retCode") != 0:
                        raise CollectorError(
                            f"Bybit API error code {data.get('retCode')}: {data.get('retMsg')}"
                        )
                    result_list = data.get("result", {}).get("list", [])
                    if not result_list:
                        raise CollectorError(
                            f"No Bybit ticker returned for symbol {symbol} ({category})"
                        )
                    ticker = result_list[0]
                    # Include server timestamp from root response
                    ticker["serverTime"] = data.get("time")
                    return ticker

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self._config.max_retries:
                        delay = self._config.retry_base_delay_seconds * (2**attempt)
                        logger.warning(
                            "Bybit API HTTP %d for %s (%s). Retrying in %.2fs (attempt %d/%d)",
                            response.status_code,
                            symbol,
                            market_type.value,
                            delay,
                            attempt + 1,
                            self._config.max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue

                raise CollectorError(
                    f"Bybit API request failed with HTTP {response.status_code}: {response.text}"
                )

            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    logger.warning(
                        "Network error connecting to Bybit for %s (%s). Retrying in %.2fs (attempt %d/%d)",
                        symbol,
                        exc,
                        delay,
                        attempt + 1,
                        self._config.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

                raise CollectorError(f"Network error collecting Bybit data for {symbol}: {exc}") from exc

        raise CollectorError(f"Failed to collect Bybit data for {symbol} after {self._config.max_retries} retries")

    async def collect(
        self,
        symbol: str,
        asset: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> RawEvent:
        """Collect market data from Bybit and package into a canonical RawEvent."""
        payload = await self.fetch_ticker(symbol, market_type=market_type)
        now = datetime.now(UTC)
        event_id = f"raw:bybit:{symbol.upper()}:{market_type.value.lower()}:{int(now.timestamp() * 1000)}:{uuid4().hex[:6]}"

        return RawEvent(
            event_id=event_id,
            timestamp=now,
            source=EventSource.BYBIT,
            payload=payload,
            metadata={
                "asset": asset.upper(),
                "symbol": symbol.upper(),
                "market_type": market_type.value,
            },
        )

    async def fetch_all_tickers(
        self,
        market_type: MarketType = MarketType.SPOT,
    ) -> list[dict[str, Any]]:
        """Fetch all tickers in bulk from Bybit V5 in a single HTTP request."""
        client = await self._get_client()
        url = f"{self._config.base_url.rstrip('/')}/v5/market/tickers"
        category = "spot" if market_type is MarketType.SPOT else "linear"
        params = {"category": category}

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("retCode") != 0:
                        raise CollectorError(f"Bybit API error {data.get('retCode')}: {data.get('retMsg')}")
                    result_list = data.get("result", {}).get("list", [])
                    server_time = data.get("time")
                    for item in result_list:
                        item["serverTime"] = server_time
                    return result_list
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise CollectorError(f"Bybit bulk tickers failed: HTTP {response.status_code}")
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise CollectorError(f"Network error fetching bulk Bybit tickers: {exc}") from exc
        return []

    async def collect_all(
        self,
        market_type: MarketType = MarketType.SPOT,
        quote_currency: str = "USDT",
    ) -> list[RawEvent]:
        """Collect all active tickers for a market type from Bybit and package into RawEvent instances."""
        tickers = await self.fetch_all_tickers(market_type=market_type)
        now = datetime.now(UTC)
        ts_ms = int(now.timestamp() * 1000)
        events: list[RawEvent] = []

        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith(quote_currency.upper()):
                continue
            base_asset = sym[: -len(quote_currency)].upper()
            if not base_asset:
                continue

            event_id = f"raw:bybit:{sym}:{market_type.value.lower()}:{ts_ms}:{uuid4().hex[:6]}"
            events.append(
                RawEvent(
                    event_id=event_id,
                    timestamp=now,
                    source=EventSource.BYBIT,
                    payload=t,
                    metadata={
                        "asset": base_asset,
                        "symbol": sym,
                        "market_type": market_type.value,
                    },
                )
            )
        return events

    async def close(self) -> None:
        """Close HTTP client resources if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BybitCollector:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
