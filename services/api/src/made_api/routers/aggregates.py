"""Aggregated anomaly results query router."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from made_api.dependencies import get_query_service
from made_api.schemas.aggregates import AggregatedResultResponse
from made_api.schemas.common import PaginatedResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/aggregates", tags=["aggregates"])


@router.get("", response_model=PaginatedResponse[AggregatedResultResponse], summary="List aggregated anomaly results")
async def list_aggregates(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
    limit: int = Query(default=50, ge=1, le=100, description="Max items to return (1-100)"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    asset: str | None = Query(default=None, description="Filter by base asset (e.g. BTC)"),
    priority: str | None = Query(default=None, description="Filter by priority (LOW, MEDIUM, HIGH)"),
    from_timestamp: datetime | None = Query(default=None, description="Filter aggregates on or after timestamp"),
    to_timestamp: datetime | None = Query(default=None, description="Filter aggregates on or before timestamp"),
) -> PaginatedResponse[AggregatedResultResponse]:
    """List paginated aggregated results with optional filters."""
    return await service.get_aggregates(
        limit=limit,
        offset=offset,
        asset=asset,
        priority=priority,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )


@router.get("/{aggregation_id}", response_model=AggregatedResultResponse, summary="Get aggregate by ID")
async def get_aggregate(
    aggregation_id: str,
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> AggregatedResultResponse:
    """Retrieve a single aggregated result by aggregation_id."""
    aggregate = await service.get_aggregate(aggregation_id)
    if aggregate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aggregated result with ID '{aggregation_id}' not found",
        )
    return aggregate
