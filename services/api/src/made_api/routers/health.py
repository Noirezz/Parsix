"""Health and readiness probe routers."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from made_api.dependencies import get_query_service
from made_api.services.query_service import MadeQueryService

router = APIRouter(tags=["health"])


@router.get("/health", summary="Basic service health probe")
async def health() -> dict[str, str]:
    """Lightweight liveness probe returning service status without external queries."""
    return {"status": "ok", "service": "made-api"}


@router.get("/ready", summary="Infrastructure readiness probe")
async def ready(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> Any:
    """Readiness probe checking PostgreSQL database connectivity."""
    is_ready = await service.check_ready()
    if is_ready:
        return {"status": "ready", "database": "connected"}
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unavailable", "database": "disconnected"},
    )
