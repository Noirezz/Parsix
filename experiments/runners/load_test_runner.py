"""Multi-stage load and resource benchmark runner (V4.0)."""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.config.config_loader import BenchmarkConfig, get_environment_metadata
from experiments.metrics.collector import MetricsCollector
from experiments.runners.throughput_runner import ThroughputBenchmarkRunner


class LoadTestBenchmarkRunner:
    """Executes multi-stage stress load while sampling Docker container resource consumption."""

    def __init__(self, config: BenchmarkConfig | None = None) -> None:
        self._config = config or BenchmarkConfig()
        self._throughput_runner = ThroughputBenchmarkRunner(self._config)

    def run(
        self,
        rates: list[int] | None = None,
        duration_per_stage: float = 4.0,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Execute load test with periodic Docker resource polling."""
        collector = MetricsCollector()
        active_seed = seed if seed is not None else self._config.seed

        # Pre-load resource baseline
        collector.sample_docker_resources()

        tput_result = self._throughput_runner.run(
            rates=rates,
            duration_per_stage=duration_per_stage,
            seed=active_seed,
        )

        # Post-load resource sample
        resource_samples = collector.sample_docker_resources()
        stages_data = tput_result.get("stages", tput_result.get("trials", []))

        result_payload = {
            "experiment": "load_stress_benchmark",
            "methodology_version": "4.0-scientific-audit",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": get_environment_metadata(),
            "config": {
                "seed": active_seed,
                "duration_per_stage": duration_per_stage,
                "rates": rates or self._config.workload.throughput_rates,
            },
            "results": {
                "throughput_stages": stages_data,
                "resource_samples": [
                    {
                        "timestamp": s.timestamp,
                        "container": s.container_name,
                        "cpu_percent": s.cpu_percent,
                        "memory_mb": s.memory_usage_mb,
                    }
                    for s in resource_samples
                ],
            },
        }

        # Export JSON and CSV
        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_dir = Path(self._config.paths.results_raw)
        csv_dir = Path(self._config.paths.results_csv)
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_dir.mkdir(parents=True, exist_ok=True)

        json_file = raw_dir / f"load_test_{ts_slug}.json"
        csv_file = csv_dir / f"resource_samples_{ts_slug}.csv"

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2)

        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "container", "cpu_percent", "memory_mb"])
            for s in resource_samples:
                writer.writerow([s.timestamp, s.container_name, s.cpu_percent, s.memory_usage_mb])

        return result_payload
