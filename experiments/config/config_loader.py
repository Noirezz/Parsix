"""Configuration loader and environment metadata collector for benchmarks."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class GenerationConfig(BaseModel):
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])
    base_prices: dict[str, float] = Field(default_factory=lambda: {"BTC": 50000.0, "ETH": 3000.0})
    volatility: float = 0.005
    spread_pct: float = 0.0005
    default_volume: float = 1.5
    tick_interval_ms: int = 10


class WorkloadConfig(BaseModel):
    default_event_count: int = 1000
    accuracy_event_count: int = 2000
    latency_event_counts: list[int] = Field(default_factory=lambda: [100, 1000, 5000])
    throughput_rates: list[int] = Field(default_factory=lambda: [10, 50, 100, 250, 500, 1000, 2000])
    duration_per_stage_seconds: float = 5.0
    trials: int = 3
    warmup_events: int = 50
    warmup_seconds: float = 2.0
    drain_seconds: float = 2.0
    saturation_threshold_ratio: float = 0.90
    max_allowed_backlog: int = 5


class IsolationConfig(BaseModel):
    redis_stream: str = "events:normalized"
    redis_consumer_group: str = "made-core-processors"
    dead_letter_stream: str = "events:dead-letter"
    use_mock_telegram: bool = True


class PathsConfig(BaseModel):
    results_raw: str = "experiments/results/raw"
    results_csv: str = "experiments/results/csv"
    results_summary: str = "experiments/results/summary"
    reports_figures: str = "experiments/reports/figures"


class BenchmarkConfig(BaseModel):
    seed: int = 42
    name: str = "master_thesis_evaluation"
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    workload: WorkloadConfig = Field(default_factory=WorkloadConfig)
    isolation: IsolationConfig = Field(default_factory=IsolationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


def load_benchmark_config(config_path: str | Path | None = None) -> BenchmarkConfig:
    """Load BenchmarkConfig from YAML file or return default."""
    if config_path is None:
        default_path = Path("experiments/config/benchmark_config.yaml")
        if default_path.exists():
            config_path = default_path

    if config_path is not None and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}
            
        exp_section = raw_data.get("experiment", {})
        return BenchmarkConfig(
            seed=exp_section.get("seed", 42),
            name=exp_section.get("name", "master_thesis_evaluation"),
            generation=GenerationConfig(**raw_data.get("generation", {})),
            workload=WorkloadConfig(**raw_data.get("workload", {})),
            isolation=IsolationConfig(**raw_data.get("isolation", {})),
            paths=PathsConfig(**raw_data.get("paths", {})),
        )

    return BenchmarkConfig()


def get_environment_metadata() -> dict[str, Any]:
    """Capture reproducible system and runtime metadata."""
    git_commit = "unknown"
    git_branch = "unknown"
    git_clean = False
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            git_commit = res.stdout.strip()
        res_b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=3)
        if res_b.returncode == 0:
            git_branch = res_b.stdout.strip()
        res_s = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=3)
        if res_s.returncode == 0:
            git_clean = len(res_s.stdout.strip()) == 0
    except Exception:
        pass

    docker_ver = "unavailable"
    docker_compose_ver = "unavailable"
    try:
        d_res = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=3)
        if d_res.returncode == 0:
            docker_ver = d_res.stdout.strip()
        dc_res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=3)
        if dc_res.returncode == 0:
            docker_compose_ver = dc_res.stdout.strip()
    except Exception:
        pass

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "git": {
            "commit": git_commit,
            "branch": git_branch,
            "is_clean": git_clean,
        },
        "docker": {
            "version": docker_ver,
            "compose_version": docker_compose_ver,
        },
    }
