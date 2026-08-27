"""Redis Streams consumer adapter for MADE Core."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis
from pydantic import ValidationError

from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
fromメイド_pipeline = None
from made_core.application.pipeline import EventPipeline
from made_core.domain.models import Alert, NormalizedEvent, PipelineExecutionResult
from made_core.infrastructure.config import InfrastructureConfig

logger = logging.getLogger(__name__)


class RedisStreamConsumer:
    """Consumes normalized events from Redis Streams, invokes Core pipelines, and manages ACKs/DLQ."""

    def __init__(
        self,
        event_pipeline: EventPipeline,
        anomaly_pipeline: AnomalyProcessingPipeline,
        config: InfrastructureConfig | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        self._event_pipeline = event_pipeline
        self._anomaly_pipeline = anomaly_pipeline
        self._config = config or InfrastructureConfig()
        self._redis = redis_client
        self._owns_redis = redis_client is None
        self._running = False

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._config.get_redis_url(),
                decode_responses=False,
            )
        return self._redis

    async def initialize(self) -> None:
        """Initialize Redis connection and ensure consumer group exists."""
        r = await self._get_redis()
        try:
            await r.xgroup_create(
                name=self._config.input_stream,
                groupname=self._config.consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Created Redis consumer group '%s' on stream '%s'",
                self._config.consumer_group,
                self._config.input_stream,
            )
        except Exception as exc:
            # BUSYGROUP error code indicates group already exists, which is safe to ignore
            err_msg = str(exc)
            if "BUSYGROUP" in err_msg or "already exists" in err_msg:
                logger.debug(
                    "Consumer group '%s' already exists on stream '%s'",
                    self._config.consumer_group,
                    self._config.input_stream,
                )
            else:
                logger.error("Failed to initialize consumer group: %s", exc)
                raise

    def deserialize_message(self, message_data: dict[bytes | str, Any]) -> NormalizedEvent:
        """Deserialize a Redis stream message payload into a NormalizedEvent."""
        # Convert any byte keys to string
        str_data: dict[str, Any] = {}
        for k, v in message_data.items():
            key_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            str_data[key_str] = v

        # Check if the payload is wrapped in a 'payload' or 'data' field
        payload_raw = str_data.get("payload") or str_data.get("data")
        if payload_raw is not None:
            if isinstance(payload_raw, bytes):
                payload_str = payload_raw.decode("utf-8")
            else:
                payload_str = str(payload_raw)
            return NormalizedEvent.model_validate_json(payload_str)

        # Otherwise decode individual dictionary values
        decoded_dict: dict[str, Any] = {}
        for k, v in str_data.items():
            if isinstance(v, bytes):
                try:
                    val_str = v.decode("utf-8")
                    # Try json parse if it looks like a dict/list
                    if val_str.startswith("{") or val_str.startswith("["):
                        try:
                            decoded_dict[k] = json.loads(val_str)
                        except json.JSONDecodeError:
                            decoded_dict[k] = val_str
                    else:
                        decoded_dict[k] = val_str
                except UnicodeDecodeError:
                    decoded_dict[k] = v
            else:
                decoded_dict[k] = v

        return NormalizedEvent.model_validate(decoded_dict)

    async def handle_message(
        self,
        message_id: str | bytes,
        raw_data: dict[bytes | str, Any],
    ) -> tuple[PipelineExecutionResult | None, Alert | None]:
        """Process one Redis message through deserialization, Core execution, and ACK/DLQ."""
        r = await self._get_redis()
        msg_id_str = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)

        try:
            event = self.deserialize_message(raw_data)
        except (json.JSONDecodeError, ValidationError, KeyError, ValueError, TypeError) as err:
            logger.warning("Malformed message %s rejected: %s", msg_id_str, err)
            # Publish to Dead Letter Stream
            dlq_payload = {
                "error": str(err),
                "originalMessageId": msg_id_str,
                "rawPayload": str(raw_data),
            }
            await r.xadd(self._config.dead_letter_stream, dlq_payload)
            # Acknowledge original message to unblock the consumer stream
            await r.xack(self._config.input_stream, self._config.consumer_group, message_id)
            return None, None

        # Execute Core pipelines
        pipeline_result = self._event_pipeline.process_event(event)
        alert = self._anomaly_pipeline.process_pipeline_result(pipeline_result)

        # Acknowledge successfully processed message
        await r.xack(self._config.input_stream, self._config.consumer_group, message_id)
        return pipeline_result, alert

    async def read_batch(self) -> list[tuple[str, dict[Any, Any]]]:
        """Read a batch of messages from Redis Streams using the configured consumer group."""
        r = await self._get_redis()
        streams_arg = {self._config.input_stream: ">"}
        try:
            response = await r.xreadgroup(
                groupname=self._config.consumer_group,
                consumername=self._config.consumer_name,
                streams=streams_arg,
                count=self._config.batch_size,
                block=self._config.block_timeout_ms,
            )
        except Exception as exc:
            logger.error("Error reading from Redis Stream: %s", exc)
            raise

        if not response:
            return []

        messages: list[tuple[str, dict[Any, Any]]] = []
        for stream_name, msg_list in response:
            for msg_id, data in msg_list:
                msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
                messages.append((msg_id_str, data))

        return messages

    async def claim_stale_messages(self, min_idle_ms: int | None = None) -> list[tuple[str, dict[Any, Any]]]:
        """Claim unacknowledged stale messages from the PEL using XAUTOCLAIM."""
        r = await self._get_redis()
        idle_time = min_idle_ms if min_idle_ms is not None else self._config.pel_claim_min_idle_ms
        try:
            response = await r.xautoclaim(
                name=self._config.input_stream,
                groupname=self._config.consumer_group,
                consumername=self._config.consumer_name,
                min_idle_time=idle_time,
                start_id="0-0",
                count=self._config.pel_claim_batch_size,
            )
        except Exception as exc:
            logger.warning("Error running XAUTOCLAIM on stream %s: %s", self._config.input_stream, exc)
            return []

        if not response or len(response) < 2:
            return []

        claimed_raw = response[1]
        messages: list[tuple[str, dict[Any, Any]]] = []
        for msg_id, data in claimed_raw:
            if data:
                msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
                messages.append((msg_id_str, data))

        if messages:
            logger.info("Reclaimed %d stale message(s) from PEL on stream %s", len(messages), self._config.input_stream)

        return messages

    async def process_one_batch(self) -> list[tuple[PipelineExecutionResult | None, Alert | None]]:

        """Read and process a single batch of messages."""
        messages = await self.read_batch()
        results: list[tuple[PipelineExecutionResult | None, Alert | None]] = []
        for msg_id, data in messages:
            res = await self.handle_message(msg_id, data)
            results.append(res)
        return results

    async def run(self, max_iterations: int | None = None) -> None:
        """Run the main consumption loop until stopped or max_iterations reached."""
        await self.initialize()
        self._running = True
        iterations = 0
        try:
            while self._running:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                await self.process_one_batch()
                iterations += 1
        finally:
            self._running = False

    def stop(self) -> None:
        """Request graceful shutdown of the consumption loop."""
        self._running = False

    async def close(self) -> None:
        """Close the Redis client connection if owned by this consumer."""
        self.stop()
        if self._owns_redis and self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def __aenter__(self) -> RedisStreamConsumer:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
