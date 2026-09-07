"""Response schemas for historical price and spread divergence charts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ChartPoint(BaseModel):
    """A single timeseries point containing price observations and spread divergence."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime = Field(description="ISO-8601 UTC timestamp of the observation")
    time_epoch: int = Field(description="Unix timestamp in seconds for TradingView Lightweight Charts")
    price_1: Decimal | None = Field(default=None, description="Price from Source 1 (e.g. Binance / DEX)")
    source_1: str | None = Field(default=None, description="Name of Exchange/Source 1")
    price_2: Decimal | None = Field(default=None, description="Price from Source 2 (e.g. Bybit Futures)")
    source_2: str | None = Field(default=None, description="Name of Exchange/Source 2")
    spread_percent: Decimal = Field(description="Divergence spread percentage between sources")
    threshold: Decimal = Field(description="Anomaly trigger threshold percentage at that time")
    is_anomaly: bool = Field(description="True if spread exceeded the threshold")


class ChartHistoryResponse(BaseModel):
    """Historical timeseries and analytical metrics for price/spread divergence visualization."""

    model_config = ConfigDict(from_attributes=True)

    asset: str = Field(description="Base asset (e.g. BTC, SOL)")
    symbol: str = Field(description="Trading pair symbol (e.g. BTCUSDT)")
    module_id: str = Field(description="Detection module identifier (e.g. futures-futures-spread)")
    timeframe: str = Field(description="Selected timeframe window (10s, 1m, 15m, 1h, 24h)")
    points: list[ChartPoint] = Field(default_factory=list, description="Ordered chronological timeseries points")
    current_spread: Decimal | None = Field(default=None, description="Latest spread percentage")
    max_spread: Decimal | None = Field(default=None, description="Maximum observed spread percentage in timeframe")
    avg_spread: Decimal | None = Field(default=None, description="Average spread percentage in timeframe")
    spread_duration_seconds: int | None = Field(default=None, description="Estimated duration in seconds that current spread persisted above threshold")
