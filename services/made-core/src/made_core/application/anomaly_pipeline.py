"""Application-layer coordinator for downstream anomaly result processing."""

from __future__ import annotations

from collections.abc import Sequence

from made_core.application.alerting import DefaultAlertGenerator
from made_core.application.aggregator import DefaultResultAggregator
from made_core.application.correlation import DefaultCorrelationEngine
from made_core.application.priority import DefaultPriorityEvaluator

from made_core.domain.enums import ResultStatus, ValidationStatus
from made_core.domain.interfaces import (
    AlertGenerator,
    CorrelationEngine,
    PriorityEvaluator,
    ResultAggregator,
)
from made_core.domain.models import Alert, DetectionResult, PipelineExecutionResult


class AnomalyProcessingPipeline:
    """Coordinates downstream anomaly processing: DetectionResult[] -> Aggregation -> Alert."""

    def __init__(
        self,
        aggregator: ResultAggregator | None = None,
        correlation_engine: CorrelationEngine | None = None,
        priority_evaluator: PriorityEvaluator | None = None,
        alert_generator: AlertGenerator | None = None,
    ) -> None:
        self._correlation_engine = correlation_engine or DefaultCorrelationEngine()
        self._priority_evaluator = priority_evaluator or DefaultPriorityEvaluator()
        self._aggregator = aggregator or DefaultResultAggregator(
            priority_evaluator=self._priority_evaluator,
            correlation_engine=self._correlation_engine,
        )
        self._alert_generator = alert_generator or DefaultAlertGenerator()

    def process_results(self, results: Sequence[DetectionResult]) -> Alert | None:
        """Process a sequence of DetectionResult objects and return an Alert if warranted."""
        if results is None:
            raise TypeError("results must not be None")

        if not results:
            return None

        has_anomaly = False
        for r in results:
            if not isinstance(r, DetectionResult):
                raise TypeError("all elements in results must be DetectionResult instances")
            if r.status is ResultStatus.ANOMALY:
                has_anomaly = True

        if not has_anomaly:
            return None

        aggregate = self._aggregator.aggregate(results)
        if aggregate is None:
            return None

        return self._alert_generator.generate(aggregate)

    def process_pipeline_result(self, pipeline_result: PipelineExecutionResult) -> Alert | None:
        """Process the output of an upstream EventPipeline execution."""
        if pipeline_result is None:
            raise TypeError("pipeline_result must not be None")
        if not isinstance(pipeline_result, PipelineExecutionResult):
            raise TypeError("pipeline_result must be an instance of PipelineExecutionResult")

        if pipeline_result.status is not ValidationStatus.VALID:
            return None

        return self.process_results(pipeline_result.detection_results)
