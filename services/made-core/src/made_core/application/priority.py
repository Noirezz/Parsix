"""Application-layer priority evaluator for anomaly aggregates."""

from __future__ import annotations

from decimal import Decimal

from made_core.domain.enums import Priority
from made_core.domain.interfaces import PriorityEvaluator
from made_core.domain.models import AggregatedResult


class DefaultPriorityEvaluator(PriorityEvaluator):
    """Evaluates Priority based on module count and max anomaly ratio."""

    def evaluate(self, aggregate: AggregatedResult) -> Priority:
        if aggregate is None:
            raise TypeError("aggregate must not be None")
        if not isinstance(aggregate, AggregatedResult):
            raise TypeError("aggregate must be an instance of AggregatedResult")

        return self.evaluate_metrics(aggregate.module_count, aggregate.max_anomaly_ratio)

    def evaluate_metrics(self, module_count: int, max_anomaly_ratio: Decimal) -> Priority:
        if module_count is None:
            raise TypeError("module_count must not be None")
        if max_anomaly_ratio is None:
            raise TypeError("max_anomaly_ratio must not be None")

        if module_count >= 2 or max_anomaly_ratio >= Decimal("3.0"):
            return Priority.HIGH
        if Decimal("1.5") <= max_anomaly_ratio < Decimal("3.0"):
            return Priority.MEDIUM
        return Priority.LOW
