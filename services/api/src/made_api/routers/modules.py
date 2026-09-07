"""Detection module registry metadata router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from made_api.dependencies import get_query_service
from made_api.schemas.modules import ModuleConfigUpdateRequest, ModuleMetadataResponse
from made_api.services.query_service import MadeQueryService

router = APIRouter(prefix="/api/v1/modules", tags=["modules"])


@router.get("", response_model=list[ModuleMetadataResponse], summary="List registered detection modules")
async def list_modules(
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> list[ModuleMetadataResponse]:
    """List all currently active and registered detection modules from the Rule Engine."""
    return await service.get_modules()


@router.get("/{module_id}", response_model=ModuleMetadataResponse, summary="Get detection module configuration")
async def get_module(
    module_id: str,
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> ModuleMetadataResponse:
    """Retrieve metadata and current configuration for a specific detection module."""
    module = await service.get_module(module_id)
    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Detection module '{module_id}' not found",
        )
    return module


@router.put("/{module_id}/config", response_model=ModuleMetadataResponse, summary="Update module configuration")
@router.patch("/{module_id}", response_model=ModuleMetadataResponse, summary="Patch module configuration")
async def update_module(
    module_id: str,
    update_req: ModuleConfigUpdateRequest,
    service: Annotated[MadeQueryService, Depends(get_query_service)],
) -> ModuleMetadataResponse:
    """Update threshold, active status, reference price mode, or homonym ratio for a detection module."""
    updated = await service.update_module_config(module_id, update_req)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Detection module '{module_id}' not found",
        )
    return updated
