"""Asynchronous PostgreSQL storage adapter for MADE Core entities."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
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
    ModuleConfigRecord,
    ProcessedEventRecord,
)


def _sanitize_json(data: Any) -> Any:
    """Ensure dictionary values are JSON-serializable across backends (converting Decimal, datetime, etc.)."""
    if isinstance(data, dict):
        return {k: _sanitize_json(v) for k, v in data.items()}
    if isinstance(data, (list, tuple, set)):
        return [_sanitize_json(item) for item in data]
    if isinstance(data, Decimal):
        return str(data)
    if isinstance(data, datetime):
        return data.isoformat()
    return data


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

    async def purge_normal_detections(self) -> int:
        """Delete historical NORMAL detection records from database, retaining only actual anomalies."""
        async with self._session_factory() as sess:
            async with sess.begin():
                stmt = delete(DetectionResultRecord).where(DetectionResultRecord.status == "NORMAL")
                result = await sess.execute(stmt)
                return result.rowcount or 0

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
        anomalies_only: bool = False,
    ) -> None:
        """Save a batch of DetectionResult domain entities."""
        if not results:
            return

        target_results = [r for r in results if r.status.value == "ANOMALY"] if anomalies_only else results
        if not target_results:
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
                metadata_json=_sanitize_json(r.metadata),
            )
            for r in target_results
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
            correlation_window=_sanitize_json(aggregate.correlation_window.model_dump(mode="json", by_alias=True)),
            metadata_json=_sanitize_json(aggregate.metadata),
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
            details=_sanitize_json(alert.details),
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

                    # 2. Save detection results (persist only ANOMALY detections to database)
                    if pipeline_result.detection_results:
                        await self.save_detection_results(
                            pipeline_result.detection_results,
                            session=sess,
                            anomalies_only=True,
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

    async def check_health(self) -> bool:
        """Lightweight database connectivity probe (returns True if accessible)."""
        try:
            async with self._session_factory() as sess:
                result = await sess.execute(select(1))
                return result.scalar() == 1
        except Exception as exc:
            logger.warning("Database health check failed: %s", exc)
            return False

    async def get_processed_events(
        self,
        limit: int = 50,
        offset: int = 0,
        event_id: str | None = None,
        status: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> tuple[Sequence[ProcessedEventRecord], int]:
        """Retrieve paginated processed events with optional filters."""
        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)

        async with self._session_factory() as sess:
            conditions = []
            if event_id:
                conditions.append(ProcessedEventRecord.event_id == event_id)
            if status:
                conditions.append(ProcessedEventRecord.status == status)
            if from_timestamp:
                conditions.append(ProcessedEventRecord.processed_at >= from_timestamp)
            if to_timestamp:
                conditions.append(ProcessedEventRecord.processed_at <= to_timestamp)

            count_stmt = select(func.count()).select_from(ProcessedEventRecord)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = (await sess.execute(count_stmt)).scalar_one()

            stmt = (
                select(ProcessedEventRecord)
                .order_by(ProcessedEventRecord.processed_at.desc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            if conditions:
                stmt = stmt.where(*conditions)

            items = (await sess.execute(stmt)).scalars().all()
            return items, total

    async def get_processed_event(self, event_id: str) -> ProcessedEventRecord | None:
        """Retrieve a single processed event by event_id."""
        if not event_id:
            return None
        async with self._session_factory() as sess:
            return await sess.get(ProcessedEventRecord, event_id)

    async def get_detection_results(
        self,
        limit: int = 50,
        offset: int = 0,
        event_id: str | None = None,
        module_id: str | None = None,
        status: str | None = None,
        asset: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> tuple[Sequence[DetectionResultRecord], int]:
        """Retrieve paginated detection results with optional filters."""
        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)

        async with self._session_factory() as sess:
            conditions = []
            if event_id:
                conditions.append(DetectionResultRecord.event_id == event_id)
            if module_id:
                conditions.append(DetectionResultRecord.module_id == module_id)
            if status:
                conditions.append(DetectionResultRecord.status == status)
            if asset:
                conditions.append(DetectionResultRecord.asset == asset)
            if from_timestamp:
                conditions.append(DetectionResultRecord.timestamp >= from_timestamp)
            if to_timestamp:
                conditions.append(DetectionResultRecord.timestamp <= to_timestamp)

            count_stmt = select(func.count()).select_from(DetectionResultRecord)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = (await sess.execute(count_stmt)).scalar_one()

            stmt = (
                select(DetectionResultRecord)
                .order_by(DetectionResultRecord.timestamp.desc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            if conditions:
                stmt = stmt.where(*conditions)

            items = (await sess.execute(stmt)).scalars().all()
            return items, total

    async def get_detection_result(self, result_id: str) -> DetectionResultRecord | None:
        """Retrieve a single detection result by result_id."""
        if not result_id:
            return None
        async with self._session_factory() as sess:
            return await sess.get(DetectionResultRecord, result_id)

    async def get_aggregated_results(
        self,
        limit: int = 50,
        offset: int = 0,
        asset: str | None = None,
        priority: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> tuple[Sequence[AggregatedResultRecord], int]:
        """Retrieve paginated aggregated results with optional filters."""
        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)

        async with self._session_factory() as sess:
            conditions = []
            if asset:
                conditions.append(AggregatedResultRecord.asset == asset)
            if priority:
                conditions.append(AggregatedResultRecord.priority == priority)
            if from_timestamp:
                conditions.append(AggregatedResultRecord.timestamp >= from_timestamp)
            if to_timestamp:
                conditions.append(AggregatedResultRecord.timestamp <= to_timestamp)

            count_stmt = select(func.count()).select_from(AggregatedResultRecord)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = (await sess.execute(count_stmt)).scalar_one()

            stmt = (
                select(AggregatedResultRecord)
                .order_by(AggregatedResultRecord.timestamp.desc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            if conditions:
                stmt = stmt.where(*conditions)

            items = (await sess.execute(stmt)).scalars().all()
            return items, total

    async def get_aggregated_result(self, aggregation_id: str) -> AggregatedResultRecord | None:
        """Retrieve a single aggregated result by aggregation_id."""
        if not aggregation_id:
            return None
        async with self._session_factory() as sess:
            return await sess.get(AggregatedResultRecord, aggregation_id)

    async def get_alerts(
        self,
        limit: int = 50,
        offset: int = 0,
        event_id: str | None = None,
        priority: str | None = None,
        notification_status: str | None = None,
        asset: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> tuple[Sequence[AlertRecord], int]:
        """Retrieve paginated alerts with optional filters."""
        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)

        async with self._session_factory() as sess:
            conditions = []
            if event_id:
                conditions.append(AlertRecord.event_id == event_id)
            if priority:
                conditions.append(AlertRecord.priority == priority)
            if notification_status:
                conditions.append(AlertRecord.notification_status == notification_status)
            if asset:
                conditions.append(AlertRecord.asset == asset)
            if from_timestamp:
                conditions.append(AlertRecord.timestamp >= from_timestamp)
            if to_timestamp:
                conditions.append(AlertRecord.timestamp <= to_timestamp)

            count_stmt = select(func.count()).select_from(AlertRecord)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = (await sess.execute(count_stmt)).scalar_one()

            stmt = (
                select(AlertRecord)
                .order_by(AlertRecord.timestamp.desc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            if conditions:
                stmt = stmt.where(*conditions)

            items = (await sess.execute(stmt)).scalars().all()
            return items, total

    async def get_metrics(self) -> dict[str, Any]:
        """Derive operational metrics from persisted records."""
        async with self._session_factory() as sess:
            total_events = (await sess.execute(select(func.count()).select_from(ProcessedEventRecord))).scalar_one()
            total_detections = (await sess.execute(select(func.count()).select_from(DetectionResultRecord))).scalar_one()
            status_counts_rows = (
                await sess.execute(
                    select(DetectionResultRecord.status, func.count())
                    .group_by(DetectionResultRecord.status)
                )
            ).all()
            detections_by_status = {row[0]: row[1] for row in status_counts_rows}

            module_counts_rows = (
                await sess.execute(
                    select(DetectionResultRecord.module_id, func.count())
                    .group_by(DetectionResultRecord.module_id)
                )
            ).all()
            detections_by_module = {row[0]: row[1] for row in module_counts_rows}

            total_aggregates = (await sess.execute(select(func.count()).select_from(AggregatedResultRecord))).scalar_one()
            total_alerts = (await sess.execute(select(func.count()).select_from(AlertRecord))).scalar_one()
            priority_rows = (
                await sess.execute(
                    select(AlertRecord.priority, func.count())
                    .group_by(AlertRecord.priority)
                )
            ).all()
            alerts_by_priority = {row[0]: row[1] for row in priority_rows}

            notif_rows = (
                await sess.execute(
                    select(AlertRecord.notification_status, func.count())
                    .group_by(AlertRecord.notification_status)
                )
            ).all()
            alerts_by_notification_status = {row[0]: row[1] for row in notif_rows}

            return {
                "total_processed_events": total_events,
                "total_detections": total_detections,
                "detections_by_status": detections_by_status,
                "detections_by_module": detections_by_module,
                "total_aggregates": total_aggregates,
                "total_alerts": total_alerts,
                "alerts_by_priority": alerts_by_priority,
                "alerts_by_notification_status": alerts_by_notification_status,
            }

    async def get_module_configs(self) -> list[ModuleConfigRecord]:
        """Retrieve all dynamic detection module configurations."""
        async with self._session_factory() as sess:
            stmt = select(ModuleConfigRecord).order_by(ModuleConfigRecord.module_id)
            result = await sess.execute(stmt)
            return list(result.scalars().all())

    async def get_module_config(self, module_id: str) -> ModuleConfigRecord | None:
        """Retrieve dynamic configuration for a specific module."""
        async with self._session_factory() as sess:
            stmt = select(ModuleConfigRecord).where(ModuleConfigRecord.module_id == module_id)
            result = await sess.execute(stmt)
            return result.scalar_one_or_none()

    async def upsert_module_config(
        self,
        module_id: str,
        threshold: Decimal | None = None,
        reference_price_mode: str | None = None,
        max_price_ratio: Decimal | None = None,
        status: str | None = None,
    ) -> ModuleConfigRecord:
        """Create or update configuration settings for a detection module."""
        async with self._session_factory() as sess:
            async with sess.begin():
                stmt = select(ModuleConfigRecord).where(ModuleConfigRecord.module_id == module_id)
                res = await sess.execute(stmt)
                record = res.scalar_one_or_none()

                now = datetime.now(UTC)
                if record is None:
                    record = ModuleConfigRecord(
                        module_id=module_id,
                        threshold=threshold if threshold is not None else Decimal("4.0"),
                        reference_price_mode=reference_price_mode or "AVERAGE",
                        max_price_ratio=max_price_ratio if max_price_ratio is not None else Decimal("2.0"),
                        status=status or "active",
                        updated_at=now,
                    )
                    sess.add(record)
                else:
                    if threshold is not None:
                        record.threshold = threshold
                    if reference_price_mode is not None:
                        record.reference_price_mode = reference_price_mode
                    if max_price_ratio is not None:
                        record.max_price_ratio = max_price_ratio
                    if status is not None:
                        record.status = status
                    record.updated_at = now

            # Refresh and return
            await sess.refresh(record)
            return record

    async def get_chart_history(
        self,
        asset: str,
        symbol: str | None = None,
        module_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 2000,
    ) -> list[DetectionResultRecord]:
        """Retrieve historical detection results ordered by timestamp ASC for charting."""
        async with self._session_factory() as sess:
            stmt = select(DetectionResultRecord).where(DetectionResultRecord.asset == asset)
            if module_id:
                stmt = stmt.where(DetectionResultRecord.module_id == module_id)
            if start_time is not None:
                stmt = stmt.where(DetectionResultRecord.timestamp >= start_time)
            if end_time is not None:
                stmt = stmt.where(DetectionResultRecord.timestamp <= end_time)
            stmt = stmt.order_by(DetectionResultRecord.timestamp.asc()).limit(limit)
            result = await sess.execute(stmt)
            records = list(result.scalars().all())

            if symbol:
                filtered = [
                    r for r in records
                    if str(r.metadata_json.get("firstSymbol") or "").upper() == symbol.upper()
                    or str(r.metadata_json.get("secondSymbol") or "").upper() == symbol.upper()
                    or not r.metadata_json.get("firstSymbol")
                ]
                return filtered or records

            return records

    async def close(self) -> None:
        """Dispose of the engine and connection pool if owned."""
        if self._owns_engine and self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def __aenter__(self) -> PostgresStorageAdapter:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
