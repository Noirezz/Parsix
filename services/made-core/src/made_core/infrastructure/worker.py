"""Infrastructure worker orchestrating Redis Streams, Core pipelines, PostgreSQL persistence, and Telegram notifications."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.pipeline import EventPipeline
from made_core.domain.enums import EventSource, MarketType, Priority, ReferencePriceMode, ValidationStatus
from made_core.domain.models import Alert, MarketSnapshot, NormalizedEvent, PipelineExecutionResult
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import AlertRecord
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.infrastructure.redis_consumer import RedisStreamConsumer
from made_core.infrastructure.telegram.notifier import (
    TelegramNotificationAdapter,
    TelegramNotificationError,
)

logger = logging.getLogger(__name__)


class SnapshotCache:
    """In-memory bounded cache storing the latest MarketSnapshot per (source, market_type, symbol)."""

    def __init__(self, freshness_ttl_seconds: float | None = 300.0) -> None:
        self._freshness_ttl_seconds = freshness_ttl_seconds
        self._snapshots: dict[tuple[EventSource, MarketType, str], MarketSnapshot] = {}

    def update_from_event(self, event: NormalizedEvent) -> MarketSnapshot:
        funding_rate = None
        raw_funding = event.metadata.get("funding_rate") or event.metadata.get("fundingRate")
        if raw_funding is not None:
            try:
                funding_rate = Decimal(str(raw_funding))
            except (InvalidOperation, TypeError, ValueError):
                funding_rate = None

        snapshot = MarketSnapshot(
            timestamp=event.timestamp,
            source=event.source,
            market_type=event.market_type,
            asset=event.asset,
            symbol=event.symbol,
            price=event.price,
            bid=event.bid,
            ask=event.ask,
            volume=event.volume,
            funding_rate=funding_rate,
            metadata=event.metadata.copy(),
        )
        self._snapshots[(event.source, event.market_type, event.symbol)] = snapshot
        return snapshot

    def get_snapshots_for(
        self,
        asset: str,
        symbol: str,
        current_time: datetime | None = None,
    ) -> tuple[MarketSnapshot, ...]:
        result: list[MarketSnapshot] = []
        for (source, market_type, sym), snap in list(self._snapshots.items()):
            if snap.asset == asset and snap.symbol == symbol:
                if self._freshness_ttl_seconds is not None and current_time is not None:
                    age_seconds = abs((current_time - snap.timestamp).total_seconds())
                    if age_seconds > self._freshness_ttl_seconds:
                        continue
                result.append(snap)
        return tuple(result)

    def clear(self) -> None:
        self._snapshots.clear()


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
        snapshot_cache: SnapshotCache | None = None,
    ) -> None:
        self._consumer = consumer
        self._event_pipeline = event_pipeline
        self._anomaly_pipeline = anomaly_pipeline
        self._storage = storage
        self._telegram = telegram
        self._config = config or InfrastructureConfig()
        self._snapshot_cache = snapshot_cache or SnapshotCache(
            freshness_ttl_seconds=self._config.snapshot_freshness_ttl_seconds
        )
        self._running = False

    async def initialize(self) -> None:
        """Initialize consumer and storage adapters and sync module configurations."""
        await self._consumer.initialize()
        await self._storage.create_tables()
        await self.sync_module_configs()

    async def sync_module_configs(self) -> None:
        """Synchronize dynamic module configurations from PostgreSQL into active DetectionModules."""
        try:
            configs = await self._storage.get_module_configs()
            if not configs:
                return

            rule_executor = getattr(self._event_pipeline, "_executor", None)
            registry = getattr(rule_executor, "_registry", None)
            if registry is None:
                return

            for cfg_rec in configs:
                mod_id = cfg_rec.module_id
                if registry.contains(mod_id):
                    # 1. Update module active/paused status
                    registry.set_module_status(mod_id, cfg_rec.status)

                    # 2. Update module threshold and reference price mode
                    mod = registry.get(mod_id)
                    if hasattr(mod, "update_config"):
                        if mod_id == "funding-spread":
                            mod.update_config(threshold=cfg_rec.threshold)
                        else:
                            ref_mode = None
                            if cfg_rec.reference_price_mode:
                                try:
                                    ref_mode = ReferencePriceMode(cfg_rec.reference_price_mode)
                                except ValueError:
                                    pass
                            mod.update_config(
                                threshold=cfg_rec.threshold,
                                reference_price_mode=ref_mode,
                                max_price_ratio=cfg_rec.max_price_ratio,
                            )
        except Exception as err:
            logger.warning("Failed syncing module configs from database: %s", err)

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

        # 3. Update snapshot cache & get matching multi-source snapshots
        self._snapshot_cache.update_from_event(event)
        matching_snapshots = self._snapshot_cache.get_snapshots_for(
            asset=event.asset,
            symbol=event.symbol,
            current_time=event.timestamp,
        )

        # 4. New event: Execute upstream Core pipeline with multi-source snapshots
        try:
            pipeline_result = self._event_pipeline.process_event(event, snapshots=matching_snapshots)
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
            aggregate, alert = self._anomaly_pipeline.process_pipeline_result_detailed(pipeline_result)
        except Exception as anom_err:
            logger.error("Downstream AnomalyProcessingPipeline failure for event %s: %s", event.event_id, anom_err)
            raise

        # 6. Persist durable PostgreSQL state (atomic commit)
        try:
            await self._storage.persist_processing_result(
                pipeline_result,
                alert=alert,
                aggregate=aggregate,
            )
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

        # 0. Sync latest module configurations from database
        await self.sync_module_configs()

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
                try:
                    await self.process_batch()
                except Exception as batch_err:
                    logger.error("Error in worker processing batch: %s", batch_err)
                    await asyncio.sleep(0.5)
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
