"""Pydantic domain contracts for the canonical MADE processing flow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from made_core.domain.enums import EventSource, MarketType, Priority, ResultStatus, ValidationStatus


def to_camel_case(value: str) -> str:
    """Expose canonical contract field names in camelCase at API boundaries."""
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class DomainModel(BaseModel):
    """Base settings shared by immutable, explicit domain contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, alias_generator=to_camel_case)


class TimestampedModel(DomainModel):
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class RawEvent(TimestampedModel):
    """Unnormalised payload received by a Collector Service."""

    event_id: str = Field(min_length=1)
    source: EventSource
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedEvent(TimestampedModel):
    """Standardised market event received by MADE through Redis Streams."""

    event_id: str = Field(min_length=1)
    source: EventSource
    market_type: MarketType
    asset: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset", "symbol")
    @classmethod
    def identifier_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value


class ValidationError(DomainModel):
    """Structured error detailing why a NormalizedEvent is invalid."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field: str | None = None
    event_id: str = Field(min_length=1)


class ValidationResult(DomainModel):
    """Result of validating a NormalizedEvent before enrichment."""

    event_id: str = Field(min_length=1)
    status: ValidationStatus
    errors: tuple[ValidationError, ...] = ()
    validated_event: NormalizedEvent | None = None


class MarketSnapshot(TimestampedModel):
    """Market data applicable to an asset/symbol at a point in time."""

    source: EventSource
    market_type: MarketType
    asset: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    funding_rate: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketContext(DomainModel):
    """Relevant market snapshots provided to detection modules."""

    asset: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    snapshots: tuple[MarketSnapshot, ...] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("snapshots")
    @classmethod
    def snapshots_must_match_context(cls, snapshots: tuple[MarketSnapshot, ...], info: Any) -> tuple[MarketSnapshot, ...]:
        asset = info.data.get("asset")
        symbol = info.data.get("symbol")
        if asset is not None and any(snapshot.asset != asset for snapshot in snapshots):
            raise ValueError("all snapshots must match the context asset")
        if symbol is not None and any(snapshot.symbol != symbol for snapshot in snapshots):
            raise ValueError("all snapshots must match the context symbol")
        return snapshots


class EnrichedEvent(TimestampedModel):
    """Normalised event with the context and metrics needed by modules."""

    event_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    market_context: MarketContext
    normalized_data: NormalizedEvent
    reference_data: dict[str, Decimal] = Field(default_factory=dict)
    calculated_metrics: dict[str, Decimal] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("market_context")
    @classmethod
    def context_must_match_event(cls, context: MarketContext, info: Any) -> MarketContext:
        asset = info.data.get("asset")
        if asset is not None and context.asset != asset:
            raise ValueError("market context must match the event asset")
        return context


class DetectionResult(TimestampedModel):
    """Standardised output from one detection module."""

    result_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    metric_value: Decimal
    threshold: Decimal = Field(ge=0)
    anomaly_ratio: Decimal = Field(ge=0)
    status: ResultStatus
    persistence: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineExecutionResult(DomainModel):
    """Execution result of the complete MADE Core pipeline for one event."""

    event_id: str = Field(min_length=1)
    status: ValidationStatus
    validation_result: ValidationResult
    enriched_event: EnrichedEvent | None = None
    detection_results: tuple[DetectionResult, ...] = ()


class CorrelatedGroup(DomainModel):
    """Related detection results grouped by asset and correlation window."""

    correlation_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    window_start: datetime
    window_end: datetime
    results: tuple[DetectionResult, ...] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("window_end")
    @classmethod
    def window_end_must_not_precede_start(cls, end: datetime, info: Any) -> datetime:
        start = info.data.get("window_start")
        if start is not None and end < start:
            raise ValueError("window_end must not precede window_start")
        return end


class AggregatedResult(TimestampedModel):
    """Combined signals for one candidate anomaly."""

    aggregation_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    correlation_window: CorrelatedGroup
    triggered_modules: tuple[str, ...] = Field(min_length=1)
    module_count: int = Field(ge=1)
    composite_anomaly_score: Decimal = Field(ge=0)
    max_anomaly_ratio: Decimal = Field(ge=0)
    average_anomaly_ratio: Decimal = Field(ge=0)
    priority: Priority
    source_results: tuple[DetectionResult, ...] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("module_count")
    @classmethod
    def module_count_must_match_modules(cls, count: int, info: Any) -> int:
        modules = info.data.get("triggered_modules")
        if modules is not None and count != len(modules):
            raise ValueError("module_count must match triggered_modules")
        return count


class Alert(TimestampedModel):
    """Prioritised notification-ready anomaly."""

    alert_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    priority: Priority
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    anomaly_score: Decimal = Field(ge=0)
    triggered_modules: tuple[str, ...] = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
