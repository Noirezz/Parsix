"""Response schemas for operational metrics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MetricsResponse(BaseModel):
    """Schema representing operational aggregate metrics derived from PostgreSQL persistence."""

    model_config = ConfigDict(from_attributes=True)

    total_processed_events: int = Field(ge=0, description="Total events processed through idempotency layer")
    total_detections: int = Field(ge=0, description="Total individual detection results recorded")
    detections_by_status: dict[str, int] = Field(description="Count of detections grouped by status (NORMAL, ANOMALY)")
    detections_by_module: dict[str, int] = Field(description="Count of detections grouped by module identifier")
    total_aggregates: int = Field(ge=0, description="Total aggregated candidate results recorded")
    total_alerts: int = Field(ge=0, description="Total alerts generated")
    alerts_by_priority: dict[str, int] = Field(description="Count of alerts grouped by priority (LOW, MEDIUM, HIGH)")
    alerts_by_notification_status: dict[str, int] = Field(description="Count of alerts grouped by delivery status (PENDING, SENT, FAILED)")
