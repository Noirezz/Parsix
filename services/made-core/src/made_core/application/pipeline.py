"""Application-layer orchestration of the MADE Core detection pipeline."""

from __future__ import annotations

from collections.abc import Sequence

from made_core.domain.enums import ValidationStatus
from made_core.domain.interfaces import ContextEnricher, EventValidator, RuleExecutor
from made_core.domain.models import (
    MarketSnapshot,
    NormalizedEvent,
    PipelineExecutionResult,
)


class EventPipeline:
    """Orchestrates the canonical MADE Core processing flow."""

    def __init__(
        self,
        validator: EventValidator,
        enricher: ContextEnricher,
        executor: RuleExecutor,
    ) -> None:
        self._validator = validator
        self._enricher = enricher
        self._executor = executor

    def process_event(
        self,
        event: NormalizedEvent,
        snapshots: Sequence[MarketSnapshot] = (),
    ) -> PipelineExecutionResult:
        if event is None:
            raise TypeError("event must not be None")
        if not isinstance(event, NormalizedEvent):
            raise TypeError("event must be an instance of NormalizedEvent")

        validation = self._validator.validate(event)
        if validation.status is ValidationStatus.INVALID:
            return PipelineExecutionResult(
                event_id=event.event_id,
                status=ValidationStatus.INVALID,
                validation_result=validation,
                enriched_event=None,
                detection_results=(),
            )

        target_event = validation.validated_event if validation.validated_event is not None else event
        enriched = self._enricher.enrich(target_event, snapshots)
        results = self._executor.execute(enriched)

        return PipelineExecutionResult(
            event_id=event.event_id,
            status=ValidationStatus.VALID,
            validation_result=validation,
            enriched_event=enriched,
            detection_results=tuple(results),
        )
