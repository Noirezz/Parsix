"""Application-layer alert generator for anomaly aggregates."""

from __future__ import annotations

from made_core.domain.enums import Priority
from made_core.domain.interfaces import AlertGenerator
from made_core.domain.models import AggregatedResult, Alert


class DefaultAlertGenerator(AlertGenerator):
    """Constructs notification-ready Alert objects for MEDIUM and HIGH priority aggregates."""

    def generate(self, aggregate: AggregatedResult) -> Alert | None:
        if aggregate is None:
            raise TypeError("aggregate must not be None")
        if not isinstance(aggregate, AggregatedResult):
            raise TypeError("aggregate must be an instance of AggregatedResult")

        if aggregate.priority is Priority.LOW:
            return None

        title = f"[{aggregate.priority.value}] {aggregate.asset} anomaly detected"
        summary = (
            f"{aggregate.asset} anomaly detected by {aggregate.module_count} module(s). "
            f"Composite score: {aggregate.composite_anomaly_score}."
        )

        details = {
            "aggregationId": aggregate.aggregation_id,
            "correlationId": aggregate.correlation_window.correlation_id,
            "maxAnomalyRatio": str(aggregate.max_anomaly_ratio),
            "averageAnomalyRatio": str(aggregate.average_anomaly_ratio),
            "compositeAnomalyScore": str(aggregate.composite_anomaly_score),
            "triggeredModules": list(aggregate.triggered_modules),
            "moduleCount": aggregate.module_count,
            "windowStart": aggregate.correlation_window.window_start.isoformat(),
            "windowEnd": aggregate.correlation_window.window_end.isoformat(),
        }

        alert_id = f"alert:{aggregate.asset}:{aggregate.aggregation_id}"

        return Alert(
            alert_id=alert_id,
            timestamp=aggregate.timestamp,
            asset=aggregate.asset,
            priority=aggregate.priority,
            title=title,
            summary=summary,
            anomaly_score=aggregate.composite_anomaly_score,
            triggered_modules=aggregate.triggered_modules,
            details=details,
        )
