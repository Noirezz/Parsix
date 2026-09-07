"""Unified CLI entrypoint for MADE benchmarks with strict mode separation and trial handling (V3.0)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from experiments.config.config_loader import load_benchmark_config
from experiments.runners.accuracy_runner import AccuracyBenchmarkRunner
from experiments.runners.failure_test_runner import FailureRecoveryBenchmarkRunner
from experiments.runners.latency_runner import LatencyBenchmarkRunner
from experiments.runners.load_test_runner import LoadTestBenchmarkRunner
from experiments.runners.throughput_runner import ThroughputBenchmarkRunner
from experiments.visualization.plotter import generate_all_figures


def main() -> None:
    parser = argparse.ArgumentParser(description="MADE Experimental Evaluation & Benchmarking CLI (V3.0)")
    parser.add_argument(
        "--experiment",
        choices=["all", "accuracy", "latency", "throughput", "load", "failure", "plots"],
        default="all",
        help="Experiment to execute",
    )
    parser.add_argument(
        "--mode",
        choices=["in-memory", "live", "all"],
        default="in-memory",
        help="Execution mode (in-memory core engine vs live containerized stack)",
    )
    parser.add_argument("--events", type=int, default=None, help="Number of synthetic events")
    parser.add_argument("--rate", type=int, default=None, help="Target offered events per second")
    parser.add_argument("--duration", type=float, default=None, help="Duration per benchmark stage (seconds)")
    parser.add_argument("--trials", type=int, default=1, help="Number of independent benchmark trials")
    parser.add_argument("--warmup", type=int, default=50, help="Number of warm-up events to exclude from statistics")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--config", type=str, default=None, help="Path to custom benchmark YAML config")

    args = parser.parse_args()
    config = load_benchmark_config(args.config)

    print(f"=== MADE Benchmark Framework V3.0 [Experiment: {args.experiment}, Mode: {args.mode}, Seed: {args.seed}, Trials: {args.trials}] ===")

    if args.experiment in ("accuracy", "all"):
        print("\n>>> Running Detection Accuracy Benchmark...")
        scenarios = args.events if args.events is not None else 200
        runner = AccuracyBenchmarkRunner(config)
        acc_res = runner.run(total_scenarios=scenarios, seed=args.seed)
        sys_metrics = acc_res["results"]["modules"]["system_aggregate"]
        print(f"    System Aggregate -> Precision: {sys_metrics['precision']:.4f} | Recall: {sys_metrics['recall']:.4f} | F1: {sys_metrics['f1_score']:.4f}")

    if args.experiment in ("latency", "all"):
        print(f"\n>>> Running Latency Benchmark [Mode: {args.mode}]...")
        events = args.events if args.events is not None else (1000 if args.mode == "in-memory" else 50)
        lat_runner = LatencyBenchmarkRunner(config)
        
        if args.mode in ("in-memory", "all"):
            lat_res_mem = lat_runner.run(event_count=events, warmup_events=args.warmup, trials=args.trials, mode="in-memory", seed=args.seed)
            core_tot = lat_res_mem.get("summary_core_total_us", {})
            print(f"    [In-Memory Core Engine] -> Mean: {core_tot.get('mean', 0):.2f} us | p50: {core_tot.get('p50', 0):.2f} us | p95: {core_tot.get('p95', 0):.2f} us | p99: {core_tot.get('p99', 0):.2f} us")

        if args.mode in ("live", "all"):
            lat_res_live = lat_runner.run(event_count=min(events, 50), warmup_events=min(args.warmup, 5), trials=args.trials, mode="live", seed=args.seed)
            t1 = lat_res_live["trials"][0] if lat_res_live.get("trials") else {}
            pipe = t1.get("pipeline_persistence_latency_ms", {})
            api = t1.get("api_http_request_latency_ms", {})
            vis = t1.get("total_event_visibility_latency_ms", {})
            print(f"    [Live Pipeline Persistence] -> Mean: {pipe.get('mean', 0):.2f} ms | p50: {pipe.get('p50', 0):.2f} ms | p95: {pipe.get('p95', 0):.2f} ms | p99: {pipe.get('p99', 0):.2f} ms")
            print(f"    [REST API Request Duration] -> Mean: {api.get('mean', 0):.2f} ms | p50: {api.get('p50', 0):.2f} ms")
            print(f"    [Total E2E Visibility Latency] -> Mean: {vis.get('mean', 0):.2f} ms | p50: {vis.get('p50', 0):.2f} ms")

    if args.experiment in ("throughput", "all"):
        print(f"\n>>> Running Throughput Benchmark [Mode: {args.mode}]...")
        tput_runner = ThroughputBenchmarkRunner(config)
        dur = args.duration if args.duration is not None else 5.0

        if args.mode in ("in-memory", "all"):
            tput_mem = tput_runner.run(rates=[args.rate] if args.rate else [1000], duration_per_stage=dur, trials=args.trials, mode="in-memory", seed=args.seed)
            print(f"    [In-Memory Core Engine Capacity] -> Mean: {tput_mem['summary']['mean_core_capacity_eps']:.2f} events/sec")

        if args.mode in ("live", "all"):
            rates = [args.rate] if args.rate is not None else [10, 50, 100]
            tput_live = tput_runner.run(rates=rates, duration_per_stage=dur, trials=args.trials, mode="live", seed=args.seed)
            for st in tput_live.get("stages", []):
                print(f"    Offered: {st['target_offered_rate_eps']:4d} eps -> Steady: {st['mean_steady_state_throughput_eps']:6.2f} eps | Completion: {st['mean_completion_throughput_eps']:6.2f} eps | Class: {st['classification']}")

    if args.experiment in ("load", "all"):
        print("\n>>> Running Staged Load & Resource Benchmark...")
        load_runner = LoadTestBenchmarkRunner(config)
        dur = args.duration if args.duration is not None else 2.0
        load_res = load_runner.run(duration_per_stage=dur, seed=args.seed)
        print(f"    Load test stages executed: {len(load_res['results']['throughput_stages'])}, Resource samples: {len(load_res['results']['resource_samples'])}")

    if args.experiment in ("failure", "all"):
        print("\n>>> Running Failure Recovery Benchmark...")
        fail_runner = FailureRecoveryBenchmarkRunner(config)
        fail_res = asyncio.run(fail_runner.run(trials=args.trials))
        sums = fail_res.get("scenario_summaries", {})
        for sc_name, sc_data in sums.items():
            print(f"    [{sc_name}] -> Mean Duration: {sc_data.get('mean_ms', 0):.2f} ms ({sc_data.get('count', 0)} trials)")

    if args.experiment in ("plots", "all"):
        print("\n>>> Generating Publication-Quality Figures...")
        figs = generate_all_figures(config)
        print(f"    Generated {len(figs)} figures in {config.paths.reports_figures}")

    print("\n=== Benchmark Execution Complete ===")


if __name__ == "__main__":
    main()
