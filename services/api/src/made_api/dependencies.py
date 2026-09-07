"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from made_core.domain.interfaces import RuleRegistry
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter

from made_api.services.query_service import MadeQueryService


def get_storage(request: Request) -> PostgresStorageAdapter:
    """Retrieve PostgresStorageAdapter from FastAPI app state."""
    return request.app.state.storage


def get_rule_registry(request: Request) -> RuleRegistry | None:
    """Retrieve RuleRegistry from FastAPI app state."""
    return getattr(request.app.state, "rule_registry", None)


def get_query_service(
    storage: Annotated[PostgresStorageAdapter, Depends(get_storage)],
    registry: Annotated[RuleRegistry | None, Depends(get_rule_registry)],
) -> MadeQueryService:
    """Provide MadeQueryService initialized with app storage and registry."""
    return MadeQueryService(storage=storage, registry=registry)
