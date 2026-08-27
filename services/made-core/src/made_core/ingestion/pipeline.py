"""Ingestion pipeline coordinating Collector, Normalizer, and Redis Publisher."""

from __future__ import annotations

import logging
from typing import Any

from made_core.domain.enums import MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.ingestion.collector import BinanceCollector
from made_core.ingestion.normalizer import BinanceNormalizer
from made_core.ingestion.publisher import RedisEventPublisher

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Coordinates fetching from external exchange, normalizing payload, and publishing to Redis Streams."""

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
        # 1. Collect raw market data
        raw_event = await self._collector.collect(symbol=symbol, asset=asset, market_type=market_type)

        # 2. Normalize raw payload
        normalized_event = self._normalizer.normalize(raw_event)

        # 3. Publish to Redis Streams
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
