"""Deterministic end-to-end integration tests for multi-source ingestion and spread anomaly detection."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import pytest

from made_core.application.aggregator import DefaultResultAggregator
from made_core.application.alerting import DefaultAlertGenerator
from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline
from made_core.application.priority import DefaultPriorityEvaluator
from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
)
from made_core.application.validator import NormalizedEventValidator
from made_core.domain.enums import EventSource, MarketType, Priority, ResultStatus
from made_core.domain.models import NormalizedEvent
from made_core.infrastructure.worker import SnapshotCache
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)
from made_core.modules.spot_futures_spread import (
    SpotFuturesSpreadConfig,
    SpotFuturesSpreadModule,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _build_full_core_pipeline() -> tuple[EventPipeline, AnomalyProcessingPipeline, SnapshotCache]:
    registry = InMemoryRuleRegistry()
    registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1.0"))))
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1.0"))))
    registry.register(FundingSpreadModule(FundingSpreadConfig(threshold=Decimal("0.0001"))))

    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)
    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()

    event_pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)
    anomaly_pipeline = AnomalyProcessingPipeline(
        aggregator=DefaultResultAggregator(),
        correlation_engine=DefaultCorrelationEngine(),
        priority_evaluator=DefaultPriorityEvaluator(),
        alert_generator=DefaultAlertGenerator(),
    )
    cache = SnapshotCache(freshness_ttl_seconds=300.0)
    return event_pipeline, anomaly_pipeline, cache


def test_e2e_multi_source_spot_futures_spread_anomaly():
    event_pipe, anom_pipe, cache = _build_full_core_pipeline()

    # Step 1: Binance Spot event arrives (100,000)
    evt_spot = NormalizedEvent(
        event_id="evt-spot-1",
        timestamp=TS,
        source=EventSource.BINANCE,
        market_type=MarketType.SPOT,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("100000"),
        bid=Decimal("99999"),
        ask=Decimal("100001"),
        volume=Decimal("50"),
    )
    cache.update_from_event(evt_spot)
    snaps1 = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)
    res1 = event_pipe.process_event(evt_spot, snapshots=snaps1)

    # SpotFuturesSpread has only 1 observation -> NORMAL (insufficient context)
    spot_res1 = [r for r in res1.detection_results if r.module_id == "spot-futures-spread"][0]
    assert spot_res1.status == ResultStatus.NORMAL

    # Step 2: Binance Futures event arrives (102,000 -> 2% spread)
    evt_fut = NormalizedEvent(
        event_id="evt-fut-1",
        timestamp=TS,
        source=EventSource.BINANCE,
        market_type=MarketType.FUTURES,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("102000"),
        bid=Decimal("101999"),
        ask=Decimal("102001"),
        volume=Decimal("80"),
    )
    cache.update_from_event(evt_fut)
    snaps2 = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)
    res2 = event_pipe.process_event(evt_fut, snapshots=snaps2)

    # SpotFuturesSpread now has BOTH Spot and Futures -> ANOMALY (spread = |100000-102000|/101000 * 100% = 1.98% >= 1.0%)
    spot_res2 = [r for r in res2.detection_results if r.module_id == "spot-futures-spread"][0]
    assert spot_res2.status == ResultStatus.ANOMALY
    assert spot_res2.metric_value > Decimal("1.0")

    # Downstream Anomaly Pipeline produces an Alert!
    alert = anom_pipe.process_pipeline_result(res2)
    assert alert is not None
    assert alert.priority in (Priority.MEDIUM, Priority.HIGH)
    assert "spot-futures-spread" in alert.triggered_modules


def test_e2e_multi_source_futures_futures_and_funding_spread_anomaly():
    event_pipe, anom_pipe, cache = _build_full_core_pipeline()

    # Step 1: Binance Futures arrives (price=101,000, funding=0.0001)
    evt_binance_fut = NormalizedEvent(
        event_id="evt-binance-fut",
        timestamp=TS,
        source=EventSource.BINANCE,
        market_type=MarketType.FUTURES,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("101000"),
        bid=Decimal("100999"),
        ask=Decimal("101001"),
        volume=Decimal("50"),
        metadata={"funding_rate": "0.0001"},
    )
    cache.update_from_event(evt_binance_fut)

    # Step 2: Bybit Futures arrives (price=103,500, funding=0.00035)
    evt_bybit_fut = NormalizedEvent(
        event_id="evt-bybit-fut",
        timestamp=TS,
        source=EventSource.BYBIT,
        market_type=MarketType.FUTURES,
        asset="BTC",
        symbol="BTCUSDT",
        price=Decimal("103500"),
        bid=Decimal("103499"),
        ask=Decimal("103501"),
        volume=Decimal("60"),
        metadata={"funding_rate": "0.00035"},
    )
    cache.update_from_event(evt_bybit_fut)
    snaps = cache.get_snapshots_for("BTC", "BTCUSDT", current_time=TS)

    res = event_pipe.process_event(evt_bybit_fut, snapshots=snaps)

    # 1. Futures-Futures spread: |101000 - 103500| / 102250 * 100% = 2.44% >= 1.0% -> ANOMALY
    ff_res = [r for r in res.detection_results if r.module_id == "futures-futures-spread"][0]
    assert ff_res.status == ResultStatus.ANOMALY

    # 2. Funding spread: |0.0001 - 0.00035| = 0.00025 >= 0.0001 -> ANOMALY
    funding_res = [r for r in res.detection_results if r.module_id == "funding-spread"][0]
    assert funding_res.status == ResultStatus.ANOMALY
    assert funding_res.metric_value == Decimal("0.00025")

    # Downstream aggregate combines both triggered modules
    alert = anom_pipe.process_pipeline_result(res)
    assert alert is not None
    assert "futures-futures-spread" in alert.triggered_modules
    assert "funding-spread" in alert.triggered_modules
    assert alert.priority in (Priority.MEDIUM, Priority.HIGH)
