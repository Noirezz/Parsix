"""FastAPI application factory and lifecycle entrypoint for MADE REST API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from made_core.application.rule_engine import InMemoryRuleRegistry
from made_core.domain.interfaces import RuleRegistry
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.modules.dex_futures_spread import DexFuturesSpreadConfig, DexFuturesSpreadModule
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)
from made_core.modules.spot_futures_spread import (
    SpotFuturesSpreadConfig,
    SpotFuturesSpreadModule,
)

from made_api.config import ApiConfig
from made_api.routers import (
    aggregates_router,
    alerts_router,
    charts_router,
    detections_router,
    events_router,
    health_router,
    metrics_router,
    modules_router,
)

logger = logging.getLogger(__name__)


from decimal import Decimal

def create_default_rule_registry() -> RuleRegistry:
    """Create a RuleRegistry populated with the 4 MVP detection modules."""
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1.0"))))
    registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1.0"))))
    registry.register(DexFuturesSpreadModule(DexFuturesSpreadConfig(threshold=Decimal("2.0"))))
    registry.register(FundingSpreadModule(FundingSpreadConfig(threshold=Decimal("0.0001"))))
    return registry


def create_app(
    storage: PostgresStorageAdapter | None = None,
    registry: RuleRegistry | None = None,
    config: ApiConfig | None = None,
    infra_config: InfrastructureConfig | None = None,
) -> FastAPI:
    """Construct and configure the FastAPI application."""
    api_cfg = config or ApiConfig()
    infra_cfg = infra_config or InfrastructureConfig()

    owns_storage = storage is None
    storage_adapter = storage or PostgresStorageAdapter(config=infra_cfg)
    rule_registry = registry if registry is not None else create_default_rule_registry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.storage = storage_adapter
        app.state.rule_registry = rule_registry
        logger.info("MADE REST API started")
        try:
            yield
        finally:
            if owns_storage:
                await storage_adapter.close()
            logger.info("MADE REST API stopped")

    app = FastAPI(
        title=api_cfg.title,
        version=api_cfg.version,
        description=api_cfg.description,
        lifespan=lifespan,
    )

    # Configure CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Include API Routers
    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(detections_router)
    app.include_router(aggregates_router)
    app.include_router(alerts_router)
    app.include_router(modules_router)
    app.include_router(charts_router)
    app.include_router(metrics_router)

    # Expose state for direct references
    app.state.storage = storage_adapter
    app.state.rule_registry = rule_registry

    return app


# Default ASGI app instance
app = create_app()
