"""Unit tests for /api/v1/aggregates endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_aggregates(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/aggregates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_aggregates_filter_by_priority(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/aggregates?priority=HIGH")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["priority"] == "HIGH"
    assert data["items"][0]["aggregation_id"] == "agg-1"


@pytest.mark.asyncio
async def test_get_aggregate_by_id_success(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/aggregates/agg-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["aggregation_id"] == "agg-1"
    assert data["asset"] == "BTC"
    assert float(data["composite_anomaly_score"]) == 1.25
    assert data["priority"] == "HIGH"
    assert data["triggered_modules"] == ["spot-futures-spread"]
    assert "correlation_window" in data


@pytest.mark.asyncio
async def test_get_aggregate_by_id_not_found(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/aggregates/missing-aggregate")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
