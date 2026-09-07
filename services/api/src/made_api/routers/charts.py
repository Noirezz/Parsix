"""Historical price and spread divergence chart API router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from made_api.dependencies import get_query_service
from made_api.schemas.charts import ChartHistoryResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/charts", tags=["charts"])


@router.get("/history", response_model=ChartHistoryResponse, summary="Get historical price and spread divergence timeseries")
async def get_chart_history(
    asset: Annotated[str, Query(description="Base asset ticker symbol (e.g. BTC, ETH, SOL)")],
    service: Annotated[MadeQueryService, Depends(get_query_service)],
    symbol: Annotated[str | None, Query(description="Optional specific trading pair symbol (e.g. BTCUSDT)")] = None,
    module_id: Annotated[str, Query(description="Detection module ID to query historical divergence for")] = "futures-futures-spread",
    timeframe: Annotated[str, Query(description="Timeframe window: 10s, 1m, 15m, 1h, 24h", pattern="^(10s|1m|15m|1h|24h)$")] = "1h",
) -> ChartHistoryResponse:
    """Retrieve chronologically ordered timeseries points of prices, spread %, and anomaly persistence."""
    return await service.get_chart_history(
        asset=asset,
        symbol=symbol,
        module_id=module_id,
        timeframe=timeframe,
    )
