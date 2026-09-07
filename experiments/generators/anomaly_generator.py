"""Controlled anomaly scenarios and ground truth generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from made_core.domain.enums import EventSource, MarketType, Priority
from made_core.domain.models import NormalizedEvent
from .synthetic_market_generator import SyntheticMarketGenerator


class ScenarioType(str, Enum):
    NORMAL = "normal"
    SPOT_FUTURES_SPREAD = "spot_futures_spread"
    FUTURES_FUTURES_SPREAD = "futures_futures_spread"
    DEX_FUTURES_SPREAD = "dex_futures_spread"
    FUNDING_SPREAD = "funding_spread"
    MULTIPLE_ANOMALIES = "multiple_anomalies"


@dataclass(frozen=True)
class GroundTruthScenario:
    """Ground truth metadata paired with synthetic event sequences."""

    scenario_id: str
    scenario_type: ScenarioType
    expected_anomaly: bool
    expected_modules: tuple[str, ...]
    expected_priority: Priority | None
    asset: str
    symbol: str
    trigger_event_id: str
    events: tuple[NormalizedEvent, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class AnomalyScenarioGenerator:
    """Generates controlled anomaly scenarios with verifiable ground truth."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._synth = SyntheticMarketGenerator(seed=seed)
        self._scenario_counter = 0

    def reset(self, seed: int | None = None) -> None:
        """Reset scenario generator."""
        if seed is not None:
            self._seed = seed
        self._synth.reset(self._seed)
        self._scenario_counter = 0

    def generate_normal_scenario(self, asset: str = "BTC") -> GroundTruthScenario:
        """Generate normal market events without anomalies."""
        self._scenario_counter += 1
        scen_id = f"scen_norm_{self._scenario_counter:04d}"
        base_price = Decimal("50000.00") if asset == "BTC" else Decimal("3000.00")

        e1 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.SPOT, price_override=base_price)
        e2 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.FUTURES, price_override=base_price * Decimal("1.0005"), funding_rate=Decimal("0.0001"))
        e3 = self._synth.generate_event(asset=asset, source=EventSource.BYBIT, market_type=MarketType.SPOT, price_override=base_price * Decimal("0.9998"))
        e4 = self._synth.generate_event(asset=asset, source=EventSource.BYBIT, market_type=MarketType.FUTURES, price_override=base_price * Decimal("1.0002"), funding_rate=Decimal("0.00012"))

        return GroundTruthScenario(
            scenario_id=scen_id,
            scenario_type=ScenarioType.NORMAL,
            expected_anomaly=False,
            expected_modules=(),
            expected_priority=None,
            asset=asset,
            symbol=f"{asset}USDT",
            trigger_event_id=e4.event_id,
            events=(e1, e2, e3, e4),
        )

    def generate_spot_futures_scenario(self, asset: str = "BTC", spread_pct: float = 4.0) -> GroundTruthScenario:
        """Generate spot vs futures spread anomaly on Binance."""
        self._scenario_counter += 1
        scen_id = f"scen_sf_{self._scenario_counter:04d}"
        base_price = Decimal("50000.00") if asset == "BTC" else Decimal("3000.00")
        fut_price = base_price * (Decimal("1") + Decimal(str(spread_pct)) / Decimal("100"))

        # 1. Establish spot baseline
        e1 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.SPOT, price_override=base_price)
        # 2. Trigger futures anomaly
        e2 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.FUTURES, price_override=fut_price)

        return GroundTruthScenario(
            scenario_id=scen_id,
            scenario_type=ScenarioType.SPOT_FUTURES_SPREAD,
            expected_anomaly=True,
            expected_modules=("spot-futures-spread",),
            expected_priority=Priority.HIGH if spread_pct >= 3.0 else Priority.MEDIUM,
            asset=asset,
            symbol=f"{asset}USDT",
            trigger_event_id=e2.event_id,
            events=(e1, e2),
            metadata={"spread_pct": spread_pct},
        )

    def generate_futures_futures_scenario(self, asset: str = "BTC", spread_pct: float = 5.0) -> GroundTruthScenario:
        """Generate cross-exchange futures anomaly (Binance vs Bybit)."""
        self._scenario_counter += 1
        scen_id = f"scen_ff_{self._scenario_counter:04d}"
        base_price = Decimal("50000.00") if asset == "BTC" else Decimal("3000.00")
        bybit_price = base_price * (Decimal("1") + Decimal(str(spread_pct)) / Decimal("100"))

        e1 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.FUTURES, price_override=base_price)
        e2 = self._synth.generate_event(asset=asset, source=EventSource.BYBIT, market_type=MarketType.FUTURES, price_override=bybit_price)

        return GroundTruthScenario(
            scenario_id=scen_id,
            scenario_type=ScenarioType.FUTURES_FUTURES_SPREAD,
            expected_anomaly=True,
            expected_modules=("futures-futures-spread",),
            expected_priority=Priority.HIGH if spread_pct >= 3.0 else Priority.MEDIUM,
            asset=asset,
            symbol=f"{asset}USDT",
            trigger_event_id=e2.event_id,
            events=(e1, e2),
            metadata={"spread_pct": spread_pct},
        )

    def generate_funding_scenario(self, asset: str = "BTC", diff: float = 0.15) -> GroundTruthScenario:
        """Generate funding rate spread anomaly between Binance and Bybit."""
        self._scenario_counter += 1
        scen_id = f"scen_fund_{self._scenario_counter:04d}"
        base_price = Decimal("50000.00") if asset == "BTC" else Decimal("3000.00")

        binance_fr = Decimal("0.08")
        bybit_fr = binance_fr - Decimal(str(diff))

        e1 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.FUTURES, price_override=base_price, funding_rate=binance_fr)
        e2 = self._synth.generate_event(asset=asset, source=EventSource.BYBIT, market_type=MarketType.FUTURES, price_override=base_price, funding_rate=bybit_fr)

        return GroundTruthScenario(
            scenario_id=scen_id,
            scenario_type=ScenarioType.FUNDING_SPREAD,
            expected_anomaly=True,
            expected_modules=("funding-spread",),
            expected_priority=Priority.HIGH if diff >= 0.1 else Priority.MEDIUM,
            asset=asset,
            symbol=f"{asset}USDT",
            trigger_event_id=e2.event_id,
            events=(e1, e2),
            metadata={"funding_diff": diff},
        )

    def generate_multiple_scenario(self, asset: str = "BTC") -> GroundTruthScenario:
        """Generate multi-module simultaneous anomaly (S/F spread + funding spread)."""
        self._scenario_counter += 1
        scen_id = f"scen_multi_{self._scenario_counter:04d}"
        base_price = Decimal("50000.00") if asset == "BTC" else Decimal("3000.00")
        fut_price = base_price * Decimal("1.045")  # 4.5% spread

        e1 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.SPOT, price_override=base_price)
        e2 = self._synth.generate_event(asset=asset, source=EventSource.BINANCE, market_type=MarketType.FUTURES, price_override=fut_price, funding_rate=Decimal("0.09"))
        e3 = self._synth.generate_event(asset=asset, source=EventSource.BYBIT, market_type=MarketType.FUTURES, price_override=fut_price, funding_rate=Decimal("-0.05"))

        return GroundTruthScenario(
            scenario_id=scen_id,
            scenario_type=ScenarioType.MULTIPLE_ANOMALIES,
            expected_anomaly=True,
            expected_modules=("spot-futures-spread", "funding-spread"),
            expected_priority=Priority.HIGH,
            asset=asset,
            symbol=f"{asset}USDT",
            trigger_event_id=e3.event_id,
            events=(e1, e2, e3),
        )

    def generate_dataset(
        self,
        total_scenarios: int = 100,
        anomaly_ratio: float = 0.3,
        assets: list[str] | None = None,
    ) -> tuple[list[NormalizedEvent], list[GroundTruthScenario]]:
        """Generate mixed dataset of normal and anomalous scenarios with full ground truth."""
        assets = assets or ["BTC", "ETH"]
        all_events: list[NormalizedEvent] = []
        scenarios: list[GroundTruthScenario] = []

        anomaly_count = int(total_scenarios * anomaly_ratio)
        normal_count = total_scenarios - anomaly_count

        generators = [
            self.generate_spot_futures_scenario,
            self.generate_futures_futures_scenario,
            self.generate_funding_scenario,
            self.generate_multiple_scenario,
        ]

        # Interleave normal and anomalies
        for i in range(total_scenarios):
            asset = assets[i % len(assets)]
            if i < anomaly_count:
                gen_fn = generators[i % len(generators)]
                scen = gen_fn(asset=asset)
            else:
                scen = self.generate_normal_scenario(asset=asset)

            scenarios.append(scen)
            all_events.extend(scen.events)

        return all_events, scenarios
