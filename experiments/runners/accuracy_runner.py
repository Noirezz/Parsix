"""Detection accuracy benchmark runner."""

from __future__ import annotations

from decimal import Decimal

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from made_core.application.alerting import DefaultAlertGenerator
from made_core.application.aggregator import DefaultResultAggregator
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
from made_core.domain.enums import ResultStatus
from made_core.domain.models import MarketSnapshot
from made_core.modules.dex_futures_spread import DexFuturesSpreadModule
from made_core.modules.funding_spread import FundingSpreadModule
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadModule
from made_core.modules.spot_futures_spread import SpotFuturesSpreadModule

from experiments.config.config_loader import BenchmarkConfig, get_environment_metadata
from experiments.generators.anomaly_generator import AnomalyScenarioGenerator, GroundTruthScenario
from experiments.metrics.statistics import calculate_classification_metrics


class AccuracyBenchmarkRunner:
    """Evaluates detection accuracy against controlled ground truth scenarios."""

    def __init__(self, config: BenchmarkConfig | None = None) -> None:
        self._config = config or BenchmarkConfig()
        from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig
        from made_core.modules.spot_futures_spread import SpotFuturesSpreadConfig
        from made_core.modules.dex_futures_spread import DexFuturesSpreadConfig
        from made_core.modules.funding_spread import FundingSpreadConfig

        self._registry = InMemoryRuleRegistry()
        self._registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1.0"))))
        self._registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1.0"))))
        self._registry.register(DexFuturesSpreadModule(DexFuturesSpreadConfig(threshold=Decimal("1.5"))))
        self._registry.register(FundingSpreadModule(FundingSpreadConfig(threshold=Decimal("0.05"))))

        self._loader = RegistryModuleLoader(self._registry)
        self._executor = RuleEngineExecutor(self._registry, self._loader)
        self._validator = NormalizedEventValidator()
        self._enricher = DefaultContextEnricher()
        self._pipeline = EventPipeline(
            validator=self._validator,
            enricher=self._enricher,
            executor=self._executor,
        )

        self._correlation_engine = DefaultCorrelationEngine()
        self._priority_evaluator = DefaultPriorityEvaluator()
        self._aggregator = DefaultResultAggregator(
            priority_evaluator=self._priority_evaluator,
            correlation_engine=self._correlation_engine,
        )
        self._alert_generator = DefaultAlertGenerator()

    def run(self, total_scenarios: int = 100, seed: int | None = None) -> dict[str, Any]:
        """Execute accuracy benchmark on ground-truth dataset."""
        active_seed = seed if seed is not None else self._config.seed
        gen = AnomalyScenarioGenerator(seed=active_seed)
        events, scenarios = gen.generate_dataset(total_scenarios=total_scenarios, anomaly_ratio=0.4)

        # Track confusion matrix per module
        module_matrix: dict[str, dict[str, int]] = {
            "spot-futures-spread": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
            "futures-futures-spread": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
            "dex-futures-spread": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
            "funding-spread": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
            "system_aggregate": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
        }

        # Run each scenario through MADE Core pipeline
        for scen in scenarios:
            snapshots_accum: list[MarketSnapshot] = []
            trigger_pipeline_result = None

            for evt in scen.events:
                # Build snapshot from previous event
                snap = MarketSnapshot(
                    timestamp=evt.timestamp,
                    source=evt.source,
                    market_type=evt.market_type,
                    asset=evt.asset,
                    symbol=evt.symbol,
                    price=evt.price,
                    bid=evt.bid,
                    ask=evt.ask,
                    volume=evt.volume,
                    funding_rate=evt.metadata.get("funding_rate"),
                )
                
                # Execute pipeline for event with current accumulated snapshots
                pipe_res = self._pipeline.process_event(evt, tuple(snapshots_accum))
                snapshots_accum.append(snap)
                if evt.event_id == scen.trigger_event_id:
                    trigger_pipeline_result = pipe_res

            # Evaluate ground truth on trigger event
            if trigger_pipeline_result is not None:
                # 1. Per-module evaluation
                detected_modules = {
                    r.module_id: (r.status is ResultStatus.ANOMALY)
                    for r in trigger_pipeline_result.detection_results
                }

                for mod_id in ["spot-futures-spread", "futures-futures-spread", "dex-futures-spread", "funding-spread"]:
                    actual_anomaly = detected_modules.get(mod_id, False)
                    expected_mod_anomaly = mod_id in scen.expected_modules

                    if expected_mod_anomaly and actual_anomaly:
                        module_matrix[mod_id]["tp"] += 1
                    elif not expected_mod_anomaly and actual_anomaly:
                        module_matrix[mod_id]["fp"] += 1
                    elif not expected_mod_anomaly and not actual_anomaly:
                        module_matrix[mod_id]["tn"] += 1
                    elif expected_mod_anomaly and not actual_anomaly:
                        module_matrix[mod_id]["fn"] += 1

                # 2. System-level evaluation
                anom_results = [r for r in trigger_pipeline_result.detection_results if r.status is ResultStatus.ANOMALY]
                has_system_alert = False
                if anom_results:
                    agg = self._aggregator.aggregate(anom_results)
                    if agg is not None:
                        alert = self._alert_generator.generate(agg)
                        has_system_alert = alert is not None

                expected_system_anomaly = scen.expected_anomaly
                if expected_system_anomaly and has_system_alert:
                    module_matrix["system_aggregate"]["tp"] += 1
                elif not expected_system_anomaly and has_system_alert:
                    module_matrix["system_aggregate"]["fp"] += 1
                elif not expected_system_anomaly and not has_system_alert:
                    module_matrix["system_aggregate"]["tn"] += 1
                elif expected_system_anomaly and not has_system_alert:
                    module_matrix["system_aggregate"]["fn"] += 1

        # Calculate metrics
        computed_metrics: dict[str, Any] = {}
        for key, counts in module_matrix.items():
            metrics = calculate_classification_metrics(
                tp=counts["tp"],
                fp=counts["fp"],
                tn=counts["tn"],
                fn=counts["fn"],
            )
            computed_metrics[key] = metrics.to_dict()

        result_payload = {
            "experiment": "detection_accuracy",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": get_environment_metadata(),
            "config": {
                "seed": active_seed,
                "total_scenarios": total_scenarios,
                "total_events": len(events),
            },
            "results": {
                "modules": computed_metrics,
                "raw_matrix": module_matrix,
            },
        }

        # Save to results/raw
        out_dir = Path(self._config.paths.results_raw)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = out_dir / f"detection_accuracy_{ts_slug}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2)

        return result_payload
