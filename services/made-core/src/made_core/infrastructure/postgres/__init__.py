"""PostgreSQL persistence models and repository for MADE."""

from made_core.infrastructure.postgres.models import (
    AggregatedResultRecord,
    AlertRecord,
    Base,
    DetectionResultRecord,
    ProcessedEventRecord,
)
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter

__all__ = [
    "AggregatedResultRecord",
    "AlertRecord",
    "Base",
    "DetectionResultRecord",
    "PostgresStorageAdapter",
    "ProcessedEventRecord",
]
