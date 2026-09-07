"""Automated unit and component tests for MADE Experimental Evaluation Framework (V3.0)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from experiments.config.config_loader import BenchmarkConfig, get_environment_metadata, load_benchmark_config
from experiments.generators.anomaly_generator import AnomalyScenarioGenerator, ScenarioType
from experiments.generators.synthetic_market_generator import SyntheticMarketGenerator
from experiments.metrics.collector import MetricsCollector, StageLatencyRecord
from experiments.metrics.statistics import (
    ClassificationMetrics,
    StatisticalSummary,
    calculate_classification_metrics,
    calculate_statistics,
    pool_and_aggregate_latencies,
)
from experiments.runners.accuracy_runner import AccuracyBenchmarkRunner
from experiments.runners.latency_runner import LatencyBenchmarkRunner
from experiments.runners.throughput_runner import ThroughputBenchmarkRunner
from experiments.visualization.plotter import generate_all_figures


def test_synthetic_market_generator_seed_repeatability():
    """Verify that identical seeds produce identical event streams, and different seeds differ."""
    gen1 = SyntheticMarketGenerator(seed=42)
    stream1 = gen1.generate_stream(count=50)

    gen2 = SyntheticMarketGenerator(seed=42)
    stream2 = gen2.generate_stream(count=50)

    gen3 = SyntheticMarketGenerator(seed=999)
    stream3 = gen3.generate_stream(count=50)

    assert len(stream1) == 50
    assert len(stream2) == 50
    assert len(stream3) == 50

    for e1, e2 in zip(stream1, stream2):
        assert e1.event_id == e2.event_id
        assert e1.price == e2.price
        assert e1.bid == e2.bid
        assert e1.ask == e2.ask
        assert e1.volume == e2.volume
        assert e1.timestamp == e2.timestamp

    differences = sum(1 for e1, e3 in zip(stream1, stream3) if e1.price != e3.price)
    assert differences > 0


def test_synthetic_market_generator_monotonic_timestamps():
    """Verify timestamps progress monotonically."""
    gen = SyntheticMarketGenerator(seed=42, tick_interval_ms=15)
    stream = gen.generate_stream(count=20)
    for i in range(len(stream) - 1):
        assert stream[i].timestamp < stream[i + 1].timestamp


def test_anomaly_scenarios_ground_truth_correctness():
    """Verify all 5 controlled anomaly scenarios produce valid ground truth contracts."""
    gen = AnomalyScenarioGenerator(seed=42)

    norm = gen.generate_normal_scenario(asset="BTC")
    assert norm.scenario_type is ScenarioType.NORMAL
    assert not norm.expected_anomaly
    assert len(norm.expected_modules) == 0

    sf = gen.generate_spot_futures_scenario(asset="BTC", spread_pct=4.0)
    assert sf.scenario_type is ScenarioType.SPOT_FUTURES_SPREAD
    assert sf.expected_anomaly
    assert "spot-futures-spread" in sf.expected_modules

    ff = gen.generate_futures_futures_scenario(asset="BTC", spread_pct=5.0)
    assert ff.scenario_type is ScenarioType.FUTURES_FUTURES_SPREAD
    assert ff.expected_anomaly
    assert "futures-futures-spread" in ff.expected_modules

    fund = gen.generate_funding_scenario(asset="BTC", diff=0.12)
    assert fund.scenario_type is ScenarioType.FUNDING_SPREAD
    assert fund.expected_anomaly
    assert "funding-spread" in fund.expected_modules

    multi = gen.generate_multiple_scenario(asset="BTC")
    assert multi.scenario_type is ScenarioType.MULTIPLE_ANOMALIES
    assert multi.expected_anomaly
    assert len(multi.expected_modules) >= 2


def test_statistical_calculations_and_edge_cases():
    """Verify statistical summary functions with normal and edge-case inputs."""
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = calculate_statistics(data)
    assert stats.count == 5
    assert stats.mean == 30.0
    assert stats.median == 30.0
    assert stats.min == 10.0
    assert stats.max == 50.0
    assert stats.p50 == 30.0
    assert stats.p90 > 40.0

    empty_stats = calculate_statistics([])
    assert empty_stats.count == 0
    assert empty_stats.mean == 0.0
    assert empty_stats.median == 0.0

    single_stats = calculate_statistics([42.5])
    assert single_stats.count == 1
    assert single_stats.mean == 42.5
    assert single_stats.stddev == 0.0
    assert single_stats.p99 == 42.5


def test_pool_and_aggregate_latencies():
    """Verify multi-trial pooling function pools raw observations correctly."""
    t1 = [10.0, 20.0, 30.0]
    t2 = [40.0, 50.0, 60.0]
    summary = pool_and_aggregate_latencies([t1, t2])
    assert summary.count == 6
    assert summary.mean == 35.0
    assert summary.min == 10.0
    assert summary.max == 60.0


def test_classification_metrics_and_zero_division():
    """Verify confusion matrix and classification metrics calculations."""
    perf = calculate_classification_metrics(tp=100, fp=0, tn=100, fn=0)
    assert perf.precision == 1.0
    assert perf.recall == 1.0
    assert perf.f1_score == 1.0
    assert perf.accuracy == 1.0

    part = calculate_classification_metrics(tp=80, fp=20, tn=80, fn=20)
    assert part.precision == pytest.approx(0.8)
    assert part.recall == pytest.approx(0.8)
    assert part.f1_score == pytest.approx(0.8)
    assert part.accuracy == pytest.approx(0.8)

    zero = calculate_classification_metrics(tp=0, fp=0, tn=0, fn=0)
    assert zero.precision == 0.0
    assert zero.f1_score == 0.0


def test_metrics_collector_and_latency_records(tmp_path: Path):
    """Verify StageLatencyRecord and MetricsCollector CSV export."""
    collector = MetricsCollector()
    collector.start_timer()

    r1 = StageLatencyRecord(
        event_id="test-1",
        t_start_ns=1000,
        t_redis_published_ns=2000,
        t_worker_consumed_ns=3000,
        t_enriched_ns=4000,
        t_detection_done_ns=5000,
        t_aggregation_done_ns=6000,
        t_persisted_ns=7000,
        t_end_ns=8000,
    )
    collector.record_latency(r1)
    collector.stop_timer()

    summary = collector.get_latency_summary()
    assert "total_e2e_ms" in summary
    assert summary["total_e2e_ms"]["count"] == 1

    csv_file = tmp_path / "test_latency.csv"
    collector.export_csv(csv_file)
    assert csv_file.exists()


def test_environment_metadata():
    """Verify environment metadata collects required thesis reproduction fields."""
    meta = get_environment_metadata()
    assert "python_version" in meta
    assert "platform" in meta
    assert "git" in meta
    assert "docker" in meta


def test_accuracy_runner_execution():
    """Verify AccuracyBenchmarkRunner runs end-to-end on small scenario batch."""
    cfg = BenchmarkConfig()
    runner = AccuracyBenchmarkRunner(cfg)
    res = runner.run(total_scenarios=20, seed=42)

    assert res["experiment"] == "detection_accuracy"
    assert "modules" in res["results"]
    assert "spot-futures-spread" in res["results"]["modules"]
    assert "system_aggregate" in res["results"]["modules"]


def test_latency_runner_in_memory_execution():
    """Verify LatencyBenchmarkRunner in-memory mode runs with microseconds breakdown."""
    cfg = BenchmarkConfig()
    runner = LatencyBenchmarkRunner(cfg)
    res = runner.run(event_count=50, warmup_events=10, trials=1, mode="in-memory", seed=42)

    assert res["experiment"] == "core_engine_stage_latency"
    assert res["unit"] == "microseconds"
    assert "summary_core_total_us" in res
    assert res["trials"][0]["steady_state_samples"] == 50
    assert res["trials"][0]["warmup_excluded_samples"] == 10


def test_throughput_runner_in_memory_execution():
    """Verify ThroughputBenchmarkRunner in-memory mode runs and measures core capacity."""
    cfg = BenchmarkConfig()
    runner = ThroughputBenchmarkRunner(cfg)
    res = runner.run_in_memory(event_count=200, trials=2, seed=42)

    assert res["experiment"] == "core_engine_throughput_capacity"
    assert "mean_core_capacity_eps" in res["summary"]
    assert len(res["trials"]) == 2


def test_plotter_figure_generation(tmp_path: Path):
    """Verify plotter generates all PNG and PDF figures."""
    cfg = BenchmarkConfig()
    cfg.paths.reports_figures = str(tmp_path)
    figs = generate_all_figures(cfg)

    assert len(figs) >= 12
    for f in figs:
        assert Path(f).exists()
