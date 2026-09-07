"""Unit tests for /api/v1/charts/history endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient

from made_core.infrastructure.postgres.models import DetectionResultRecord
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter


@pytest.mark.asyncio
async def test_get_chart_history_empty(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/charts/history?asset=BTC&timeframe=1h")
    assert resp.status_code == 200
    data = resp.json()
    assert data["asset"] == "BTC"
    assert data["timeframe"] == "1h"
    assert data["points"] == []
    assert data["current_spread"] is None


@pytest.mark.asyncio
async def test_get_chart_history_with_points(api_client: AsyncClient, test_storage: PostgresStorageAdapter):
    now = datetime.now(UTC)
    records = [
        DetectionResultRecord(
            result_id="det-chart-1",
            event_id="evt-chart-1",
            module_id="futures-futures-spread",
            timestamp=now,
            asset="ETH",
            metric_value=Decimal("4.50"),
            threshold=Decimal("4.00"),
            anomaly_ratio=Decimal("1.125"),
            status="ANOMALY",
            persistence=1,
            metadata_json={
                "firstSource": "binance",
                "secondSource": "bybit",
                "firstPrice": "3100.00",
                "secondPrice": "3240.00",
                "firstSymbol": "ETHUSDT",
            },
        ),
        DetectionResultRecord(
            result_id="det-chart-2",
            event_id="evt-chart-2",
            module_id="futures-futures-spread",
            timestamp=now,
            asset="ETH",
            metric_value=Decimal("5.20"),
            threshold=Decimal("4.00"),
            anomaly_ratio=Decimal("1.30"),
            status="ANOMALY",
            persistence=2,
            metadata_json={
                "firstSource": "binance",
                "secondSource": "bybit",
                "firstPrice": "3100.00",
                "secondPrice": "3261.20",
                "firstSymbol": "ETHUSDT",
            },
        ),
    ]
    async with test_storage._session_factory() as sess:
        sess.add_all(records)
        await sess.commit()

    resp = await api_client.get(
        "/api/v1/charts/history?asset=ETH&symbol=ETHUSDT&module_id=futures-futures-spread&timeframe=1h"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["asset"] == "ETH"
    assert len(data["points"]) >= 2
    assert Decimal(str(data["current_spread"])) == Decimal("5.20")
    assert Decimal(str(data["max_spread"])) == Decimal("5.20")
    assert data["spread_duration_seconds"] is not None


@pytest.mark.asyncio
async def test_get_chart_history_invalid_timeframe(api_client: AsyncClient):
    resp = await api_client.get("/api/v1/charts/history?asset=BTC&timeframe=100y")
    assert resp.status_code == 422
