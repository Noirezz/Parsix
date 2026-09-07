"""Deterministic integration test verifying PostgreSQL -> Repository -> QueryService -> FastAPI endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from made_api.main import create_app
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_real_postgres_e2e():
    """Verify live PostgreSQL container integration if Docker daemon is active."""
    import os
    cfg = InfrastructureConfig(
        postgres_host=os.environ.get("MADE_POSTGRES_HOST", "localhost"),
        postgres_port=int(os.environ.get("MADE_POSTGRES_PORT", "5432")),
        postgres_database=os.environ.get("MADE_POSTGRES_DATABASE", "made_db"),
        postgres_username=os.environ.get("MADE_POSTGRES_USERNAME", "made_user"),
        postgres_password=os.environ.get("MADE_POSTGRES_PASSWORD", "made_password"),
    )
    storage = PostgresStorageAdapter(config=cfg)

    # Check if database is accessible
    is_healthy = await storage.check_health()
    if not is_healthy:
        pytest.skip("PostgreSQL container is not reachable for integration test")

    app = create_app(storage=storage)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

        events_resp = await client.get("/api/v1/events")
        assert events_resp.status_code == 200
        assert "items" in events_resp.json()

    await storage.close()
