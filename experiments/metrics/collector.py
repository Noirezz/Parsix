"""Metrics collector for stage latencies, throughput, and Docker resource usage."""

from __future__ import annotations

import csv
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .statistics import StatisticalSummary, calculate_statistics


@dataclass
class StageLatencyRecord:
    """Microsecond-accurate monotonic latency breakdown for a single event."""

    event_id: str
    t_start_ns: int = 0
    t_redis_published_ns: int = 0
    t_worker_consumed_ns: int = 0
    t_enriched_ns: int = 0
    t_detection_done_ns: int = 0
    t_aggregation_done_ns: int = 0
    t_persisted_ns: int = 0
    t_api_visible_ns: int = 0
    t_end_ns: int = 0

    @property
    def total_e2e_ms(self) -> float:
        if self.t_end_ns > self.t_start_ns:
            return (self.t_end_ns - self.t_start_ns) / 1_000_000.0
        return 0.0

    @property
    def ingestion_to_redis_ms(self) -> float:
        if self.t_redis_published_ns > self.t_start_ns:
            return (self.t_redis_published_ns - self.t_start_ns) / 1_000_000.0
        return 0.0

    @property
    def redis_to_worker_ms(self) -> float:
        if self.t_worker_consumed_ns > self.t_redis_published_ns:
            return (self.t_worker_consumed_ns - self.t_redis_published_ns) / 1_000_000.0
        return 0.0

    @property
    def enrichment_ms(self) -> float:
        if self.t_enriched_ns > self.t_worker_consumed_ns:
            return (self.t_enriched_ns - self.t_worker_consumed_ns) / 1_000_000.0
        return 0.0

    @property
    def detection_ms(self) -> float:
        if self.t_detection_done_ns > self.t_enriched_ns:
            return (self.t_detection_done_ns - self.t_enriched_ns) / 1_000_000.0
        return 0.0

    @property
    def aggregation_ms(self) -> float:
        if self.t_aggregation_done_ns > self.t_detection_done_ns:
            return (self.t_aggregation_done_ns - self.t_detection_done_ns) / 1_000_000.0
        return 0.0

    @property
    def persistence_ms(self) -> float:
        if self.t_persisted_ns > self.t_aggregation_done_ns:
            return (self.t_persisted_ns - self.t_aggregation_done_ns) / 1_000_000.0
        return 0.0


@dataclass
class DockerResourceSample:
    """Resource utilization sample for a Docker container."""

    timestamp: str
    container_name: str
    cpu_percent: float
    memory_usage_mb: float
    net_rx_mb: float = 0.0
    net_tx_mb: float = 0.0


class MetricsCollector:
    """Aggregates latency records, throughput observations, and Docker resource stats."""

    def __init__(self) -> None:
        self._latency_records: list[StageLatencyRecord] = []
        self._resource_samples: list[DockerResourceSample] = []
        self._events_processed_count: int = 0
        self._start_time_monotonic: float = 0.0
        self._end_time_monotonic: float = 0.0

    def start_timer(self) -> None:
        self._start_time_monotonic = time.perf_counter()

    def stop_timer(self) -> None:
        self._end_time_monotonic = time.perf_counter()

    def record_latency(self, record: StageLatencyRecord) -> None:
        self._latency_records.append(record)
        self._events_processed_count += 1

    def sample_docker_resources(self) -> list[DockerResourceSample]:
        """Capture live Docker container CPU and memory stats."""
        samples: list[DockerResourceSample] = []
        try:
            cmd = ["docker", "stats", "--no-stream", "--format", "{{.Name}}	{{.CPUPerc}}	{{.MemUsage}}	{{.NetIO}}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if res.returncode == 0:
                now_str = datetime.now(timezone.utc).isoformat()
                for line in res.stdout.strip().splitlines():
                    parts = line.split("	")
                    if len(parts) >= 3:
                        name = parts[0].strip()
                        cpu_str = parts[1].replace("%", "").strip()
                        cpu_val = float(cpu_str) if cpu_str else 0.0
                        
                        # Parse MemUsage, e.g. "55.29MiB / 15.59GiB"
                        mem_part = parts[2].split("/")[0].strip()
                        mem_val = 0.0
                        if "GiB" in mem_part:
                            mem_val = float(mem_part.replace("GiB", "").strip()) * 1024.0
                        elif "MiB" in mem_part:
                            mem_val = float(mem_part.replace("MiB", "").strip())
                        elif "kB" in mem_part or "KiB" in mem_part:
                            mem_val = float(mem_part.replace("KiB", "").replace("kB", "").strip()) / 1024.0

                        sample = DockerResourceSample(
                            timestamp=now_str,
                            container_name=name,
                            cpu_percent=cpu_val,
                            memory_usage_mb=mem_val,
                        )
                        samples.append(sample)
                        self._resource_samples.append(sample)
        except Exception:
            pass
        return samples

    def get_latency_summary(self) -> dict[str, Any]:
        """Compute statistical summaries for each pipeline stage."""
        if not self._latency_records:
            return {}

        e2e = [r.total_e2e_ms for r in self._latency_records if r.total_e2e_ms > 0]
        ingestion_redis = [r.ingestion_to_redis_ms for r in self._latency_records if r.ingestion_to_redis_ms > 0]
        redis_worker = [r.redis_to_worker_ms for r in self._latency_records if r.redis_to_worker_ms > 0]
        enrichment = [r.enrichment_ms for r in self._latency_records if r.enrichment_ms > 0]
        detection = [r.detection_ms for r in self._latency_records if r.detection_ms > 0]
        aggregation = [r.aggregation_ms for r in self._latency_records if r.aggregation_ms > 0]
        persistence = [r.persistence_ms for r in self._latency_records if r.persistence_ms > 0]

        return {
            "total_e2e_ms": calculate_statistics(e2e).to_dict(),
            "ingestion_to_redis_ms": calculate_statistics(ingestion_redis).to_dict(),
            "redis_to_worker_ms": calculate_statistics(redis_worker).to_dict(),
            "enrichment_ms": calculate_statistics(enrichment).to_dict(),
            "detection_ms": calculate_statistics(detection).to_dict(),
            "aggregation_ms": calculate_statistics(aggregation).to_dict(),
            "persistence_ms": calculate_statistics(persistence).to_dict(),
        }

    def get_throughput_stats(self) -> dict[str, float]:
        """Compute sustained events/sec throughput."""
        elapsed = self._end_time_monotonic - self._start_time_monotonic
        if elapsed <= 0:
            elapsed = 0.001
        rate = self._events_processed_count / elapsed
        return {
            "events_processed": self._events_processed_count,
            "elapsed_seconds": round(elapsed, 4),
            "throughput_events_per_sec": round(rate, 2),
        }

    def export_csv(self, output_path: str | Path) -> None:
        """Export raw latency records to CSV."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "event_id",
                "total_e2e_ms",
                "ingestion_to_redis_ms",
                "redis_to_worker_ms",
                "enrichment_ms",
                "detection_ms",
                "aggregation_ms",
                "persistence_ms",
            ])
            for r in self._latency_records:
                writer.writerow([
                    r.event_id,
                    round(r.total_e2e_ms, 4),
                    round(r.ingestion_to_redis_ms, 4),
                    round(r.redis_to_worker_ms, 4),
                    round(r.enrichment_ms, 4),
                    round(r.detection_ms, 4),
                    round(r.aggregation_ms, 4),
                    round(r.persistence_ms, 4),
                ])
