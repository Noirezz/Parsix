"""Ingestion package containing Collectors, Normalizers, and Redis Publisher."""

from made_core.ingestion.collector import (
    BinanceCollector,
    BybitCollector,
    BybitCollectorConfig,
    CollectorConfig,
    CollectorError,
)
from made_core.ingestion.dex_collector import DexCollectorConfig, DexScreenerCollector
from made_core.ingestion.dex_normalizer import DexNormalizer
from made_core.ingestion.normalizer import (
    BinanceNormalizer,
    BybitNormalizer,
    NormalizerError,
)
from made_core.ingestion.pipeline import (
    IngestionPipeline,
    MultiSourceIngestionPipeline,
    SourceTarget,
)
from made_core.ingestion.publisher import PublisherError, RedisEventPublisher

__all__ = [
    "BinanceCollector",
    "BinanceNormalizer",
    "BybitCollector",
    "BybitCollectorConfig",
    "BybitNormalizer",
    "CollectorConfig",
    "CollectorError",
    "DexCollectorConfig",
    "DexNormalizer",
    "DexScreenerCollector",
    "IngestionPipeline",
    "MultiSourceIngestionPipeline",
    "NormalizerError",
    "PublisherError",
    "RedisEventPublisher",
    "SourceTarget",
]
