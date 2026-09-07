"""Detection results query router."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from made_api.dependencies import get_query_service
from made_api.schemas.common import PaginatedResponse
from made_api.schemas.detections import DetectionResultResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/detections", tags=["detections"])


@router.get("", response_model=PaginatedResponse[DetectionResultResponse], summary="List detection results")
async def list_detections(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
    limit: int = Query(default=50, ge=1, le=100, description="Max items to return (1-100)"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    event_id: str | None = Query(default=None, description="Filter by triggering event identifier"),
    module_id: str | None = Query(default=None, description="Filter by detection module identifier"),
    status: str | None = Query(default=None, description="Filter by detection status (NORMAL, ANOMALY)"),
    asset: str | None = Query(default=None, description="Filter by base asset (e.g. BTC)"),
    from_timestamp: datetime | None = Query(default=None, description="Filter detections on or after timestamp"),
    to_timestamp: datetime | None = Query(default=None, description="Filter detections on or before timestamp"),
) -> PaginatedResponse[DetectionResultResponse]:
    """List paginated detection results with optional filters."""
    return await service.get_detections(
        limit=limit,
        offset=offset,
        event_id=event_id,
        module_id=module_id,
        status=status,
        asset=asset,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )


@router.get("/{detection_id}", response_model=DetectionResultResponse, summary="Get detection result by ID")
async def get_detection(
    detection_id: str,
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> DetectionResultResponse:
    """Retrieve a single detection result by result_id."""
    detection = await service.get_detection(detection_id)
    if detection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Detection result with ID '{detection_id}' not found",
        )
    return detection
