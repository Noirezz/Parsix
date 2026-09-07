"""Run Docker Resource Benchmark."""
from experiments.metrics.collector import MetricsCollector

if __name__ == "__main__":
    collector = MetricsCollector()
    samples = collector.sample_docker_resources()
    print(f"Captured {len(samples)} Docker resource samples.")
