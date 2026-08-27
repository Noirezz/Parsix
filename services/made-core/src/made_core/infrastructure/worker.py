"""Infrastructure worker orchestrating Redis Streams, Core pipelines, PostgreSQL persistence, and Telegram notifications."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.pipeline import EventPipeline
from made_core.domain.enums import Priority, ValidationStatus
from made_core.domain.models import Alert, PipelineExecutionResult
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import AlertRecord
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram.notifier import (
    TelegramNotificationAdapter,
    TelegramNotificationError,
)

logger = logging.getLogger(__name__)


class MadeCoreWorker:
    """End-to-end infrastructure worker for MADE Core streaming event processing."""

    def __init__(
        self,
        consumer: RedisStreamConsumer,
        event_pipeline: EventPipeline,
        anomaly_pipeline: AnomalyProcessingPipeline,
        storage: PostgresStorageAdapter,
        telegram: TelegramNotificationAdapter,
        config: InfrastructureConfig | None = None,
    ) -> None:
        self._consumer = consumer
        self._event_pipeline = event_pipeline
        self._anomaly_pipeline = anomaly_pipeline
        self._storage = storage
        self._telegram = telegram
        self._config = config or InfrastructureConfig()
        self._running = False

    async def initialize(self) -> None:
        """Initialize consumer and storage adapters."""
        await self._consumer.initialize()
        await self._storage.create_tables()

    async def _ack_message(self, message_id: str | bytes) -> None:
        """Acknowledge a Redis stream message."""
        r = await self._consumer._get_redis()
        await r.xack(self._config.input_stream, self._config.consumer_group, message_id)

    async def _publish_dlq(self, message_id: str | bytes, raw_data: Any, error: Exception) -> None:
        """Publish malformed message to dead-letter stream."""
        r = await self._consumer._get_redis()
        msg_id_str = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)
        dlq_payload = {
            "error": str(error),
            "originalMessageId": msg_id_str,
            "rawPayload": str(raw_data),
        }
        await r.xadd(self._config.dead_letter_stream, dlq_payload)

    def _reconstruct_alert(self, record: AlertRecord) -> Alert:
        """Reconstruct an immutable domain Alert entity from an AlertRecord."""
        from datetime import UTC

        ts = record.timestamp
        if ts.tzinfo is None or ts.utcoffset() is None:
            ts = ts.replace(tzinfo=UTC)

        return Alert(
            alert_id=record.alert_id,
            timestamp=ts,
            asset=record.asset,
            priority=Priority(record.priority),
            title=record.title,
            summary=record.summary,
            anomaly_score=record.anomaly_score,
            triggered_modules=tuple(record.triggered_modules),
            details=record.details,
        )


    async def process_message(
        self,
        message_id: str | bytes,
        raw_data: dict[bytes | str, Any],
    ) -> tuple[PipelineExecutionResult | None, Alert | None]:
        """Process one Redis stream message through Core, PostgreSQL, and Telegram with strict ACK semantics."""
        msg_id_str = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)

        # 1. Deserialize message payload
        try:
            event = self._consumer.deserialize_message(raw_data)
        except (json.JSONDecodeError, ValidationError, KeyError, ValueError, TypeError) as err:
            logger.warning("Malformed message %s: %s", msg_id_str, err)
            await self._publish_dlq(message_id, raw_data, err)
            await self._ack_message(message_id)
            return None, None

        # 2. Check event idempotency & pending notifications
        try:
            if await self._storage.is_event_processed(event.event_id):
                # Event was already processed in DB. Check if Telegram notification is still pending
                pending_alert_rec = await self._storage.get_pending_alert_for_event(event.event_id)
                if pending_alert_rec is None:
                    # Event was completely processed and notified (or no alert needed)
                    logger.info("Event %s already completely processed; acknowledging message %s", event.event_id, msg_id_str)
                    await self._ack_message(message_id)
                    return None, None

                # Notification is pending/failed! Retry Telegram delivery without re-running Core
                logger.info(
                    "Event %s already in database but alert %s is %s; retrying Telegram delivery",
                    event.event_id,
                    pending_alert_rec.alert_id,
                    pending_alert_rec.notification_status,
                )
                domain_alert = self._reconstruct_alert(pending_alert_rec)
                try:
                    await self._telegram.send_alert(domain_alert)
                    await self._storage.mark_alert_sent(pending_alert_rec.alert_id)
                    await self._ack_message(message_id)
                    return None, domain_alert
                except TelegramNotificationError as tg_err:
                    logger.error("Telegram notification retry failed for alert %s: %s", pending_alert_rec.alert_id, tg_err)
                    await self._storage.mark_alert_failed(pending_alert_rec.alert_id, str(tg_err))
                    # Do NOT ACK
                    raise
        except Exception as db_err:
            if isinstance(db_err, TelegramNotificationError):
                raise
            logger.error("Database error checking idempotency for event %s: %s", event.event_id, db_err)
            raise

        # 3. New event: Execute upstream Core pipeline
        try:
            pipeline_result = self._event_pipeline.process_event(event)
        except Exception as core_err:
            logger.error("Core EventPipeline processing failure for event %s: %s", event.event_id, core_err)
            raise

        # 4. Handle invalid events
        if pipeline_result.status is not ValidationStatus.VALID:
            try:
                await self._storage.persist_processing_result(pipeline_result)
            except Exception as db_err:
                logger.error("Database error persisting invalid event %s: %s", event.event_id, db_err)
                raise
            await self._ack_message(message_id)
            return pipeline_result, None

        # 5. Execute downstream AnomalyProcessingPipeline
        try:
            alert = self._anomaly_pipeline.process_pipeline_result(pipeline_result)
        except Exception as anom_err:
            logger.error("Downstream AnomalyProcessingPipeline failure for event %s: %s", event.event_id, anom_err)
            raise

        # 6. Persist durable PostgreSQL state (atomic commit)
        try:
            await self._storage.persist_processing_result(pipeline_result, alert=alert)
        except Exception as db_err:
            logger.error("Database error persisting execution result for event %s: %s", event.event_id, db_err)
            raise

        # 7. Deliver notification if Alert exists
        if alert is not None:
            try:
                await self._telegram.send_alert(alert)
                await self._storage.mark_alert_sent(alert.alert_id)
            except TelegramNotificationError as tg_err:
                logger.error("Telegram notification failed for event %s: %s", event.event_id, tg_err)
                await self._storage.mark_alert_failed(alert.alert_id, str(tg_err))
                # Database is committed. Telegram delivery failed -> do NOT ACK automatically so failure is retried on redelivery
                raise

        # 8. Success -> Acknowledge message in Redis Streams
        await self._ack_message(message_id)
        return pipeline_result, alert

    async def process_batch(self) -> list[tuple[PipelineExecutionResult | None, Alert | None]]:
        """Read, reclaim, and process a batch of messages from Redis Streams."""
        results: list[tuple[PipelineExecutionResult | None, Alert | None]] = []

        # 1. Reclaim any stale pending messages from PEL
        stale_messages = await self._consumer.claim_stale_messages()
        for msg_id, data in stale_messages:
            res = await self.process_message(msg_id, data)
            results.append(res)

        # 2. Read and process new messages
        messages = await self._consumer.read_batch()
        for msg_id, data in messages:
            res = await self.process_message(msg_id, data)
            results.append(res)

        return results


    async def run(self, max_iterations: int | None = None) -> None:
        """Continuous consumption and processing loop with graceful shutdown support."""
        await self.initialize()
        self._running = True
        iterations = 0
        try:
            while self._running:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                await self.process_batch()
                iterations += 1
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal graceful shutdown."""
        self._running = False
        self._consumer.stop()

    async def close(self) -> None:
        """Close all underlying infrastructure resources."""
        self.stop()
        await self._telegram.close()
        await self._storage.close()
        await self._consumer.close()

    async def __aenter__(self) -> MadeCoreWorker:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
