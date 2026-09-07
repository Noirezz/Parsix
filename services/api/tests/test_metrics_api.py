"""Unit tests for /api/v1/metrics endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_metrics(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/metrics")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_processed_events"] == 3
    assert data["total_detections"] == 3
    assert data["detections_by_status"] == {"ANOMALY": 2, "NORMAL": 1}
    assert data["detections_by_module"]["spot-futures-spread"] == 1
    assert data["detections_by_module"]["futures-futures-spread"] == 1
    assert data["detections_by_module"]["funding-spread"] == 1
    assert data["total_aggregates"] == 2
    assert data["total_alerts"] == 2
    assert data["alerts_by_priority"]["HIGH"] == 1
    assert data["alerts_by_priority"]["MEDIUM"] == 1
    assert data["alerts_by_notification_status"]["SENT"] == 1
    assert data["alerts_by_notification_status"]["PENDING"] == 1
