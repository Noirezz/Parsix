"""Throughput and capacity benchmark runner with strict rate pacing and live pipeline support (V3.0)."""

from __future__ import annotations

import asyncio
import csv
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

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
from made_core.infrastructure.postgres.models import ProcessedEventRecord
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


class ThroughputBenchmarkRunner:
    """Evaluates sustained event throughput across stepped load rates with strict trial isolation."""

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

    async def _get_trial_db_count(self, storage: PostgresStorageAdapter, trial_prefix: str) -> int:
        """Query count of specifically injected benchmark events matching trial_prefix in PostgreSQL."""
        async with storage._session_factory() as sess:
            stmt = select(func.count()).select_from(ProcessedEventRecord).where(
                ProcessedEventRecord.event_id.like(f"{trial_prefix}%")
            )
            res = await sess.execute(stmt)
            return res.scalar_one() or 0

    def run_in_memory(
        self,
        event_count: int = 5000,
        trials: int = 3,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """MODE A: Measure pure CPU in-memory processing capacity of the Rule Engine (no network/DB)."""
        active_seed = seed if seed is not None else self._config.seed
        trial_results: list[dict[str, Any]] = []

        for trial in range(trials):
            gen = SyntheticMarketGenerator(seed=active_seed + trial * 100)
            events = gen.generate_stream(count=event_count)

            snapshots_accum: list[MarketSnapshot] = []
            processed_count = 0
            detection_count = 0
            alert_count = 0

            t0 = time.perf_counter()
            for evt in events:
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
                pipe_res = self._pipeline.process_event(evt, tuple(snapshots_accum[-10:]))
                snapshots_accum.append(snap)
                processed_count += 1
                detection_count += len(pipe_res.detection_results)

                anoms = [r for r in pipe_res.detection_results if r.status is ResultStatus.ANOMALY]
                if anoms:
                    agg = self._aggregator.aggregate(anoms)
                    if agg:
                        alert = self._alert_generator.generate(agg)
                        if alert:
                            alert_count += 1

            t1 = time.perf_counter()
            elapsed = max(0.00001, t1 - t0)
            capacity_eps = processed_count / elapsed

            trial_results.append({
                "trial": trial + 1,
                "seed": active_seed + trial * 100,
                "processed_events": processed_count,
                "duration_seconds": round(elapsed, 4),
                "core_capacity_eps": round(capacity_eps, 2),
                "detections_generated": detection_count,
                "alerts_generated": alert_count,
            })

        avg_capacity = sum(t["core_capacity_eps"] for t in trial_results) / len(trial_results)

        result_payload = {
            "experiment": "core_engine_throughput_capacity",
            "mode": "in-memory",
            "methodology_version": "3.0-independent-audit",
            "metric_description": "Pure in-memory CPU processing capacity of Core Rule Engine without Redis or PostgreSQL I/O.",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": get_environment_metadata(),
            "config": {
                "seed": active_seed,
                "event_count": event_count,
                "trials": trials,
            },
            "summary": {
                "mean_core_capacity_eps": round(avg_capacity, 2),
                "min_core_capacity_eps": min(t["core_capacity_eps"] for t in trial_results),
                "max_core_capacity_eps": max(t["core_capacity_eps"] for t in trial_results),
            },
            "trials": trial_results,
        }

        self._export_results(result_payload, "core_capacity")
        return result_payload

    async def run_live(
        self,
        rates: list[int] | None = None,
        duration_per_stage: float = 5.0,
        trials: int = 1,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """MODE B: Measure sustained throughput of live containerized pipeline with strict trial isolation."""
        import redis.asyncio as aioredis
        target_rates = rates or [10, 50, 100]
        active_seed = seed if seed is not None else self._config.seed
        drain_sec = self._config.workload.drain_seconds

        pg_cfg = InfrastructureConfig(
            postgres_host="localhost",
            postgres_port=5432,
            postgres_database="made_db",
            postgres_username="made_user",
            postgres_password="made_password",
        )
        storage = PostgresStorageAdapter(config=pg_cfg)
        r_client = aioredis.from_url("redis://localhost:6379/0")

        stage_results: list[dict[str, Any]] = []

        try:
            for rate in target_rates:
                trial_stats: list[dict[str, Any]] = []

                for trial in range(trials):
                    trial_id = f"tput-{rate}eps-tr{trial+1}-{uuid.uuid4().hex[:6]}"
                    trial_prefix = f"bench-{trial_id}-"
                    trial_seed = active_seed + trial * 50
                    gen = SyntheticMarketGenerator(seed=trial_seed)
                    total_events = int(rate * duration_per_stage)

                    stream_key = self._config.isolation.redis_stream
                    cgroup = self._config.isolation.redis_consumer_group

                    # 1. Verify clean trial state
                    initial_pending = 0
                    try:
                        pending_info = await r_client.xpending(stream_key, cgroup)
                        initial_pending = pending_info.get("pending", 0) if isinstance(pending_info, dict) else (pending_info[0] if isinstance(pending_info, tuple) else 0)
                    except Exception:
                        pass

                    published_count = 0
                    t_start = time.perf_counter()

                    # 2. Monotonic deadline paced injection
                    for i in range(total_events):
                        target_deadline = t_start + (i + 1) / float(rate)
                        event_id = f"{trial_prefix}{i:05d}"
                        evt = gen.generate_event(
                            asset="BTC" if i % 2 == 0 else "ETH",
                            metadata={"benchmark_trial_id": trial_id, "offered_rate": rate},
                        )

                        payload = {
                            "eventId": event_id,
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
                        await r_client.xadd(stream_key, payload)
                        published_count += 1

                        now = time.perf_counter()
                        sleep_dur = target_deadline - now
                        if sleep_dur > 0.0001:
                            await asyncio.sleep(sleep_dur)

                    t_inj_end = time.perf_counter()
                    inj_duration_s = t_inj_end - t_start
                    actual_offered_rate_eps = published_count / max(0.001, inj_duration_s)

                    # Count steady state processed during injection
                    steady_state_persisted = await self._get_trial_db_count(storage, trial_prefix)
                    steady_state_throughput_eps = steady_state_persisted / max(0.001, inj_duration_s)

                    # 3. Dynamic Bounded Drain Phase
                    t_drain_start = time.perf_counter()
                    persisted_during_trial = steady_state_persisted
                    t_last_processed = t_inj_end

                    for _ in range(int(drain_sec * 20)):  # Poll every 50ms up to drain_sec
                        persisted_during_trial = await self._get_trial_db_count(storage, trial_prefix)
                        if persisted_during_trial >= published_count:
                            t_last_processed = time.perf_counter()
                            break
                        await asyncio.sleep(0.05)
                        t_last_processed = time.perf_counter()

                    actual_drain_duration_s = t_last_processed - t_inj_end
                    total_completion_duration_s = t_last_processed - t_start
                    completion_throughput_eps = persisted_during_trial / max(0.001, total_completion_duration_s)

                    # Final backlog check
                    try:
                        pending_info = await r_client.xpending(stream_key, cgroup)
                        final_pending = pending_info.get("pending", 0) if isinstance(pending_info, dict) else (pending_info[0] if isinstance(pending_info, tuple) else 0)
                    except Exception:
                        final_pending = 0

                    pending_growth = max(0, final_pending - initial_pending)
                    loss_count = max(0, published_count - persisted_during_trial)
                    loss_pct = (loss_count / published_count) * 100.0 if published_count > 0 else 0.0
                    throughput_ratio = completion_throughput_eps / float(rate) if rate > 0 else 1.0

                    # 4. Formal 3-state classification
                    if (throughput_ratio >= self._config.workload.saturation_threshold_ratio) and (loss_count == 0) and (pending_growth <= self._config.workload.max_allowed_backlog):
                        classification = "SUSTAINABLE"
                        sustainable = True
                        saturated = False
                    elif (throughput_ratio < self._config.workload.saturation_threshold_ratio) or (pending_growth > self._config.workload.max_allowed_backlog) or (loss_count > 0):
                        classification = "SATURATED"
                        sustainable = False
                        saturated = True
                    else:
                        classification = "INCONCLUSIVE"
                        sustainable = False
                        saturated = False

                    trial_stats.append({
                        "trial": trial + 1,
                        "trial_id": trial_id,
                        "offered_rate_eps": rate,
                        "actual_injection_rate_eps": round(actual_offered_rate_eps, 2),
                        "injected_events": published_count,
                        "persisted_events": persisted_during_trial,
                        "lost_events": loss_count,
                        "loss_percentage": round(loss_pct, 2),
                        "injection_duration_s": round(inj_duration_s, 3),
                        "actual_drain_duration_s": round(actual_drain_duration_s, 3),
                        "total_completion_duration_s": round(total_completion_duration_s, 3),
                        "steady_state_throughput_eps": round(steady_state_throughput_eps, 2),
                        "completion_throughput_eps": round(completion_throughput_eps, 2),
                        "throughput_ratio": round(throughput_ratio, 4),
                        "redis_pending_end": final_pending,
                        "classification": classification,
                        "sustainable": sustainable,
                        "saturated": saturated,
                    })

                avg_completion_tput = sum(t["completion_throughput_eps"] for t in trial_stats) / len(trial_stats)
                avg_steady_tput = sum(t["steady_state_throughput_eps"] for t in trial_stats) / len(trial_stats)
                all_sustainable = all(t["sustainable"] for t in trial_stats)
                any_saturated = any(t["saturated"] for t in trial_stats)

                stage_results.append({
                    "target_offered_rate_eps": rate,
                    "mean_steady_state_throughput_eps": round(avg_steady_tput, 2),
                    "mean_completion_throughput_eps": round(avg_completion_tput, 2),
                    "classification": "SUSTAINABLE" if all_sustainable else ("SATURATED" if any_saturated else "INCONCLUSIVE"),
                    "sustainable": all_sustainable,
                    "saturated": any_saturated,
                    "trials": trial_stats,
                })
        finally:
            await r_client.aclose()
            await storage.close()

        highest_sustainable = 0
        saturation_point = None
        for st in stage_results:
            if st["sustainable"]:
                highest_sustainable = st["target_offered_rate_eps"]
            elif st["saturated"] and saturation_point is None:
                saturation_point = st["target_offered_rate_eps"]

        result_payload = {
            "experiment": "live_streaming_throughput",
            "mode": "live",
            "methodology_version": "3.0-independent-audit",
            "metric_description": "Live containerized pipeline throughput measured via rate-controlled Redis injection and isolated PostgreSQL persistence confirmation.",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": get_environment_metadata(),
            "config": {
                "seed": active_seed,
                "rates": target_rates,
                "duration_per_stage": duration_per_stage,
                "trials": trials,
                "drain_seconds": drain_sec,
            },
            "conclusions": {
                "highest_sustainable_rate_eps": highest_sustainable,
                "first_observed_saturation_eps": saturation_point if saturation_point else "No saturation observed up to highest tested load",
            },
            "stages": stage_results,
        }

        self._export_results(result_payload, "live_throughput")
        return result_payload

    def run(
        self,
        rates: list[int] | None = None,
        duration_per_stage: float = 5.0,
        trials: int = 1,
        mode: str = "in-memory",
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Dispatch throughput benchmark based on selected mode."""
        if mode == "live":
            return asyncio.run(self.run_live(rates=rates, duration_per_stage=duration_per_stage, trials=trials, seed=seed))
        return self.run_in_memory(event_count=int((rates[0] if rates else 1000) * duration_per_stage), trials=trials, seed=seed)

    def _export_results(self, payload: dict[str, Any], prefix: str) -> None:
        """Export benchmark JSON artifacts."""
        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_dir = Path(self._config.paths.results_raw)
        raw_dir.mkdir(parents=True, exist_ok=True)

        json_file = raw_dir / f"{prefix}_{ts_slug}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
