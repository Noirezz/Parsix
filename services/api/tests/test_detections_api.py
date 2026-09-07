"""Unit tests for /api/v1/detections endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_detections(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/detections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_detections_filter_by_module_id(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/detections?module_id=spot-futures-spread")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["module_id"] == "spot-futures-spread"
    assert data["items"][0]["result_id"] == "det-1"


@pytest.mark.asyncio
async def test_list_detections_filter_by_status(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/detections?status=ANOMALY")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert item["status"] == "ANOMALY"


@pytest.mark.asyncio
async def test_list_detections_filter_by_asset(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/detections?asset=ETH")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["asset"] == "ETH"


@pytest.mark.asyncio
async def test_get_detection_by_id_success(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/detections/det-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["result_id"] == "det-1"
    assert data["event_id"] == "evt-1"
    assert data["module_id"] == "spot-futures-spread"
    assert data["asset"] == "BTC"
    assert float(data["metric_value"]) == 1.25
    assert float(data["threshold"]) == 1.00
    assert float(data["anomaly_ratio"]) == 1.25
    assert data["status"] == "ANOMALY"
    assert data["persistence"] == 1
    assert data["metadata"] == {"source": "BINANCE"}


@pytest.mark.asyncio
async def test_get_detection_by_id_not_found(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/detections/missing-detection")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
