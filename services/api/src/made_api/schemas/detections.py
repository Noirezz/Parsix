"""Response schemas for module detection results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DetectionResultResponse(BaseModel):
    """Schema representing an individual detection result produced by a module."""

    model_config = ConfigDict(from_attributes=True)

    result_id: str = Field(description="Unique detection result identifier")
    event_id: str = Field(description="Identifier of the normalized event triggering detection")
    module_id: str = Field(description="Unique identifier of the detection module")
    timestamp: datetime = Field(description="UTC timestamp of the detection result")
    asset: str = Field(description="Base asset analyzed (e.g. BTC)")
    metric_value: Decimal = Field(description="Observed metric value (e.g. calculated spread %)")
    threshold: Decimal = Field(description="Configured threshold for anomaly triggering")
    anomaly_ratio: Decimal = Field(description="Ratio of metric value relative to threshold")
    status: str = Field(description="Detection status (NORMAL or ANOMALY)")
    persistence: int = Field(description="Anomaly persistence score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata dictionary associated with detection")
