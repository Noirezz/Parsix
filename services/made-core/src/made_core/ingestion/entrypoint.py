"""Continuous multi-source ingestion runner for MADE."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from made_core.domain.enums import EventSource, MarketType
from made_core.infrastructure.config import InfrastructureConfig
from made_core.ingestion.collector import BinanceCollector, BybitCollector
from made_core.ingestion.dex_collector import DexScreenerCollector
from made_core.ingestion.dex_normalizer import DexNormalizer
from made_core.ingestion.normalizer import BinanceNormalizer, BybitNormalizer
from made_core.ingestion.pipeline import MultiSourceIngestionPipeline, SourceTarget
from made_core.ingestion.publisher import RedisEventPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("made_core.ingestion")

DEFAULT_TARGETS = [
    SourceTarget(source=EventSource.BINANCE, market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT"),
    SourceTarget(source=EventSource.BINANCE, market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSDT"),
    SourceTarget(source=EventSource.BYBIT, market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT"),
    SourceTarget(source=EventSource.BYBIT, market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSDT"),
    SourceTarget(source=EventSource.BINANCE, market_type=MarketType.SPOT, asset="ETH", symbol="ETHUSDT"),
    SourceTarget(source=EventSource.BINANCE, market_type=MarketType.FUTURES, asset="ETH", symbol="ETHUSDT"),
    SourceTarget(source=EventSource.BYBIT, market_type=MarketType.SPOT, asset="ETH", symbol="ETHUSDT"),
    SourceTarget(source=EventSource.BYBIT, market_type=MarketType.FUTURES, asset="ETH", symbol="ETHUSDT"),
]


async def run_ingestion_loop(
    config: InfrastructureConfig | None = None,
    poll_interval_seconds: float = 2.0,
) -> None:
    """Run continuous polling and ingestion of multi-source market data."""
    cfg = config or InfrastructureConfig()
    
    binance_col = BinanceCollector()
    bybit_col = BybitCollector()
    dex_col = DexScreenerCollector()
    binance_norm = BinanceNormalizer()
    bybit_norm = BybitNormalizer()
    dex_norm = DexNormalizer()
    publisher = RedisEventPublisher(config=cfg)

    pipeline = MultiSourceIngestionPipeline(
        collectors={
            EventSource.BINANCE: binance_col,
            EventSource.BYBIT: bybit_col,
            EventSource.DEXSCREENER: dex_col,
        },
        normalizers={
            EventSource.BINANCE: binance_norm,
            EventSource.BYBIT: bybit_norm,
            EventSource.DEXSCREENER: dex_norm,
            EventSource.UNISWAP: dex_norm,
            EventSource.RAYDIUM: dex_norm,
            EventSource.PANCAKESWAP: dex_norm,
            EventSource.AERODROME: dex_norm,
        },
        publisher=publisher,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Signal handlers not implemented on Windows event loop
            pass

    logger.info("Starting MADE Multi-Source Ingestion Runner across ALL available exchange pairs (interval=%.1fs)...", poll_interval_seconds)

    try:
        while not stop_event.is_set():
            start_time = asyncio.get_event_loop().time()
            try:
                total_raw, total_norm, msg_ids = await pipeline.ingest_bulk_all(quote_currency="USDT")
                logger.info(
                    "Ingestion cycle completed: %d raw tickers collected, %d normalized events published to Redis Streams",
                    total_raw,
                    len(msg_ids),
                )
            except Exception as exc:
                logger.error("Ingestion cycle error: %s", exc)

            elapsed = asyncio.get_event_loop().time() - start_time
            sleep_time = max(0.0, poll_interval_seconds - elapsed)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("Shutting down ingestion runner...")
        await pipeline.close()
        logger.info("Ingestion runner stopped.")


def main() -> None:
    """CLI entrypoint for the ingestion runner."""
    try:
        asyncio.run(run_ingestion_loop())
    except KeyboardInterrupt:
        logger.info("Ingestion runner interrupted by user.")


if __name__ == "__main__":
    main()
