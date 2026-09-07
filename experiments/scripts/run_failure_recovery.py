"""Run Failure Recovery Benchmark."""
import asyncio
from experiments.config.config_loader import load_benchmark_config
from experiments.runners.failure_test_runner import FailureRecoveryBenchmarkRunner

if __name__ == "__main__":
    cfg = load_benchmark_config()
    runner = FailureRecoveryBenchmarkRunner(cfg)
    res = asyncio.run(runner.run())
    print("Failure Recovery Benchmark Completed.")
