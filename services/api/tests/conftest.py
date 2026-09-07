"""Pytest configuration and fixtures for MADE REST API tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from made_core.application.rule_engine import InMemoryRuleRegistry
from made_core.domain.interfaces import RuleRegistry
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.models import (
    AggregatedResultRecord,
    AlertRecord,
    Base,
    DetectionResultRecord,
    ProcessedEventRecord,
)
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.modules.dex_futures_spread import DexFuturesSpreadConfig, DexFuturesSpreadModule
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)
from made_core.modules.spot_futures_spread import (
    SpotFuturesSpreadConfig,
    SpotFuturesSpreadModule,
)

from made_api.config import ApiConfig
from made_api.main import create_app

TS_BASE = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def create_test_rule_registry() -> RuleRegistry:
    """Create a RuleRegistry populated with the 4 MVP detection modules."""
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1.0"))))
    registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1.0"))))
    registry.register(DexFuturesSpreadModule(DexFuturesSpreadConfig(threshold=Decimal("2.0"))))
    registry.register(FundingSpreadModule(FundingSpreadConfig(threshold=Decimal("0.0001"))))
    return registry


@pytest_asyncio.fixture
async def test_storage() -> AsyncIterator[PostgresStorageAdapter]:
    """Provide an in-memory SQLite storage adapter populated with test schema and seed data."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = PostgresStorageAdapter(engine=engine, session_factory=session_factory)

    # Seed data
    async with session_factory() as sess:
        async with sess.begin():
            # 1. Processed Events
            sess.add_all([
                ProcessedEventRecord(event_id="evt-1", status="COMPLETED", processed_at=TS_BASE),
                ProcessedEventRecord(event_id="evt-2", status="COMPLETED", processed_at=TS_BASE + timedelta(seconds=10)),
                ProcessedEventRecord(event_id="evt-3", status="INVALID", processed_at=TS_BASE + timedelta(seconds=20)),
            ])

            # 2. Detection Results
            sess.add_all([
                DetectionResultRecord(
                    result_id="det-1",
                    event_id="evt-1",
                    module_id="spot-futures-spread",
                    timestamp=TS_BASE,
                    asset="BTC",
                    metric_value=Decimal("1.25"),
                    threshold=Decimal("1.00"),
                    anomaly_ratio=Decimal("1.25"),
                    status="ANOMALY",
                    persistence=1,
                    metadata_json={"source": "BINANCE"},
                ),
                DetectionResultRecord(
                    result_id="det-2",
                    event_id="evt-1",
                    module_id="futures-futures-spread",
                    timestamp=TS_BASE,
                    asset="BTC",
                    metric_value=Decimal("0.40"),
                    threshold=Decimal("1.00"),
                    anomaly_ratio=Decimal("0.40"),
                    status="NORMAL",
                    persistence=0,
                    metadata_json={"source": "BINANCE"},
                ),
                DetectionResultRecord(
                    result_id="det-3",
                    event_id="evt-2",
                    module_id="funding-spread",
                    timestamp=TS_BASE + timedelta(seconds=10),
                    asset="ETH",
                    metric_value=Decimal("0.00025"),
                    threshold=Decimal("0.00010"),
                    anomaly_ratio=Decimal("2.50"),
                    status="ANOMALY",
                    persistence=1,
                    metadata_json={"source": "BYBIT"},
                ),
            ])

            # 3. Aggregated Results
            sess.add_all([
                AggregatedResultRecord(
                    aggregation_id="agg-1",
                    timestamp=TS_BASE,
                    asset="BTC",
                    composite_anomaly_score=Decimal("1.25"),
                    max_anomaly_ratio=Decimal("1.25"),
                    average_anomaly_ratio=Decimal("1.25"),
                    priority="HIGH",
                    module_count=1,
                    triggered_modules=["spot-futures-spread"],
                    correlation_window={"window_seconds": 60},
                    metadata_json={"note": "high spread"},
                ),
                AggregatedResultRecord(
                    aggregation_id="agg-2",
                    timestamp=TS_BASE + timedelta(seconds=10),
                    asset="ETH",
                    composite_anomaly_score=Decimal("2.50"),
                    max_anomaly_ratio=Decimal("2.50"),
                    average_anomaly_ratio=Decimal("2.50"),
                    priority="MEDIUM",
                    module_count=1,
                    triggered_modules=["funding-spread"],
                    correlation_window={"window_seconds": 60},
                    metadata_json={"note": "funding divergence"},
                ),
            ])

            # 4. Alerts
            sess.add_all([
                AlertRecord(
                    alert_id="alt-1",
                    event_id="evt-1",
                    timestamp=TS_BASE,
                    asset="BTC",
                    priority="HIGH",
                    title="Spot-Futures Spread Anomaly",
                    summary="Spread 1.25% exceeded threshold 1.00%",
                    anomaly_score=Decimal("1.25"),
                    triggered_modules=["spot-futures-spread"],
                    details={"metric_value": "1.25"},
                    notification_status="SENT",
                    notification_attempts=1,
                    notified_at=TS_BASE + timedelta(seconds=2),
                    last_notification_error=None,
                    created_at=TS_BASE,
                ),
                AlertRecord(
                    alert_id="alt-2",
                    event_id="evt-2",
                    timestamp=TS_BASE + timedelta(seconds=10),
                    asset="ETH",
                    priority="MEDIUM",
                    title="Funding Rate Spread Anomaly",
                    summary="Funding spread 0.00025 exceeded threshold 0.0001",
                    anomaly_score=Decimal("2.50"),
                    triggered_modules=["funding-spread"],
                    details={"metric_value": "0.00025"},
                    notification_status="PENDING",
                    notification_attempts=0,
                    notified_at=None,
                    last_notification_error=None,
                    created_at=TS_BASE + timedelta(seconds=10),
                ),
            ])

    yield storage
    await storage.close()


@pytest_asyncio.fixture
async def api_client(test_storage: PostgresStorageAdapter) -> AsyncIterator[AsyncClient]:
    """Provide an AsyncClient making HTTP calls against the test FastAPI app."""
    registry = create_test_rule_registry()
    config = ApiConfig(cors_origins=["http://localhost:3000"])
    app = create_app(storage=test_storage, registry=registry, config=config)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
