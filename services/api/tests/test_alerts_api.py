"""Unit tests for /api/v1/alerts endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_alerts(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_alerts_filter_by_notification_status(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/alerts?notification_status=SENT")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["notification_status"] == "SENT"
    assert data["items"][0]["alert_id"] == "alt-1"


@pytest.mark.asyncio
async def test_list_alerts_filter_by_priority(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/alerts?priority=MEDIUM")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["priority"] == "MEDIUM"
    assert data["items"][0]["alert_id"] == "alt-2"


@pytest.mark.asyncio
async def test_get_alert_by_id_success(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/alerts/alt-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alert_id"] == "alt-1"
    assert data["event_id"] == "evt-1"
    assert data["asset"] == "BTC"
    assert data["priority"] == "HIGH"
    assert data["title"] == "Spot-Futures Spread Anomaly"
    assert data["notification_status"] == "SENT"
    assert data["notification_attempts"] == 1
    assert data["notified_at"] is not None


@pytest.mark.asyncio
async def test_get_alert_by_id_not_found(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/alerts/missing-alert")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
