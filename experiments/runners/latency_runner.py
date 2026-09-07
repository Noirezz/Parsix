"""Latency benchmark runner measuring core stage microseconds and live round-trip milliseconds (V3.0)."""

from __future__ import annotations

import asyncio
import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
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
from made_core.domain.models import MarketSnapshot, NormalizedEvent
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)
from made_core.modules.spot_futures_spread import (
    SpotFuturesSpreadConfig,
    SpotFuturesSpreadModule,
)

from experiments.config.config_loader import BenchmarkConfig, get_environment_metadata
from experiments.generators.synthetic_market_generator import SyntheticMarketGenerator
from experiments.metrics.statistics import calculate_statistics, pool_and_aggregate_latencies


class LatencyBenchmarkRunner:
    """Evaluates microsecond core processing latency and live controller-observed round-trip latency."""

    def __init__(self, config: BenchmarkConfig | None = None) -> None:
        self._config = config or BenchmarkConfig()

        self._registry = InMemoryRuleRegistry()
        self._registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1.0"))))
        self._registry.register(SpotFuturesSpreadModule(SpotFuturesSpreadConfig(threshold=Decimal("1.0"))))
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

    def run_in_memory(
        self,
        event_count: int = 1000,
        warmup_events: int = 50,
        trials: int = 3,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """MODE A: Measure in-memory stage latencies in microseconds with warm-up exclusion."""
        active_seed = seed if seed is not None else self._config.seed
        trial_summaries: list[dict[str, Any]] = []
        all_trials_core_samples: list[list[float]] = []

        for trial in range(trials):
            gen = SyntheticMarketGenerator(seed=active_seed + trial * 100)
            events = gen.generate_stream(count=event_count + warmup_events)

            snapshots_accum: list[MarketSnapshot] = []
            records: list[dict[str, float]] = []

            for i, evt in enumerate(events):
                t0 = time.perf_counter_ns()

                # Stage 1: Validation
                val_res = self._validator.validate(evt)
                t1 = time.perf_counter_ns()

                # Stage 2: Context Enrichment
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
                enriched = self._enricher.enrich(evt, tuple(snapshots_accum[-10:]))
                snapshots_accum.append(snap)
                t2 = time.perf_counter_ns()

                # Stage 3: Rule Engine Execution
                results = self._executor.execute(enriched)
                t3 = time.perf_counter_ns()

                # Stage 4: Result Aggregation & Correlation
                anoms = [r for r in results if r.status is ResultStatus.ANOMALY]
                if anoms:
                    agg = self._aggregator.aggregate(anoms)
                    if agg:
                        self._alert_generator.generate(agg)
                t4 = time.perf_counter_ns()

                # Exclude warm-up samples from steady state statistics
                if i >= warmup_events:
                    records.append({
                        "validation_us": (t1 - t0) / 1000.0,
                        "enrichment_us": (t2 - t1) / 1000.0,
                        "rule_engine_us": (t3 - t2) / 1000.0,
                        "aggregation_us": (t4 - t3) / 1000.0,
                        "core_total_us": (t4 - t0) / 1000.0,
                    })

            validation_stats = calculate_statistics([r["validation_us"] for r in records])
            enrichment_stats = calculate_statistics([r["enrichment_us"] for r in records])
            rule_engine_stats = calculate_statistics([r["rule_engine_us"] for r in records])
            aggregation_stats = calculate_statistics([r["aggregation_us"] for r in records])
            core_total_stats = calculate_statistics([r["core_total_us"] for r in records])

            core_samples = [r["core_total_us"] for r in records]
            all_trials_core_samples.append(core_samples)

            trial_summaries.append({
                "trial": trial + 1,
                "steady_state_samples": len(records),
                "warmup_excluded_samples": warmup_events,
                "stages_us": {
                    "validation_us": validation_stats.to_dict(),
                    "enrichment_us": enrichment_stats.to_dict(),
                    "rule_engine_us": rule_engine_stats.to_dict(),
                    "aggregation_us": aggregation_stats.to_dict(),
                    "core_total_us": core_total_stats.to_dict(),
                },
            })

        # Mathematically sound pooled summary across all trials
        pooled_summary = pool_and_aggregate_latencies(all_trials_core_samples)

        result_payload = {
            "experiment": "core_engine_stage_latency",
            "mode": "in-memory",
            "methodology_version": "3.0-independent-audit",
            "unit": "microseconds",
            "metric_description": "In-memory stage execution latency measured with process-local high-resolution monotonic clock (time.perf_counter_ns).",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": get_environment_metadata(),
            "config": {
                "seed": active_seed,
                "event_count": event_count,
                "warmup_events": warmup_events,
                "trials": trials,
            },
            "summary_core_total_us": pooled_summary.to_dict(),
            "trials": trial_summaries,
        }

        self._export_results(result_payload, "core_latency")
        return result_payload

    async def run_live(
        self,
        event_count: int = 50,
        warmup_events: int = 5,
        trials: int = 1,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """MODE B: Measure live controller-observed round-trip latency in milliseconds."""
        import redis.asyncio as aioredis
        active_seed = seed if seed is not None else self._config.seed

        pg_cfg = InfrastructureConfig(
            postgres_host="localhost",
            postgres_port=5432,
            postgres_database="made_db",
            postgres_username="made_user",
            postgres_password="made_password",
        )
        storage = PostgresStorageAdapter(config=pg_cfg)
        r_client = aioredis.from_url("redis://localhost:6379/0")

        trial_summaries: list[dict[str, Any]] = []

        try:
            for trial in range(trials):
                gen = SyntheticMarketGenerator(seed=active_seed + trial * 50)
                events = gen.generate_stream(count=event_count + warmup_events)

                pipeline_latencies_ms: list[float] = []
                api_request_latencies_ms: list[float] = []
                total_visibility_latencies_ms: list[float] = []

                for i, evt in enumerate(events):
                    stream_key = self._config.isolation.redis_stream
                    payload = {
                        "eventId": evt.event_id,
                        "timestamp": evt.timestamp.isoformat(),
                        "source": evt.source.value,
                        "marketType": evt.market_type.value,
                        "asset": evt.asset,
                        "symbol": evt.symbol,
                        "price": str(evt.price),
                        "bid": str(evt.bid),
                        "ask": str(evt.ask),
                        "volume": str(evt.volume),
                        "metadata": json.dumps(evt.metadata),
                    }

                    # 1. Controller-observed pipeline latency: publication -> DB confirmation
                    t0 = time.perf_counter()
                    await r_client.xadd(stream_key, payload)

                    persisted = False
                    for _ in range(50):
                        if await storage.is_event_processed(evt.event_id):
                            persisted = True
                            break
                        await asyncio.sleep(0.01)

                    t1 = time.perf_counter()
                    pipeline_e2e_ms = (t1 - t0) * 1000.0

                    # 2. REST API Request Round-Trip Latency
                    t_api_start = time.perf_counter()
                    api_ok = False
                    try:
                        req = urllib.request.Request(f"http://localhost:8000/api/v1/events/{evt.event_id}")
                        with urllib.request.urlopen(req, timeout=1.0) as resp:
                            if resp.status == 200:
                                api_ok = True
                    except Exception:
                        pass
                    t_api_end = time.perf_counter()
                    api_req_ms = (t_api_end - t_api_start) * 1000.0
                    total_vis_ms = (t_api_end - t0) * 1000.0

                    if i >= warmup_events and persisted:
                        pipeline_latencies_ms.append(pipeline_e2e_ms)
                        if api_ok:
                            api_request_latencies_ms.append(api_req_ms)
                            total_visibility_latencies_ms.append(total_vis_ms)

                pipe_stats = calculate_statistics(pipeline_latencies_ms)
                api_stats = calculate_statistics(api_request_latencies_ms)
                vis_stats = calculate_statistics(total_visibility_latencies_ms)

                trial_summaries.append({
                    "trial": trial + 1,
                    "steady_state_samples": len(pipeline_latencies_ms),
                    "warmup_excluded_samples": warmup_events,
                    "pipeline_persistence_latency_ms": pipe_stats.to_dict(),
                    "api_http_request_latency_ms": api_stats.to_dict(),
                    "total_event_visibility_latency_ms": vis_stats.to_dict(),
                })
        finally:
            await r_client.aclose()
            await storage.close()

        result_payload = {
            "experiment": "live_pipeline_roundtrip_latency",
            "mode": "live",
            "methodology_version": "3.0-independent-audit",
            "unit": "milliseconds",
            "metric_description": "Controller-observed round-trip latencies: 1) Pipeline persistence (Redis XADD -> PostgreSQL commit), 2) REST API HTTP request duration, 3) Total end-to-end event visibility.",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": get_environment_metadata(),
            "config": {
                "seed": active_seed,
                "event_count": event_count,
                "warmup_events": warmup_events,
                "trials": trials,
            },
            "trials": trial_summaries,
        }

        self._export_results(result_payload, "live_latency")
        return result_payload

    def run(
        self,
        event_count: int = 1000,
        warmup_events: int = 50,
        trials: int = 1,
        mode: str = "in-memory",
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Dispatch latency benchmark based on selected mode."""
        if mode == "live":
            return asyncio.run(self.run_live(event_count=min(event_count, 100), warmup_events=min(warmup_events, 10), trials=trials, seed=seed))
        return self.run_in_memory(event_count=event_count, warmup_events=warmup_events, trials=trials, seed=seed)

    def _export_results(self, payload: dict[str, Any], prefix: str) -> None:
        """Export benchmark JSON artifacts."""
        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_dir = Path(self._config.paths.results_raw)
        raw_dir.mkdir(parents=True, exist_ok=True)

        json_file = raw_dir / f"{prefix}_{ts_slug}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
