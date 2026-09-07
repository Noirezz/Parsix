"""Operational metrics router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from made_api.dependencies import get_query_service
from made_api.schemas.metrics import MetricsResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse, summary="Get operational metrics")
async def get_metrics(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> MetricsResponse:
    """Retrieve operational totals and category breakdowns derived from PostgreSQL persistence."""
    return await service.get_metrics()
