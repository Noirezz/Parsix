"""Ingestion pipelines coordinating Collectors, Normalizers, and Redis Publisher."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.ingestion.collector import BinanceCollector, BybitCollector
from made_core.ingestion.dex_collector import DexScreenerCollector
from made_core.ingestion.dex_normalizer import DexNormalizer
from made_core.ingestion.normalizer import BinanceNormalizer, BybitNormalizer
from made_core.ingestion.publisher import RedisEventPublisher

logger = logging.getLogger(__name__)

DEX_POPULAR_ASSETS = (
    "BTC", "ETH", "SOL", "BNB", "DOGE", "XRP", "ADA", "AVAX", "LINK", "SUI",
    "PEPE", "WIF", "NEAR", "APT", "ARB", "OP", "UNI", "RENDER", "FET", "INJ",
    "TIA", "SEI", "JUP", "RAY", "AAVE", "LDO", "ENA", "PENDLE", "ONDO", "TON",
)


@dataclass(frozen=True, slots=True)
class SourceTarget:
    """Target definition for market data ingestion."""

    source: EventSource
    market_type: MarketType
    symbol: str
    asset: str


class MultiSourceIngestionPipeline:
    """Coordinates concurrent ingestion across multiple exchanges, DEXes, and market types."""

    def __init__(
        self,
        collectors: dict[EventSource, Any] | None = None,
        normalizers: dict[EventSource, Any] | None = None,
        publisher: RedisEventPublisher | None = None,
    ) -> None:
        self._collectors = collectors or {
            EventSource.BINANCE: BinanceCollector(),
            EventSource.BYBIT: BybitCollector(),
            EventSource.DEXSCREENER: DexScreenerCollector(),
        }
        self._normalizers = normalizers or {
            EventSource.BINANCE: BinanceNormalizer(),
            EventSource.BYBIT: BybitNormalizer(),
            EventSource.DEXSCREENER: DexNormalizer(),
            EventSource.UNISWAP: DexNormalizer(),
            EventSource.RAYDIUM: DexNormalizer(),
            EventSource.PANCAKESWAP: DexNormalizer(),
            EventSource.AERODROME: DexNormalizer(),
        }
        self._publisher = publisher or RedisEventPublisher()

    async def ingest_single(
        self,
        target: SourceTarget,
    ) -> tuple[RawEvent, NormalizedEvent, str]:
        """Collect, normalize, and publish market data for a single target."""
        collector = self._collectors.get(target.source)
        if collector is None:
            raise ValueError(f"No collector configured for source {target.source.value}")

        normalizer = self._normalizers.get(target.source)
        if normalizer is None:
            raise ValueError(f"No normalizer configured for source {target.source.value}")

        # 1. Collect raw market data
        raw_event = await collector.collect(
            symbol=target.symbol,
            asset=target.asset,
            market_type=target.market_type,
        )

        # 2. Normalize raw payload
        normalized_event = normalizer.normalize(raw_event)

        # 3. Publish to Redis Streams
        msg_id = await self._publisher.publish(normalized_event)

        logger.info(
            "Ingested %s %s %s -> Redis message %s (price=%s, bid=%s, ask=%s)",
            target.source.value,
            target.market_type.value,
            target.symbol,
            msg_id,
            normalized_event.price,
            normalized_event.bid,
            normalized_event.ask,
        )
        return raw_event, normalized_event, msg_id

    async def _safe_ingest_single(
        self,
        target: SourceTarget,
    ) -> tuple[RawEvent | None, NormalizedEvent | None, str | None, Exception | None]:
        """Execute ingest_single with error isolation."""
        try:
            raw, norm, msg_id = await self.ingest_single(target)
            return raw, norm, msg_id, None
        except Exception as exc:
            logger.error(
                "Ingestion failed for target %s %s %s: %s",
                target.source.value,
                target.market_type.value,
                target.symbol,
                exc,
            )
            return None, None, None, exc

    async def ingest_all(
        self,
        targets: Sequence[SourceTarget],
    ) -> list[tuple[RawEvent | None, NormalizedEvent | None, str | None, Exception | None]]:
        """Concurrently ingest market data for all specified targets with failure isolation."""
        tasks = [self._safe_ingest_single(target) for target in targets]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def ingest_bulk_all(
        self,
        quote_currency: str = "USDT",
        dex_assets: Sequence[str] | None = None,
    ) -> tuple[int, int, list[str]]:
        """Collect all available tickers across all configured exchanges and DEXes, normalize in batch, and publish via pipeline."""
        binance_col: Any = self._collectors.get(EventSource.BINANCE)
        bybit_col: Any = self._collectors.get(EventSource.BYBIT)
        dex_col: Any = self._collectors.get(EventSource.DEXSCREENER)

        binance_norm: Any = self._normalizers.get(EventSource.BINANCE)
        bybit_norm: Any = self._normalizers.get(EventSource.BYBIT)
        dex_norm: Any = self._normalizers.get(EventSource.DEXSCREENER) or DexNormalizer()

        collect_tasks = []
        if binance_col and hasattr(binance_col, "collect_all"):
            collect_tasks.append(binance_col.collect_all(market_type=MarketType.SPOT, quote_currency=quote_currency))
            collect_tasks.append(binance_col.collect_all(market_type=MarketType.FUTURES, quote_currency=quote_currency))
        if bybit_col and hasattr(bybit_col, "collect_all"):
            collect_tasks.append(bybit_col.collect_all(market_type=MarketType.SPOT, quote_currency=quote_currency))
            collect_tasks.append(bybit_col.collect_all(market_type=MarketType.FUTURES, quote_currency=quote_currency))
        if dex_col and hasattr(dex_col, "fetch_bulk_dex_tickers"):
            collect_tasks.append(dex_col.fetch_bulk_dex_tickers(dex_assets or DEX_POPULAR_ASSETS, quote_currency=quote_currency))

        if not collect_tasks:
            return 0, 0, []

        collected_results = await asyncio.gather(*collect_tasks, return_exceptions=True)

        all_normalized: list[NormalizedEvent] = []
        total_raw = 0

        for res in collected_results:
            if isinstance(res, Exception):
                logger.error("Bulk collection task error: %s", res)
                continue
            if not isinstance(res, list):
                continue
            total_raw += len(res)
            if not res:
                continue
            source = res[0].source
            if source == EventSource.BINANCE and binance_norm:
                if hasattr(binance_norm, "normalize_batch"):
                    all_normalized.extend(binance_norm.normalize_batch(res))
                else:
                    for r in res:
                        try:
                            all_normalized.append(binance_norm.normalize(r))
                        except Exception:
                            pass
            elif source == EventSource.BYBIT and bybit_norm:
                if hasattr(bybit_norm, "normalize_batch"):
                    all_normalized.extend(bybit_norm.normalize_batch(res))
                else:
                    for r in res:
                        try:
                            all_normalized.append(bybit_norm.normalize(r))
                        except Exception:
                            pass
            elif source in (
                EventSource.DEXSCREENER,
                EventSource.UNISWAP,
                EventSource.RAYDIUM,
                EventSource.PANCAKESWAP,
                EventSource.AERODROME,
            ):
                for r in res:
                    try:
                        all_normalized.append(dex_norm.normalize(r))
                    except Exception:
                        pass

        msg_ids = await self._publisher.publish_batch(all_normalized)
        logger.info(
            "Bulk ingestion cycle: collected %d raw tickers, normalized %d events, published %d to Redis Streams",
            total_raw,
            len(all_normalized),
            len(msg_ids),
        )
        return total_raw, len(all_normalized), msg_ids

    async def close(self) -> None:
        """Close all collector and publisher resources."""
        for collector in self._collectors.values():
            if hasattr(collector, "close") and callable(collector.close):
                await collector.close()
        await self._publisher.close()

    async def __aenter__(self) -> MultiSourceIngestionPipeline:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class IngestionPipeline:
    """Backward-compatible single-source IngestionPipeline for Binance."""

    def __init__(
        self,
        collector: BinanceCollector,
        normalizer: BinanceNormalizer,
        publisher: RedisEventPublisher,
    ) -> None:
        self._collector = collector
        self._normalizer = normalizer
        self._publisher = publisher

    async def ingest(
        self,
        symbol: str,
        asset: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> tuple[RawEvent, NormalizedEvent, str]:
        """Collect, normalize, and publish market data for a symbol."""
        raw_event = await self._collector.collect(symbol=symbol, asset=asset, market_type=market_type)
        normalized_event = self._normalizer.normalize(raw_event)
        msg_id = await self._publisher.publish(normalized_event)

        logger.info(
            "Ingested %s %s -> Redis message %s (price=%s, bid=%s, ask=%s)",
            market_type.value,
            symbol,
            msg_id,
            normalized_event.price,
            normalized_event.bid,
            normalized_event.ask,
        )
        return raw_event, normalized_event, msg_id

    async def close(self) -> None:
        """Close collector and publisher resources."""
        await self._collector.close()
        await self._publisher.close()

    async def __aenter__(self) -> IngestionPipeline:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
