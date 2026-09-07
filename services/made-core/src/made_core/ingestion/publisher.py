"""Redis Streams publisher for normalized market events."""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis

from made_core.domain.models import NormalizedEvent
from made_core.infrastructure.config import InfrastructureConfig

logger = logging.getLogger(__name__)


class PublisherError(Exception):
    """Exception raised when publishing to Redis Streams fails."""


class RedisEventPublisher:
    """Asynchronously publishes NormalizedEvent entities to Redis Streams."""

    def __init__(
        self,
        config: InfrastructureConfig | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self._config = config or InfrastructureConfig()
        self._redis = redis_client
        self._owns_redis = redis_client is None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._config.get_redis_url(),
                decode_responses=False,
            )
        return self._redis

    async def publish(
        self,
        event: NormalizedEvent,
        stream_name: str | None = None,
    ) -> str:
        """Publish a NormalizedEvent to the configured Redis Stream."""
        if event is None:
            raise PublisherError("event must not be None")
        if not isinstance(event, NormalizedEvent):
            raise PublisherError(f"Expected NormalizedEvent, got {type(event)}")

        r = await self._get_redis()
        target_stream = stream_name or self._config.input_stream
        json_payload = event.model_dump_json(by_alias=True)

        try:
            msg_id = await r.xadd(target_stream, {"payload": json_payload})
            msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
            logger.debug(
                "Published event %s (%s %s) to stream %s as message %s",
                event.event_id,
                event.source.value,
                event.symbol,
                target_stream,
                msg_id_str,
            )
            return msg_id_str
        except Exception as exc:
            logger.error("Failed to publish event %s to stream %s: %s", event.event_id, target_stream, exc)
            raise PublisherError(f"Failed to publish event to Redis Stream: {exc}") from exc

    async def publish_batch(
        self,
        events: Sequence[NormalizedEvent],
        stream_name: str | None = None,
    ) -> list[str]:
        """Publish a batch of NormalizedEvent instances to Redis Streams using a pipeline."""
        if not events:
            return []

        r = await self._get_redis()
        target_stream = stream_name or self._config.input_stream

        try:
            pipe = r.pipeline()
            for evt in events:
                payload = evt.model_dump_json(by_alias=True)
                pipe.xadd(target_stream, {"payload": payload})
            raw_ids = await pipe.execute()
            msg_ids = [mid.decode("utf-8") if isinstance(mid, bytes) else str(mid) for mid in raw_ids]
            logger.debug("Published batch of %d events to stream %s", len(events), target_stream)
            return msg_ids
        except Exception as exc:
            logger.error("Failed to publish batch of %d events to stream %s: %s", len(events), target_stream, exc)
            raise PublisherError(f"Failed to publish batch to Redis Stream: {exc}") from exc

    async def close(self) -> None:
        """Close the Redis client connection if owned."""
        if self._owns_redis and self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def __aenter__(self) -> RedisEventPublisher:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
