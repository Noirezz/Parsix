"""Unit tests for /health and /ready endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from made_api.main import create_app


@pytest.mark.asyncio
async def test_health_endpoint(api_client: AsyncClient):
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "made-api"
    # Ensure no secrets or connection strings are exposed
    assert "url" not in str(data).lower()
    assert "password" not in str(data).lower()


@pytest.mark.asyncio
async def test_ready_endpoint_healthy_database(api_client: AsyncClient):
    resp = await api_client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_ready_endpoint_unhealthy_database():
    class _FailingStorage:
        async def check_health(self) -> bool:
            return False

        async def close(self) -> None:
            pass

    app = create_app(storage=_FailingStorage()) # type: ignore
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["database"] == "disconnected"
