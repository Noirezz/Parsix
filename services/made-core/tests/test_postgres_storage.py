"""Unit tests for PostgreSQL storage adapter, models, and idempotency."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from made_core.domain.enums import Priority, ResultStatus, ValidationStatus
from made_core.domain.models import (
    AggregatedResult,
    Alert,
    CorrelatedGroup,
    DetectionResult,
    PipelineExecutionResult,
    ValidationResult,
)
from made_core.infrastructure.config import InfrastructureConfig
fromメイド_postgres = None
from made_core.infrastructure.postgres.models import (
    AggregatedResultRecord,
    AlertRecord,
    Base,
    DetectionResultRecord,
    ProcessedEventRecord,
)
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_detection_result(
    result_id: str = "res-1",
    event_id: str = "evt-1",
    anomaly_ratio: Decimal = Decimal("2.5000000000"),
    status: ResultStatus = ResultStatus.ANOMALY,
) -> DetectionResult:
    return DetectionResult(
        result_id=result_id,
        event_id=event_id,
        module_id="futures-futures-spread",
        timestamp=TS,
        asset="BTC",
        metric_value=Decimal("2.5000000000"),
        threshold=Decimal("1.0000000000"),
        anomaly_ratio=anomaly_ratio,
        status=status,
        persistence=0,
        metadata={"detail": "test_spread"},
    )


def _make_aggregated_result(
    aggregation_id: str = "agg-1",
    asset: str = "BTC",
    priority: Priority = Priority.HIGH,
) -> AggregatedResult:
    r = _make_detection_result()
    group = CorrelatedGroup(
        correlation_id="corr-1",
        asset=asset,
        window_start=TS,
        window_end=TS,
        results=(r,),
    )
    return AggregatedResult(
        aggregation_id=aggregation_id,
        timestamp=TS,
        asset=asset,
        correlation_window=group,
        triggered_modules=("futures-futures-spread",),
        module_count=1,
        composite_anomaly_score=Decimal("2.5000000000"),
        max_anomaly_ratio=Decimal("2.5000000000"),
        average_anomaly_ratio=Decimal("2.5000000000"),
        priority=priority,
        source_results=(r,),
        metadata={"source": "test"},
    )



def _make_alert(
    alert_id: str = "alt-1",
    asset: str = "BTC",
    priority: Priority = Priority.HIGH,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        timestamp=TS,
        asset=asset,
        priority=priority,
        title=f"[{priority.value}] {asset} anomaly detected",
        summary=f"{asset} anomaly detected by 1 module(s).",
        anomaly_score=Decimal("2.5000000000"),
        triggered_modules=("futures-futures-spread",),
        details={"score": "2.5"},
    )


def test_postgres_config_defaults_and_url():
    config = InfrastructureConfig()
    assert config.postgres_host == "localhost"
    assert config.postgres_port == 5432
    assert config.postgres_database == "made"
    assert config.postgres_username == "postgres"
    assert config.postgres_password is None
    assert config.get_postgres_url(async_driver=True) == "postgresql+asyncpg://postgres@localhost:5432/made"
    assert config.get_postgres_url(async_driver=False) == "postgresql://postgres@localhost:5432/made"


def test_postgres_config_env_overrides():
    env_vars = {
        "MADE_POSTGRES_HOST": "pg.internal",
        "MADE_POSTGRES_PORT": "5433",
        "MADE_POSTGRES_DATABASE": "made_prod",
        "MADE_POSTGRES_USERNAME": "made_user",
        "MADE_POSTGRES_PASSWORD": "strongpassword",
    }
    with mock.patch.dict(os.environ, env_vars, clear=False):
        config = InfrastructureConfig()
        assert config.postgres_host == "pg.internal"
        assert config.postgres_port == 5433
        assert config.postgres_database == "made_prod"
        assert config.postgres_username == "made_user"
        assert config.postgres_password == "strongpassword"
        assert (
            config.get_postgres_url(async_driver=True)
            == "postgresql+asyncpg://made_user:strongpassword@pg.internal:5433/made_prod"
        )


def test_postgres_config_explicit_url():
    config = InfrastructureConfig(postgres_url="postgresql://user:pass@db:5432/db")
    assert config.get_postgres_url(async_driver=True) == "postgresql+asyncpg://user:pass@db:5432/db"
    assert config.get_postgres_url(async_driver=False) == "postgresql://user:pass@db:5432/db"


@pytest_asyncio.fixture
async def memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    adapter = PostgresStorageAdapter(engine=engine, session_factory=session_factory)
    yield adapter
    await adapter.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotency_tracking(memory_db: PostgresStorageAdapter):
    assert await memory_db.is_event_processed("evt-100") is False

    await memory_db.mark_event_processed("evt-100", "VALID")
    assert await memory_db.is_event_processed("evt-100") is True

    # Re-marking does not raise error and preserves idempotency
    await memory_db.mark_event_processed("evt-100", "VALID")
    assert await memory_db.is_event_processed("evt-100") is True


@pytest.mark.asyncio
async def test_save_detection_results_preserves_decimal_and_enums(memory_db: PostgresStorageAdapter):
    r1 = _make_detection_result(result_id="res-101", anomaly_ratio=Decimal("3.1415926535"))
    r2 = _make_detection_result(result_id="res-102", status=ResultStatus.NORMAL, anomaly_ratio=Decimal("0.5"))

    await memory_db.save_detection_results([r1, r2])

    async with memory_db._session_factory() as session:
        rec1 = await session.get(DetectionResultRecord, "res-101")
        assert rec1 is not None
        assert rec1.status == "ANOMALY"
        assert rec1.anomaly_ratio == Decimal("3.1415926535")
        assert rec1.timestamp.replace(tzinfo=UTC) == TS
        assert rec1.metadata_json == {"detail": "test_spread"}


        rec2 = await session.get(DetectionResultRecord, "res-102")
        assert rec2 is not None
        assert rec2.status == "NORMAL"


@pytest.mark.asyncio
async def test_save_aggregated_result_and_alert(memory_db: PostgresStorageAdapter):
    agg = _make_aggregated_result(aggregation_id="agg-201", priority=Priority.HIGH)
    alert = _make_alert(alert_id="alt-201", priority=Priority.HIGH)

    await memory_db.save_aggregated_result(agg)
    await memory_db.save_alert(alert)

    async with memory_db._session_factory() as session:
        agg_rec = await session.get(AggregatedResultRecord, "agg-201")
        assert agg_rec is not None
        assert agg_rec.priority == "HIGH"
        assert agg_rec.composite_anomaly_score == Decimal("2.5000000000")
        assert agg_rec.triggered_modules == ["futures-futures-spread"]

        alt_rec = await session.get(AlertRecord, "alt-201")
        assert alt_rec is not None
        assert alt_rec.priority == "HIGH"
        assert alt_rec.anomaly_score == Decimal("2.5000000000")
        assert alt_rec.details == {"score": "2.5"}


@pytest.mark.asyncio
async def test_persist_processing_result_atomic(memory_db: PostgresStorageAdapter):
    r = _make_detection_result(result_id="res-301", event_id="evt-301")
    val_res = ValidationResult(
        event_id="evt-301",
        status=ValidationStatus.VALID,
        errors=(),
        validated_event=None,
    )
    pipe_res = PipelineExecutionResult(
        event_id="evt-301",
        status=ValidationStatus.VALID,
        validation_result=val_res,
        enriched_event=None,
        detection_results=(r,),
    )
    alert = _make_alert(alert_id="alt-301")
    agg = _make_aggregated_result(aggregation_id="agg-301")

    await memory_db.persist_processing_result(pipe_res, alert=alert, aggregate=agg)

    assert await memory_db.is_event_processed("evt-301") is True

    async with memory_db._session_factory() as session:
        assert await session.get(DetectionResultRecord, "res-301") is not None
        assert await session.get(AggregatedResultRecord, "agg-301") is not None
        assert await session.get(AlertRecord, "alt-301") is not None


@pytest.mark.asyncio
async def test_persist_processing_result_rejects_none(memory_db: PostgresStorageAdapter):
    with pytest.raises(TypeError, match="pipeline_result must not be None"):
        await memory_db.persist_processing_result(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_alert_notification_status_lifecycle(memory_db: PostgresStorageAdapter):
    alert = _make_alert(alert_id="alt-lifecycle-1")
    await memory_db.save_alert(alert, event_id="evt-life-1", notification_status="PENDING")

    # Initial state
    rec = await memory_db.get_alert("alt-lifecycle-1")
    assert rec is not None
    assert rec.notification_status == "PENDING"
    assert rec.notification_attempts == 0
    assert rec.notified_at is None

    # Check pending query
    pending = await memory_db.get_pending_alert_for_event("evt-life-1")
    assert pending is not None
    assert pending.alert_id == "alt-lifecycle-1"

    # Mark failed
    await memory_db.mark_alert_failed("alt-lifecycle-1", "HTTP 500 Telegram Error")
    rec_failed = await memory_db.get_alert("alt-lifecycle-1")
    assert rec_failed is not None
    assert rec_failed.notification_status == "FAILED"
    assert rec_failed.notification_attempts == 1
    assert rec_failed.last_notification_error == "HTTP 500 Telegram Error"

    # Still pending/retryable
    pending_retry = await memory_db.get_pending_alert_for_event("evt-life-1")
    assert pending_retry is not None
    assert pending_retry.notification_status == "FAILED"

    # Mark sent
    await memory_db.mark_alert_sent("alt-lifecycle-1")
    rec_sent = await memory_db.get_alert("alt-lifecycle-1")
    assert rec_sent is not None
    assert rec_sent.notification_status == "SENT"
    assert rec_sent.notified_at is not None
    assert rec_sent.last_notification_error is None

    # No longer pending
    pending_done = await memory_db.get_pending_alert_for_event("evt-life-1")
    assert pending_done is None

