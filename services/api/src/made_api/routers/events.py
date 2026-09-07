"""Processed events query router."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from made_api.dependencies import get_query_service
from made_api.schemas.common import PaginatedResponse
from made_api.schemas.events import ProcessedEventResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("", response_model=PaginatedResponse[ProcessedEventResponse], summary="List processed events")
async def list_events(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
    limit: int = Query(default=50, ge=1, le=100, description="Max items to return (1-100)"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    event_id: str | None = Query(default=None, description="Filter by event identifier"),
    status: str | None = Query(default=None, description="Filter by processing status"),
    from_timestamp: datetime | None = Query(default=None, description="Filter events processed on or after UTC timestamp"),
    to_timestamp: datetime | None = Query(default=None, description="Filter events processed on or before UTC timestamp"),
) -> PaginatedResponse[ProcessedEventResponse]:
    """List paginated processed events with optional filters."""
    return await service.get_events(
        limit=limit,
        offset=offset,
        event_id=event_id,
        status=status,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )


@router.get("/{event_id}", response_model=ProcessedEventResponse, summary="Get processed event by ID")
async def get_event(
    event_id: str,
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> ProcessedEventResponse:
    """Retrieve a single processed event by event_id."""
    event = await service.get_event(event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with ID '{event_id}' not found",
        )
    return event
