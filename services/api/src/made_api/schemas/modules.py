"""Response and request schemas for detection module configuration and metadata."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ModuleMetadataResponse(BaseModel):
    """Schema representing metadata and active configuration for a detection module."""

    model_config = ConfigDict(from_attributes=True)

    module_id: str = Field(description="Unique stable identifier of the detection module")
    status: str = Field(default="active", description="Module registry lifecycle status (active/paused)")
    description: str = Field(description="Human-readable description of module purpose")
    threshold: str = Field(default="4.00", description="Configured anomaly trigger threshold percentage")
    reference_price_mode: str = Field(default="AVERAGE", description="Reference price calculation mode (AVERAGE, FIRST, SECOND, LAST)")
    max_price_ratio: str = Field(default="2.00", description="Maximum price scale ratio before homonym blacklist rejection")
    updated_at: datetime | None = Field(default=None, description="Timestamp when configuration was last updated")


class ModuleConfigUpdateRequest(BaseModel):
    """Request schema for updating detection module configuration parameters."""

    threshold: Decimal | None = Field(default=None, gt=Decimal("0"), description="Anomaly spread trigger threshold percentage (must be > 0)")
    status: str | None = Field(default=None, pattern="^(active|paused)$", description="Module operational status ('active' or 'paused')")
    reference_price_mode: str | None = Field(default=None, pattern="^(AVERAGE|FIRST|SECOND|LAST)$", description="Reference price calculation mode")
    max_price_ratio: Decimal | None = Field(default=None, gt=Decimal("1.0"), description="Maximum price scale ratio filter")
