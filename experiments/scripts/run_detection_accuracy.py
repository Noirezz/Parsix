"""Run Detection Accuracy Benchmark."""
from experiments.config.config_loader import load_benchmark_config
from experiments.runners.accuracy_runner import AccuracyBenchmarkRunner

if __name__ == "__main__":
    cfg = load_benchmark_config()
    runner = AccuracyBenchmarkRunner(cfg)
    res = runner.run(total_scenarios=200, seed=42)
    print("Accuracy Benchmark Completed.")
