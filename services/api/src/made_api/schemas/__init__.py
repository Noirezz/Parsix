"""API Schemas package."""

from made_api.schemas.aggregates import AggregatedResultResponse
from made_api.schemas.alerts import AlertResponse
from made_api.schemas.common import ErrorResponse, PaginatedResponse
from made_api.schemas.detections import DetectionResultResponse
from made_api.schemas.events import ProcessedEventResponse
from made_api.schemas.metrics import MetricsResponse
from made_api.schemas.modules import ModuleMetadataResponse

__all__ = [
    "AggregatedResultResponse",
    "AlertResponse",
    "DetectionResultResponse",
    "ErrorResponse",
    "MetricsResponse",
    "ModuleMetadataResponse",
    "PaginatedResponse",
    "ProcessedEventResponse",
]
