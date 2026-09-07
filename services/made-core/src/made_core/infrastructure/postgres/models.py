"""SQLAlchemy 2.x ORM models for PostgreSQL persistence in MADE."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class DetectionResultRecord(Base):
    """Database table for storing individual detection results."""

    __tablename__ = "detection_results"

    result_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    module_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    asset: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    anomaly_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    persistence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)


class AggregatedResultRecord(Base):
    """Database table for candidate anomaly aggregations."""

    __tablename__ = "aggregated_results"

    aggregation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    asset: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    composite_anomaly_score: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    max_anomaly_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    average_anomaly_ratio: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    module_count: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_modules: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    correlation_window: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)


class AlertRecord(Base):
    """Database table for prioritized notifications and alerts."""

    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    asset: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    anomaly_score: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    triggered_modules: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    notification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    notification_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class ProcessedEventRecord(Base):
    """Idempotency tracking for processed normalized events."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class ModuleConfigRecord(Base):
    """Database table for dynamic detection module configuration and thresholds."""

    __tablename__ = "module_configs"

    module_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    threshold: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    reference_price_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="AVERAGE")
    max_price_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("2.0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
