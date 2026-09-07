"""Unit tests for /api/v1/modules endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_modules_returns_registered_mvp_modules(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/modules")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 4

    module_ids = {m["module_id"] for m in data}
    expected_ids = {
        "futures-futures-spread",
        "spot-futures-spread",
        "dex-futures-spread",
        "funding-spread",
    }
    assert module_ids == expected_ids

    for m in data:
        assert m["status"] == "active"
        assert len(m["description"]) > 0
        assert "threshold" in m
        assert "reference_price_mode" in m


@pytest.mark.asyncio
async def test_get_module_by_id_success(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/modules/futures-futures-spread")
    assert resp.status_code == 200
    data = resp.json()
    assert data["module_id"] == "futures-futures-spread"
    assert data["status"] == "active"
    assert "threshold" in data


@pytest.mark.asyncio
async def test_get_module_by_id_not_found(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/modules/non-existent-module")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_module_config_success(api_client: AsyncClient):
    resp = await api_client.put(
        "/api/v1/modules/futures-futures-spread/config",
        json={
            "threshold": 6.5,
            "status": "active",
            "reference_price_mode": "FIRST",
            "max_price_ratio": 2.5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["module_id"] == "futures-futures-spread"
    assert data["threshold"] == "6.50"
    assert data["reference_price_mode"] == "FIRST"
    assert data["max_price_ratio"] == "2.50"


@pytest.mark.asyncio
async def test_update_module_config_validation_error(api_client: AsyncClient):
    resp = await api_client.put(
        "/api/v1/modules/futures-futures-spread/config",
        json={
            "threshold": -1.0,
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_module_not_found(api_client: AsyncClient):
    resp = await api_client.put(
        "/api/v1/modules/unknown-module/config",
        json={
            "threshold": 5.0,
        },
    )
    assert resp.status_code == 404
