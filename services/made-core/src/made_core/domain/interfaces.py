"""Abstract contracts for MADE modules and the Rule Engine mechanism."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from made_core.domain.enums import Priority
from made_core.domain.models import (
    AggregatedResult,
    Alert,
    CorrelatedGroup,
    DetectionResult,
    EnrichedEvent,
    MarketSnapshot,
    NormalizedEvent,
    ValidationResult,
)


class EventValidator(Protocol):
    """Abstract contract for event validation in MADE Core."""

    def validate(self, event: NormalizedEvent) -> ValidationResult: ...


class ContextEnricher(Protocol):
    """Abstract contract for market context enrichment in MADE Core."""

    def enrich(
        self,
        event: NormalizedEvent,
        snapshots: Sequence[MarketSnapshot] = (),
    ) -> EnrichedEvent: ...


class DetectionModule(ABC):
    """Public extension point for an independently executable detection module."""

    @abstractmethod
    def get_module_id(self) -> str:
        """Return the stable, unique identifier of this module."""

    @abstractmethod
    def detect(self, event: EnrichedEvent) -> DetectionResult:
        """Produce one standardised result for an enriched event."""


class RuleRegistry(Protocol):
    """Stores module metadata and availability; it does not execute modules."""

    def register(self, module: DetectionModule) -> None: ...

    def get_active_module_ids(self) -> Sequence[str]: ...


class ModuleLoader(Protocol):
    """Resolves registered modules for execution; it is not a separate service."""

    def load(self, module_ids: Sequence[str]) -> Sequence[DetectionModule]: ...


class RuleExecutor(Protocol):
    """Selects and executes active modules without containing module formulas."""

    def execute(self, event: EnrichedEvent) -> Sequence[DetectionResult]: ...


class ResultAggregator(Protocol):
    """Combines standardised DetectionResults into an AggregatedResult."""

    def aggregate(
        self,
        results: Sequence[DetectionResult],
        correlation_window: CorrelatedGroup | None = None,
    ) -> AggregatedResult | None: ...


class CorrelationEngine(Protocol):
    """Groups detection results by asset and time window."""

    def correlate(
        self,
        results: Sequence[DetectionResult],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> CorrelatedGroup: ...


class PriorityEvaluator(Protocol):
    """Evaluates Priority of an anomaly aggregate."""

    def evaluate(
        self,
        aggregate: AggregatedResult,
    ) -> Priority: ...


class AlertGenerator(Protocol):
    """Constructs a notification-ready Alert from an AggregatedResult."""

    def generate(
        self,
        aggregate: AggregatedResult,
    ) -> Alert | None: ...
