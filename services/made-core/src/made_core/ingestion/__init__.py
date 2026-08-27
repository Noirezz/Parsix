"""Ingestion package containing Collector, Normalizer, and Redis Publisher."""

from made_core.ingestion.collector import BinanceCollector, CollectorConfig, CollectorError
from made_core.ingestion.normalizer import BinanceNormalizer, NormalizerError
from made_core.ingestion.pipeline import IngestionPipeline
from made_core.ingestion.publisher import PublisherError, RedisEventPublisher

__all__ = [
    "BinanceCollector",
    "BinanceNormalizer",
    "CollectorConfig",
    "CollectorError",
    "IngestionPipeline",
    "NormalizerError",
    "PublisherError",
    "RedisEventPublisher",
]
