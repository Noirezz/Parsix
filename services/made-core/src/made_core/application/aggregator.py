"""Application-layer result aggregator for detection results."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.priority import DefaultPriorityEvaluator
from made_core.domain.enums import ResultStatus
from made_core.domain.interfaces import CorrelationEngine, PriorityEvaluator, ResultAggregator
from made_core.domain.models import AggregatedResult, CorrelatedGroup, DetectionResult


class DefaultResultAggregator(ResultAggregator):
    """Combines standardised anomalous DetectionResults into an AggregatedResult."""

    def __init__(
        self,
        priority_evaluator: PriorityEvaluator | None = None,
        correlation_engine: CorrelationEngine | None = None,
    ) -> None:
        self._priority_evaluator = priority_evaluator or DefaultPriorityEvaluator()
        self._correlation_engine = correlation_engine or DefaultCorrelationEngine()

    def aggregate(
        self,
        results: Sequence[DetectionResult],
        correlation_window: CorrelatedGroup | None = None,
    ) -> AggregatedResult | None:
        if results is None:
            raise TypeError("results must not be None")
        if not results:
            return None

        anomalous: list[DetectionResult] = []
        for r in results:
            if not isinstance(r, DetectionResult):
                raise TypeError("all elements in results must be DetectionResult instances")
            if r.status is ResultStatus.ANOMALY:
                anomalous.append(r)

        if not anomalous:
            return None

        asset = anomalous[0].asset
        if any(r.asset != asset for r in anomalous):
            raise ValueError("all anomalous detection results must belong to the same asset")

        triggered_list: list[str] = []
        for r in anomalous:
            if r.module_id not in triggered_list:
                triggered_list.append(r.module_id)
        triggered_modules = tuple(triggered_list)
        module_count = len(triggered_modules)

        max_anomaly_ratio = max(r.anomaly_ratio for r in anomalous)
        average_anomaly_ratio = sum(r.anomaly_ratio for r in anomalous) / Decimal(len(anomalous))

        multiplier = Decimal("1") + Decimal("0.1") * (Decimal(module_count) - Decimal("1"))
        composite_anomaly_score = max_anomaly_ratio * multiplier

        if isinstance(self._priority_evaluator, DefaultPriorityEvaluator):
            priority = self._priority_evaluator.evaluate_metrics(module_count, max_anomaly_ratio)
        else:
            # Fallback priority evaluation
            priority = self._priority_evaluator.evaluate_metrics(module_count, max_anomaly_ratio) if hasattr(self._priority_evaluator, "evaluate_metrics") else (
                DefaultPriorityEvaluator().evaluate_metrics(module_count, max_anomaly_ratio)
            )

        window = correlation_window if correlation_window is not None else self._correlation_engine.correlate(anomalous)

        aggregation_id = f"agg:{asset}:{anomalous[0].event_id}"

        return AggregatedResult(
            aggregation_id=aggregation_id,
            timestamp=anomalous[0].timestamp,
            asset=asset,
            correlation_window=window,
            triggered_modules=triggered_modules,
            module_count=module_count,
            composite_anomaly_score=composite_anomaly_score,
            max_anomaly_ratio=max_anomaly_ratio,
            average_anomaly_ratio=average_anomaly_ratio,
            priority=priority,
            source_results=tuple(anomalous),
        )
