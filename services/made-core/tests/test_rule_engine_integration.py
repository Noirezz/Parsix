"""End-to-end Rule Engine integration tests for MADE Core.

Verifies:
  EnrichedEvent → RuleRegistry → ModuleLoader → RuleExecutor
  → FuturesFuturesSpreadModule → DetectionResult

Production Rule Engine and module implementations are used as-is.
Tests never invoke FuturesFuturesSpreadModule.detect directly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
    UnknownModuleError,
)
from made_core.domain.enums import EventSource, MarketType, ReferencePriceMode, ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent, MarketContext, MarketSnapshot
from made_core.modules.dex_futures_spread import DexFuturesSpreadConfig, DexFuturesSpreadModule
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig, FuturesFuturesSpreadModule
from made_core.modules.spot_futures_spread import SpotFuturesSpreadConfig, SpotFuturesSpreadModule

MODULE_ID = "futures-futures-spread"
SPOT_FUTURES_MODULE_ID = "spot-futures-spread"
DEX_FUTURES_MODULE_ID = "dex-futures-spread"
FUNDING_SPREAD_MODULE_ID = "funding-spread"



def _snapshot(
    timestamp,
    source: EventSource,
    price: Decimal,
    *,
    symbol: str = "BTCUSDT",
    market_type: MarketType = MarketType.FUTURES,
    funding_rate: Decimal | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp,
        source=source,
        market_type=market_type,
        asset="BTC",
        symbol=symbol,
        price=price,
        bid=price,
        ask=price,
        volume=Decimal("1"),
        funding_rate=funding_rate,
    )


def _enriched_event(timestamp, normalized_event, snapshots: tuple[MarketSnapshot, ...]) -> EnrichedEvent:
    context = MarketContext.model_construct(
        asset="BTC",
        symbol="BTCUSDT",
        snapshots=snapshots,
        metadata={},
    )
    return EnrichedEvent(
        event_id=normalized_event.event_id,
        timestamp=timestamp,
        asset="BTC",
        market_context=context,
        normalized_data=normalized_event,
    )


def _build_engine(
    config: FuturesFuturesSpreadConfig | None = None,
) -> tuple[InMemoryRuleRegistry, RegistryModuleLoader, RuleEngineExecutor, FuturesFuturesSpreadModule]:
    registry = InMemoryRuleRegistry()
    module = FuturesFuturesSpreadModule(config or FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    registry.register(module)
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)
    return registry, loader, executor, module


class _StubCompanionModule(DetectionModule):
    """Minimal test-only companion used solely to prove sequential multi-module execution."""

    def __init__(self, module_id: str = "companion-stub") -> None:
        self._module_id = module_id

    def get_module_id(self) -> str:
        return self._module_id

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        return DetectionResult(
            result_id=f"{event.event_id}:{self._module_id}",
            event_id=event.event_id,
            module_id=self._module_id,
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=Decimal("0"),
            threshold=Decimal("1"),
            anomaly_ratio=Decimal("0"),
            status=ResultStatus.NORMAL,
            persistence=0,
        )


def test_normal_spread_through_rule_engine(timestamp, normalized_event):
    _, _, executor, _ = _build_engine(FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("100.5")),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 1
    result = results[0]
    assert result.module_id == MODULE_ID
    assert result.status is ResultStatus.NORMAL
    assert result.metric_value < result.threshold


def test_anomalous_spread_through_rule_engine(timestamp, normalized_event):
    _, _, executor, _ = _build_engine(FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("103")),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 1
    result = results[0]
    assert result.module_id == MODULE_ID
    assert result.status is ResultStatus.ANOMALY
    expected_spread = abs(Decimal("100") - Decimal("103")) / (
        (Decimal("100") + Decimal("103")) / Decimal("2")
    ) * Decimal("100")
    assert result.metric_value == expected_spread
    assert result.metric_value > result.threshold


def test_threshold_boundary_is_anomaly_through_rule_engine(timestamp, normalized_event):
    _, _, executor, _ = _build_engine(
        FuturesFuturesSpreadConfig(threshold=Decimal("1"), reference_price_mode=ReferencePriceMode.FIRST)
    )
    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("101")),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 1
    assert results[0].module_id == MODULE_ID
    assert results[0].metric_value == Decimal("1")
    assert results[0].status is ResultStatus.ANOMALY


def test_insufficient_context_through_rule_engine(timestamp, normalized_event):
    _, _, executor, _ = _build_engine(FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    event = _enriched_event(
        timestamp,
        normalized_event,
        (_snapshot(timestamp, EventSource.BINANCE, Decimal("100")),),
    )

    results = executor.execute(event)

    assert len(results) == 1
    result = results[0]
    assert result.module_id == MODULE_ID
    assert result.status is ResultStatus.NORMAL
    assert result.metadata["insufficientContextReason"] == "insufficient_futures_context"


def test_rule_engine_returns_module_detection_result_identity(timestamp, normalized_event, monkeypatch):
    registry, loader, executor, module = _build_engine(FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("101")),
        ),
    )

    produced: list[DetectionResult] = []
    original_detect = module.detect

    def recording_detect(enriched: EnrichedEvent) -> DetectionResult:
        result = original_detect(enriched)
        produced.append(result)
        return result

    monkeypatch.setattr(module, "detect", recording_detect)

    results = executor.execute(event)

    assert registry.contains(MODULE_ID)
    assert loader.load((MODULE_ID,)) == (module,)
    assert len(produced) == 1
    assert len(results) == 1
    assert results[0] is produced[0]


def test_module_is_resolved_through_registry_loader_and_executor(timestamp, normalized_event):
    registry = InMemoryRuleRegistry()
    module = FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    registry.register(module)
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    assert registry.get_active_module_ids() == (MODULE_ID,)
    assert registry.get(MODULE_ID) is module
    loaded = loader.load(registry.get_active_module_ids())
    assert loaded == (module,)

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("100.5")),
        ),
    )
    results = executor.execute(event)

    assert len(results) == 1
    assert results[0].module_id == MODULE_ID


def test_unregistered_module_cannot_be_loaded_through_module_loader():
    registry = InMemoryRuleRegistry()
    loader = RegistryModuleLoader(registry)

    with pytest.raises(UnknownModuleError, match=MODULE_ID):
        loader.load((MODULE_ID,))


def test_rule_engine_executes_real_module_and_stub_sequentially(timestamp, normalized_event):
    registry = InMemoryRuleRegistry()
    futures_module = FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1")))
    companion = _StubCompanionModule()
    registry.register(futures_module)
    registry.register(companion)
    executor = RuleEngineExecutor(registry, RegistryModuleLoader(registry))

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("103")),
        ),
    )

    results = executor.execute(event)

    assert tuple(result.module_id for result in results) == (MODULE_ID, "companion-stub")
    assert results[0].status is ResultStatus.ANOMALY
    assert results[1].status is ResultStatus.NORMAL


def test_spot_futures_module_executes_through_rule_engine(timestamp, normalized_event):
    registry = InMemoryRuleRegistry()
    module = SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1")))
    registry.register(module)
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    assert registry.get_active_module_ids() == (SPOT_FUTURES_MODULE_ID,)
    assert loader.load((SPOT_FUTURES_MODULE_ID,)) == (module,)

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.FUTURES),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 1
    assert results[0].module_id == SPOT_FUTURES_MODULE_ID
    assert results[0].status is ResultStatus.ANOMALY
    assert results[0].metadata["spotSource"] == "BINANCE"
    assert results[0].metadata["futuresSource"] == "BYBIT"


def test_rule_engine_executes_both_spread_modules_without_engine_changes(timestamp, normalized_event):
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1"))))
    registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1"))))
    executor = RuleEngineExecutor(registry, RegistryModuleLoader(registry))

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.FUTURES),
            _snapshot(timestamp, EventSource.OKX, Decimal("110"), market_type=MarketType.FUTURES),
        ),
    )

    results = executor.execute(event)

    assert tuple(result.module_id for result in results) == (MODULE_ID, SPOT_FUTURES_MODULE_ID)
    assert results[0].status is ResultStatus.ANOMALY
    assert results[1].status is ResultStatus.ANOMALY


def test_dex_futures_module_executes_through_rule_engine(timestamp, normalized_event):
    registry = InMemoryRuleRegistry()
    module = DexFuturesSpreadModule(DexFuturesSpreadConfig(threshold=Decimal("1")))
    registry.register(module)
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    assert registry.get_active_module_ids() == (DEX_FUTURES_MODULE_ID,)
    assert loader.load((DEX_FUTURES_MODULE_ID,)) == (module,)

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.UNISWAP, Decimal("100"), market_type=MarketType.DEX),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.FUTURES),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 1
    assert results[0].module_id == DEX_FUTURES_MODULE_ID
    assert results[0].status is ResultStatus.ANOMALY
    assert results[0].metadata["dexSource"] == "UNISWAP"
    assert results[0].metadata["futuresSource"] == "BYBIT"


def test_funding_spread_module_executes_through_rule_engine(timestamp, normalized_event):
    registry = InMemoryRuleRegistry()
    module = FundingSpreadModule(FundingSpreadConfig(threshold=Decimal("0.0005")))
    registry.register(module)
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    assert registry.get_active_module_ids() == (FUNDING_SPREAD_MODULE_ID,)
    assert loader.load((FUNDING_SPREAD_MODULE_ID,)) == (module,)

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("64000"),
                      funding_rate=Decimal("0.0001")),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("64050"),
                      funding_rate=Decimal("0.001")),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 1
    assert results[0].module_id == FUNDING_SPREAD_MODULE_ID
    assert results[0].status is ResultStatus.ANOMALY
    assert results[0].metric_value == Decimal("0.0009")
    assert results[0].metadata["sources"] == ["BINANCE", "BYBIT"]


def test_all_four_mvp_modules_execute_through_same_rule_engine(timestamp, normalized_event):
    """Proves that all four MVP detection modules coexist and execute through the
    same unchanged Rule Engine without module-specific branching."""
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1"))))
    registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1"))))
    registry.register(DexFuturesSpreadModule(DexFuturesSpreadConfig(threshold=Decimal("1"))))
    registry.register(FundingSpreadModule(FundingSpreadConfig(threshold=Decimal("0.001"))))
    executor = RuleEngineExecutor(registry, RegistryModuleLoader(registry))

    event = _enriched_event(
        timestamp,
        normalized_event,
        (
            _snapshot(timestamp, EventSource.BINANCE, Decimal("100"),
                      market_type=MarketType.SPOT),
            _snapshot(timestamp, EventSource.BYBIT, Decimal("103"),
                      market_type=MarketType.FUTURES, funding_rate=Decimal("0.0001")),
            _snapshot(timestamp, EventSource.OKX, Decimal("110"),
                      market_type=MarketType.FUTURES, funding_rate=Decimal("0.002")),
            _snapshot(timestamp, EventSource.UNISWAP, Decimal("100"),
                      market_type=MarketType.DEX),
        ),
    )

    results = executor.execute(event)

    assert len(results) == 4
    assert tuple(r.module_id for r in results) == (
        MODULE_ID,
        SPOT_FUTURES_MODULE_ID,
        DEX_FUTURES_MODULE_ID,
        FUNDING_SPREAD_MODULE_ID,
    )
    # All four modules produced valid DetectionResult instances.
    assert all(isinstance(r, DetectionResult) for r in results)
    # Funding spread: |0.0001 - 0.002| = 0.0019 >= 0.001 → ANOMALY
    assert results[3].status is ResultStatus.ANOMALY
    assert results[3].metric_value == Decimal("0.0019")
