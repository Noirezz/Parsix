"""Run Latency Benchmark."""
from experiments.config.config_loader import load_benchmark_config
from experiments.runners.latency_runner import LatencyBenchmarkRunner

if __name__ == "__main__":
    cfg = load_benchmark_config()
    runner = LatencyBenchmarkRunner(cfg)
    res = runner.run(event_count=1000, seed=42)
    print("Latency Benchmark Completed.")
