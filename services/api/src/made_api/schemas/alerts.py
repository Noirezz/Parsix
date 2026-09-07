"""Response schemas for prioritized alerts and notifications."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertResponse(BaseModel):
    """Schema representing a prioritized notification-ready alert."""

    model_config = ConfigDict(from_attributes=True)

    alert_id: str = Field(description="Unique alert identifier")
    event_id: str | None = Field(default=None, description="Triggering event identifier if available")
    timestamp: datetime = Field(description="UTC timestamp of the alert")
    asset: str = Field(description="Base asset (e.g. BTC)")
    priority: str = Field(description="Alert priority level (LOW, MEDIUM, HIGH)")
    title: str = Field(description="Alert title")
    summary: str = Field(description="Human-readable summary of detected anomaly")
    anomaly_score: Decimal = Field(description="Final anomaly score")
    triggered_modules: list[str] = Field(description="List of triggered module identifiers")
    details: dict[str, Any] = Field(default_factory=dict, description="Structured alert details")
    notification_status: str = Field(description="Delivery status (PENDING, SENT, FAILED)")
    notification_attempts: int = Field(description="Number of notification delivery attempts")
    notified_at: datetime | None = Field(default=None, description="Timestamp when notification was successfully delivered")
    last_notification_error: str | None = Field(default=None, description="Last delivery failure error message if any")
    created_at: datetime = Field(description="Record creation timestamp")
