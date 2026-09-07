"""Response schemas for processed events."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProcessedEventResponse(BaseModel):
    """Schema representing an event processed through the MADE idempotency layer."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(description="Unique event identifier")
    status: str = Field(description="Processing status (e.g. COMPLETED, INVALID, ERROR)")
    processed_at: datetime = Field(description="UTC timestamp when the event was processed")
