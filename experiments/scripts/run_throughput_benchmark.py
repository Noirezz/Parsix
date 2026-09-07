"""Run Throughput Benchmark."""
from experiments.config.config_loader import load_benchmark_config
from experiments.runners.throughput_runner import ThroughputBenchmarkRunner

if __name__ == "__main__":
    cfg = load_benchmark_config()
    runner = ThroughputBenchmarkRunner(cfg)
    res = runner.run(rates=[10, 50, 100, 250, 500, 1000], duration_per_stage=2.0, seed=42)
    print("Throughput Benchmark Completed.")
