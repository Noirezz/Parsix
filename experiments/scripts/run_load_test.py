"""Run Load and Stress Benchmark."""
from experiments.config.config_loader import load_benchmark_config
from experiments.runners.load_test_runner import LoadTestBenchmarkRunner

if __name__ == "__main__":
    cfg = load_benchmark_config()
    runner = LoadTestBenchmarkRunner(cfg)
    res = runner.run(duration_per_stage=2.0, seed=42)
    print("Load Test Benchmark Completed.")
