"""Alerts and notifications query router."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from made_api.dependencies import get_query_service
from made_api.schemas.alerts import AlertResponse
from made_api.schemas.common import PaginatedResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=PaginatedResponse[AlertResponse], summary="List alerts")
async def list_alerts(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
    limit: int = Query(default=50, ge=1, le=100, description="Max items to return (1-100)"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    event_id: str | None = Query(default=None, description="Filter by event identifier"),
    priority: str | None = Query(default=None, description="Filter by priority (LOW, MEDIUM, HIGH)"),
    notification_status: str | None = Query(default=None, description="Filter by delivery status (PENDING, SENT, FAILED)"),
    asset: str | None = Query(default=None, description="Filter by base asset (e.g. BTC)"),
    from_timestamp: datetime | None = Query(default=None, description="Filter alerts on or after timestamp"),
    to_timestamp: datetime | None = Query(default=None, description="Filter alerts on or before timestamp"),
) -> PaginatedResponse[AlertResponse]:
    """List paginated alerts with optional filters."""
    return await service.get_alerts(
        limit=limit,
        offset=offset,
        event_id=event_id,
        priority=priority,
        notification_status=notification_status,
        asset=asset,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )


@router.get("/{alert_id}", response_model=AlertResponse, summary="Get alert by ID")
async def get_alert(
    alert_id: str,
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> AlertResponse:
    """Retrieve a single alert by alert_id."""
    alert = await service.get_alert(alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID '{alert_id}' not found",
        )
    return alert
