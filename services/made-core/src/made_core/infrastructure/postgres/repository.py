"""Asynchronous PostgreSQL storage adapter for MADE Core entities."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


from made_core.domain.models import (
    AggregatedResult,
    Alert,
    DetectionResult,
    PipelineExecutionResult,
)
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import (
    AggregatedResultRecord,
    AlertRecord,
    Base,
    DetectionResultRecord,
    ProcessedEventRecord,
)


class PostgresStorageAdapter:
    """PostgreSQL repository for historical anomaly data and event idempotency."""

    def __init__(
        self,
        config: InfrastructureConfig | None = None,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._config = config or InfrastructureConfig()
        self._engine = engine
        self._owns_engine = engine is None and session_factory is None
        if session_factory is not None:
            self._session_factory = session_factory
        elif engine is not None:
            self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        else:
            self._engine = create_async_engine(
                self._config.get_postgres_url(async_driver=True),
                echo=False,
                future=True,
            )
            self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_tables(self) -> None:
        """Create all tables in the database schema (useful for test setups)."""
        if self._engine is not None:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    async def is_event_processed(self, event_id: str, session: AsyncSession | None = None) -> bool:
        """Check if an event_id has already been processed."""
        if not event_id:
            return False

        if session is not None:
            stmt = select(ProcessedEventRecord.event_id).where(ProcessedEventRecord.event_id == event_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

        async with self._session_factory() as sess:
            stmt = select(ProcessedEventRecord.event_id).where(ProcessedEventRecord.event_id == event_id)
            result = await sess.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def mark_event_processed(
        self,
        event_id: str,
        status: str,
        session: AsyncSession | None = None,
    ) -> None:
        """Mark an event as processed in the idempotency table."""
        record = ProcessedEventRecord(
            event_id=event_id,
            status=status,
            processed_at=datetime.now(UTC),
        )
        if session is not None:
            await session.merge(record)
        else:
            async with self._session_factory() as sess:
                async with sess.begin():
                    await sess.merge(record)

    async def save_detection_results(
        self,
        results: Sequence[DetectionResult],
        session: AsyncSession | None = None,
    ) -> None:
        """Save a batch of DetectionResult domain entities."""
        if not results:
            return

        records = [
            DetectionResultRecord(
                result_id=r.result_id,
                event_id=r.event_id,
                module_id=r.module_id,
                timestamp=r.timestamp,
                asset=r.asset,
                metric_value=r.metric_value,
                threshold=r.threshold,
                anomaly_ratio=r.anomaly_ratio,
                status=r.status.value,
                persistence=r.persistence,
                metadata_json=r.metadata,
            )
            for r in results
        ]

        if session is not None:
            for rec in records:
                await session.merge(rec)
        else:
            async with self._session_factory() as sess:
                async with sess.begin():
                    for rec in records:
                        await sess.merge(rec)

    async def save_aggregated_result(
        self,
        aggregate: AggregatedResult,
        session: AsyncSession | None = None,
    ) -> None:
        """Save an AggregatedResult domain entity."""
        if aggregate is None:
            return

        record = AggregatedResultRecord(
            aggregation_id=aggregate.aggregation_id,
            timestamp=aggregate.timestamp,
            asset=aggregate.asset,
            composite_anomaly_score=aggregate.composite_anomaly_score,
            max_anomaly_ratio=aggregate.max_anomaly_ratio,
            average_anomaly_ratio=aggregate.average_anomaly_ratio,
            priority=aggregate.priority.value,
            module_count=aggregate.module_count,
            triggered_modules=list(aggregate.triggered_modules),
            correlation_window=aggregate.correlation_window.model_dump(mode="json", by_alias=True),
            metadata_json=aggregate.metadata,
        )

        if session is not None:
            await session.merge(record)
        else:
            async with self._session_factory() as sess:
                async with sess.begin():
                    await sess.merge(record)

    async def save_alert(
        self,
        alert: Alert,
        event_id: str | None = None,
        notification_status: str = "PENDING",
        session: AsyncSession | None = None,
    ) -> None:
        """Save an Alert domain entity with event association and initial notification status."""
        if alert is None:
            return

        record = AlertRecord(
            alert_id=alert.alert_id,
            event_id=event_id,
            timestamp=alert.timestamp,
            asset=alert.asset,
            priority=alert.priority.value,
            title=alert.title,
            summary=alert.summary,
            anomaly_score=alert.anomaly_score,
            triggered_modules=list(alert.triggered_modules),
            details=alert.details,
            notification_status=notification_status,
            notification_attempts=0,
            created_at=datetime.now(UTC),
        )

        if session is not None:
            await session.merge(record)
        else:
            async with self._session_factory() as sess:
                async with sess.begin():
                    await sess.merge(record)

    async def get_alert(self, alert_id: str, session: AsyncSession | None = None) -> AlertRecord | None:
        """Retrieve an Alert record by alert_id."""
        if not alert_id:
            return None

        if session is not None:
            return await session.get(AlertRecord, alert_id)

        async with self._session_factory() as sess:
            return await sess.get(AlertRecord, alert_id)

    async def get_pending_alert_for_event(
        self,
        event_id: str,
        session: AsyncSession | None = None,
    ) -> AlertRecord | None:
        """Retrieve an Alert associated with event_id whose notification is still pending or failed."""
        if not event_id:
            return None

        stmt = (
            select(AlertRecord)
            .where(
                AlertRecord.event_id == event_id,
                AlertRecord.notification_status != "SENT",
            )
            .order_by(AlertRecord.created_at.desc())
        )

        if session is not None:
            result = await session.execute(stmt)
            return result.scalars().first()

        async with self._session_factory() as sess:
            result = await sess.execute(stmt)
            return result.scalars().first()

    async def mark_alert_sent(self, alert_id: str, session: AsyncSession | None = None) -> None:
        """Mark an Alert's notification status as SENT."""
        stmt = (
            update(AlertRecord)
            .where(AlertRecord.alert_id == alert_id)
            .values(
                notification_status="SENT",
                notified_at=datetime.now(UTC),
                last_notification_error=None,
            )
        )
        if session is not None:
            await session.execute(stmt)
        else:
            async with self._session_factory() as sess:
                async with sess.begin():
                    await sess.execute(stmt)

    async def mark_alert_failed(
        self,
        alert_id: str,
        error_message: str,
        session: AsyncSession | None = None,
    ) -> None:
        """Mark an Alert's notification status as FAILED and record error details."""
        stmt = (
            update(AlertRecord)
            .where(AlertRecord.alert_id == alert_id)
            .values(
                notification_status="FAILED",
                notification_attempts=AlertRecord.notification_attempts + 1,
                last_notification_error=error_message,
            )
        )
        if session is not None:
            await session.execute(stmt)
        else:
            async with self._session_factory() as sess:
                async with sess.begin():
                    await sess.execute(stmt)

    async def persist_processing_result(
        self,
        pipeline_result: PipelineExecutionResult,
        alert: Alert | None = None,
        aggregate: AggregatedResult | None = None,
    ) -> None:
        """Atomically persist pipeline execution results, idempotency record, and optional alert."""
        if pipeline_result is None:
            raise TypeError("pipeline_result must not be None")

        try:
            async with self._session_factory() as sess:
                async with sess.begin():
                    # 1. Mark event processed
                    await self.mark_event_processed(
                        pipeline_result.event_id,
                        pipeline_result.status.value,
                        session=sess,
                    )

                    # 2. Save detection results
                    if pipeline_result.detection_results:
                        await self.save_detection_results(
                            pipeline_result.detection_results,
                            session=sess,
                        )

                    # 3. Save aggregated result if present
                    if aggregate is not None:
                        await self.save_aggregated_result(aggregate, session=sess)

                    # 4. Save alert if present
                    if alert is not None:
                        await self.save_alert(
                            alert,
                            event_id=pipeline_result.event_id,
                            notification_status="PENDING",
                            session=sess,
                        )
        except IntegrityError as err:
            logger.info("Concurrent insert for event %s already completed: %s", pipeline_result.event_id, err)


    async def close(self) -> None:
        """Dispose of the engine and connection pool if owned."""
        if self._owns_engine and self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def __aenter__(self) -> PostgresStorageAdapter:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
