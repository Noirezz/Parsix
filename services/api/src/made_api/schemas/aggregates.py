"""Response schemas for aggregated anomaly results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AggregatedResultResponse(BaseModel):
    """Schema representing combined signals for a candidate anomaly."""

    model_config = ConfigDict(from_attributes=True)

    aggregation_id: str = Field(description="Unique aggregation identifier")
    timestamp: datetime = Field(description="UTC timestamp of aggregation")
    asset: str = Field(description="Base asset aggregated (e.g. BTC)")
    composite_anomaly_score: Decimal = Field(description="Weighted composite score")
    max_anomaly_ratio: Decimal = Field(description="Maximum anomaly ratio among triggered modules")
    average_anomaly_ratio: Decimal = Field(description="Average anomaly ratio across modules")
    priority: str = Field(description="Evaluated priority (LOW, MEDIUM, HIGH)")
    module_count: int = Field(description="Number of contributing modules")
    triggered_modules: list[str] = Field(description="List of triggered module identifiers")
    correlation_window: dict[str, Any] = Field(description="Correlation time window and grouping metadata")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional aggregation metadata")
