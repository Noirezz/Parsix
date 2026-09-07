"""Security, CORS, and credential sanitization tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_cors_preflight_and_headers(api_client: AsyncClient):
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    resp = await api_client.options("/api/v1/events", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


@pytest.mark.asyncio
async def test_error_detail_does_not_leak_secrets(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events/some-missing-event")
    assert resp.status_code == 404
    body = resp.text.lower()
    assert "password" not in body
    assert "postgresql://" not in body
    assert "redis://" not in body
    assert "bot_token" not in body
