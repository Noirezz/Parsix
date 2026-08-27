"""Focused MADE modularity integration test.

Proves that independent real detection modules coexist and execute through
the same unchanged Rule Engine without module-specific branching:

  InMemoryRuleRegistry
         /     |      \\
        ▼      ▼       ▼
  futures-  spot-    funding-
  futures   futures  spread
         \\     |      /
          ▼    ▼    ▼
      RuleEngineExecutor → DetectionResult[]

Production Rule Engine components and all real modules are used as-is.
No module's detect() is invoked directly by these tests.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
)
from made_core.domain.enums import EventSource, MarketType, ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent, MarketContext, MarketSnapshot
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig, FuturesFuturesSpreadModule
from made_core.modules.spot_futures_spread import SpotFuturesSpreadConfig, SpotFuturesSpreadModule

FUTURES_FUTURES_MODULE_ID = "futures-futures-spread"
SPOT_FUTURES_MODULE_ID = "spot-futures-spread"
FUNDING_SPREAD_MODULE_ID = "funding-spread"


def _snapshot(
    timestamp,
    source: EventSource,
    price: Decimal,
    *,
    market_type: MarketType,
    funding_rate: Decimal | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp,
        source=source,
        market_type=market_type,
        asset="BTC",
        symbol="BTCUSDT",
        price=price,
        bid=price,
        ask=price,
        volume=Decimal("1"),
        funding_rate=funding_rate,
    )


def _event_applicable_to_both_modules(timestamp, normalized_event) -> EnrichedEvent:
    """Shared market context usable by both real spread modules.

    - Spot BINANCE + futures BYBIT → Spot + Futures module
    - Futures BYBIT + futures OKX → Futures + Futures module
    The BYBIT futures observation is reused by both modules.
    """
    snapshots = (
        _snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
        _snapshot(timestamp, EventSource.BYBIT, Decimal("103"), market_type=MarketType.FUTURES),
        _snapshot(timestamp, EventSource.OKX, Decimal("110"), market_type=MarketType.FUTURES),
    )
    return EnrichedEvent(
        event_id=normalized_event.event_id,
        timestamp=timestamp,
        asset="BTC",
        market_context=MarketContext.model_construct(
            asset="BTC",
            symbol="BTCUSDT",
            snapshots=snapshots,
            metadata={},
        ),
        normalized_data=normalized_event,
    )


def test_two_real_modules_coexist_through_unchanged_rule_engine(timestamp, normalized_event):
    futures_futures_module = FuturesFuturesSpreadModule(
        FuturesFuturesSpreadConfig(threshold=Decimal("1"))
    )
    spot_futures_module = SpotFuturesSpreadModule(
        SpotFuturesSpreadConfig(threshold=Decimal("1"))
    )

    registry = InMemoryRuleRegistry()
    registry.register(futures_futures_module)
    registry.register(spot_futures_module)

    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    assert isinstance(futures_futures_module, DetectionModule)
    assert isinstance(spot_futures_module, DetectionModule)
    assert registry.get_active_module_ids() == (
        FUTURES_FUTURES_MODULE_ID,
        SPOT_FUTURES_MODULE_ID,
    )
    assert loader.load(registry.get_active_module_ids()) == (
        futures_futures_module,
        spot_futures_module,
    )

    # Architectural property: the executor loop has no module-ID branching.
    executor_source = inspect.getsource(RuleEngineExecutor.execute)
    assert FUTURES_FUTURES_MODULE_ID not in executor_source
    assert SPOT_FUTURES_MODULE_ID not in executor_source
    assert "SpotFutures" not in executor_source
    assert "FuturesFutures" not in executor_source

    results = executor.execute(_event_applicable_to_both_modules(timestamp, normalized_event))

    assert len(results) == 2
    assert all(isinstance(result, DetectionResult) for result in results)

    # Registration order is preserved by the existing in-memory registry.
    assert tuple(result.module_id for result in results) == (
        FUTURES_FUTURES_MODULE_ID,
        SPOT_FUTURES_MODULE_ID,
    )

    futures_futures_result, spot_futures_result = results
    assert futures_futures_result.event_id == normalized_event.event_id
    assert spot_futures_result.event_id == normalized_event.event_id
    assert futures_futures_result.asset == "BTC"
    assert spot_futures_result.asset == "BTC"
    assert futures_futures_result.status in (ResultStatus.NORMAL, ResultStatus.ANOMALY)
    assert spot_futures_result.status in (ResultStatus.NORMAL, ResultStatus.ANOMALY)
    assert futures_futures_result.threshold == Decimal("1")
    assert spot_futures_result.threshold == Decimal("1")
    assert futures_futures_result.status is ResultStatus.ANOMALY
    assert spot_futures_result.status is ResultStatus.ANOMALY
    assert spot_futures_result.metadata["spotSource"] == "BINANCE"
    assert spot_futures_result.metadata["futuresSource"] == "BYBIT"


def test_funding_spread_coexists_through_unchanged_rule_engine(timestamp, normalized_event):
    """Proves that the funding-spread module executes alongside price-spread modules
    through the same unchanged Rule Engine without module-specific branching.

    The shared market context carries funding rates on futures snapshots:
    - Futures BYBIT + futures OKX → Futures + Futures module (price spread)
    - Futures BYBIT + futures OKX → Funding Spread module (funding rate spread)
    """
    futures_futures_module = FuturesFuturesSpreadModule(
        FuturesFuturesSpreadConfig(threshold=Decimal("1"))
    )
    spot_futures_module = SpotFuturesSpreadModule(
        SpotFuturesSpreadConfig(threshold=Decimal("1"))
    )
    funding_spread_module = FundingSpreadModule(
        FundingSpreadConfig(threshold=Decimal("0.001"))
    )

    registry = InMemoryRuleRegistry()
    registry.register(futures_futures_module)
    registry.register(spot_futures_module)
    registry.register(funding_spread_module)

    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)

    assert isinstance(funding_spread_module, DetectionModule)
    assert registry.get_active_module_ids() == (
        FUTURES_FUTURES_MODULE_ID,
        SPOT_FUTURES_MODULE_ID,
        FUNDING_SPREAD_MODULE_ID,
    )

    # Architectural property: the executor loop has no module-ID branching.
    executor_source = inspect.getsource(RuleEngineExecutor.execute)
    assert FUNDING_SPREAD_MODULE_ID not in executor_source
    assert "FundingSpread" not in executor_source

    snapshots = (
        _snapshot(timestamp, EventSource.BINANCE, Decimal("100"), market_type=MarketType.SPOT),
        _snapshot(timestamp, EventSource.BYBIT, Decimal("103"),
                  market_type=MarketType.FUTURES, funding_rate=Decimal("0.0001")),
        _snapshot(timestamp, EventSource.OKX, Decimal("110"),
                  market_type=MarketType.FUTURES, funding_rate=Decimal("0.002")),
    )
    event = EnrichedEvent(
        event_id=normalized_event.event_id,
        timestamp=timestamp,
        asset="BTC",
        market_context=MarketContext.model_construct(
            asset="BTC",
            symbol="BTCUSDT",
            snapshots=snapshots,
            metadata={},
        ),
        normalized_data=normalized_event,
    )

    results = executor.execute(event)

    assert len(results) == 3
    assert all(isinstance(result, DetectionResult) for result in results)

    # Registration order is preserved.
    assert tuple(result.module_id for result in results) == (
        FUTURES_FUTURES_MODULE_ID,
        SPOT_FUTURES_MODULE_ID,
        FUNDING_SPREAD_MODULE_ID,
    )

    funding_result = results[2]
    assert funding_result.event_id == normalized_event.event_id
    assert funding_result.asset == "BTC"
    # |0.0001 - 0.002| = 0.0019 >= 0.001 → ANOMALY
    assert funding_result.status is ResultStatus.ANOMALY
    assert funding_result.metric_value == Decimal("0.0019")
    assert funding_result.threshold == Decimal("0.001")
    assert funding_result.metadata["sources"] == ["BYBIT", "OKX"]
