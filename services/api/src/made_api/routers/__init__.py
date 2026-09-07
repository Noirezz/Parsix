"""API Routers package."""

from made_api.routers.aggregates import router as aggregates_router
from made_api.routers.alerts import router as alerts_router
from made_api.routers.charts import router as charts_router
from made_api.routers.detections import router as detections_router
from made_api.routers.events import router as events_router
from made_api.routers.health import router as health_router
from made_api.routers.metrics import router as metrics_router
from made_api.routers.modules import router as modules_router

__all__ = [
    "aggregates_router",
    "alerts_router",
    "charts_router",
    "detections_router",
    "events_router",
    "health_router",
    "metrics_router",
    "modules_router",
]
