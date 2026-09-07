"""Common reusable schemas for MADE REST API."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated container for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T] = Field(description="List of paginated items")
    total: int = Field(ge=0, description="Total number of items matching filter criteria")
    limit: int = Field(ge=1, le=100, description="Maximum number of items returned")
    offset: int = Field(ge=0, description="Number of skipped items")


class ErrorResponse(BaseModel):
    """Standard error response model."""

    detail: str = Field(description="Human-readable error explanation")
