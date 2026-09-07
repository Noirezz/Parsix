"""Unit tests for /api/v1/events endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_events_default_pagination(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] == 3
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["items"]) == 3
    assert data["items"][0]["event_id"] in ("evt-1", "evt-2", "evt-3")


@pytest.mark.asyncio
async def test_list_events_with_pagination(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events?limit=2&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_events_filter_by_status(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events?status=INVALID")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["event_id"] == "evt-3"
    assert data["items"][0]["status"] == "INVALID"


@pytest.mark.asyncio
async def test_list_events_filter_by_event_id(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events?event_id=evt-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_get_event_by_id_success(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events/evt-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["event_id"] == "evt-1"
    assert data["status"] == "COMPLETED"
    assert "processed_at" in data


@pytest.mark.asyncio
async def test_get_event_by_id_not_found(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/events/non-existent-event")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "not found" in data["detail"]


@pytest.mark.asyncio
async def test_list_events_invalid_pagination_parameters(api_client: AsyncClient):
    # limit < 1
    resp = await api_client.get("/api/v1/events?limit=0")
    assert resp.status_code == 422

    # offset < 0
    resp = await api_client.get("/api/v1/events?offset=-5")
    assert resp.status_code == 422
