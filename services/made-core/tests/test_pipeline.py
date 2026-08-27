"""Unit tests for EventPipeline and PipelineExecutionResult."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from made_core.application.enrichment import DefaultContextEnricher
from made_core.application.pipeline import EventPipeline
from made_core.application.rule_engine import (
    InMemoryRuleRegistry,
    RegistryModuleLoader,
    RuleEngineExecutor,
)
from made_core.application.validator import NormalizedEventValidator
from made_core.domain.enums import EventSource, MarketType, ResultStatus, ValidationStatus
from made_core.domain.interfaces import ContextEnricher, EventValidator, RuleExecutor
from made_core.domain.models import (
    DetectionResult,
    EnrichedEvent,
    MarketSnapshot,
    NormalizedEvent,
    PipelineExecutionResult,
    ValidationError,
    ValidationResult,
)
from made_core.modules.futures_futures_spread import (
    FuturesFuturesSpreadConfig,
    FuturesFuturesSpreadModule,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_event(
    *,
    event_id: str = "evt-1",
    bid: Decimal = Decimal("63999"),
    ask: Decimal = Decimal("64001"),
    price: Decimal = Decimal("64000"),
    volume: Decimal = Decimal("10"),
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
    source: EventSource = EventSource.BINANCE,
    market_type: MarketType = MarketType.FUTURES,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        timestamp=TS,
        source=source,
        market_type=market_type,
        asset=asset,
        symbol=symbol,
        price=price,
        bid=bid,
        ask=ask,
        volume=volume,
    )


def _make_snapshot(
    *,
    source: EventSource = EventSource.BYBIT,
    market_type: MarketType = MarketType.FUTURES,
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("64050"),
    bid: Decimal = Decimal("64049"),
    ask: Decimal = Decimal("64051"),
    volume: Decimal = Decimal("15"),
    funding_rate: Decimal | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=TS,
        source=source,
        market_type=market_type,
        asset=asset,
        symbol=symbol,
        price=price,
        bid=bid,
        ask=ask,
        volume=volume,
        funding_rate=funding_rate,
    )


class _RecordingValidator(EventValidator):
    def __init__(self, result: ValidationResult | None = None) -> None:
        self.calls: list[NormalizedEvent] = []
        self._result = result

    def validate(self, event: NormalizedEvent) -> ValidationResult:
        self.calls.append(event)
        if self._result is not None:
            return self._result
        return ValidationResult(
            event_id=event.event_id,
            status=ValidationStatus.VALID,
            errors=(),
            validated_event=event,
        )


class _RecordingEnricher(ContextEnricher):
    def __init__(self) -> None:
        self.calls: list[tuple[NormalizedEvent, tuple[MarketSnapshot, ...]]] = []

    def enrich(self, event: NormalizedEvent, snapshots=()) -> EnrichedEvent:
        self.calls.append((event, tuple(snapshots)))
        return DefaultContextEnricher().enrich(event, snapshots)


class _RecordingExecutor(RuleExecutor):
    def __init__(self, results: tuple[DetectionResult, ...] = ()) -> None:
        self.calls: list[EnrichedEvent] = []
        self._results = results

    def execute(self, event: EnrichedEvent) -> tuple[DetectionResult, ...]:
        self.calls.append(event)
        return self._results


def _build_real_pipeline() -> EventPipeline:
    validator = NormalizedEventValidator()
    enricher = DefaultContextEnricher()
    registry = InMemoryRuleRegistry()
    registry.register(FuturesFuturesSpreadModule(FuturesFuturesSpreadConfig(threshold=Decimal("1"))))
    loader = RegistryModuleLoader(registry)
    executor = RuleEngineExecutor(registry, loader)
    return EventPipeline(validator=validator, enricher=enricher, executor=executor)


def test_pipeline_implements_expected_contract():
    validator = _RecordingValidator()
    enricher = _RecordingEnricher()
    executor = _RecordingExecutor()
    pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)
    assert callable(getattr(pipeline, "process_event", None))


def test_orchestrator_full_happy_path():
    pipeline = _build_real_pipeline()
    event = _make_event(bid=Decimal("63999"), ask=Decimal("64001"), price=Decimal("64000"))
    snap1 = _make_snapshot(source=EventSource.BINANCE, price=Decimal("64000"))
    snap2 = _make_snapshot(source=EventSource.BYBIT, price=Decimal("66000"))

    result = pipeline.process_event(event, (snap1, snap2))

    assert isinstance(result, PipelineExecutionResult)
    assert result.event_id == event.event_id
    assert result.status is ValidationStatus.VALID
    assert result.validation_result.status is ValidationStatus.VALID
    assert result.enriched_event is not None
    assert result.enriched_event.event_id == event.event_id
    assert len(result.detection_results) == 1
    assert result.detection_results[0].module_id == "futures-futures-spread"
    assert result.detection_results[0].status is ResultStatus.ANOMALY


def test_orchestrator_stops_on_invalid_event():
    validator = _RecordingValidator(
        result=ValidationResult(
            event_id="evt-inv",
            status=ValidationStatus.INVALID,
            errors=(
                ValidationError(
                    code="BID_EXCEEDS_ASK",
                    message="Bid exceeds ask",
                    field="bid,ask",
                    event_id="evt-inv",
                ),
            ),
            validated_event=None,
        )
    )
    enricher = _RecordingEnricher()
    executor = _RecordingExecutor()
    pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)

    event = _make_event(event_id="evt-inv", bid=Decimal("64010"), ask=Decimal("64000"))
    result = pipeline.process_event(event)

    assert result.status is ValidationStatus.INVALID
    assert result.event_id == "evt-inv"
    assert result.enriched_event is None
    assert result.detection_results == ()
    assert len(result.validation_result.errors) == 1
    assert len(validator.calls) == 1
    assert len(enricher.calls) == 0
    assert len(executor.calls) == 0


def test_orchestrator_propagates_snapshots_to_enricher():
    validator = _RecordingValidator()
    enricher = _RecordingEnricher()
    executor = _RecordingExecutor()
    pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)

    event = _make_event()
    snap1 = _make_snapshot(source=EventSource.BYBIT)
    snap2 = _make_snapshot(source=EventSource.OKX)

    pipeline.process_event(event, (snap1, snap2))

    assert len(enricher.calls) == 1
    passed_event, passed_snapshots = enricher.calls[0]
    assert passed_event is event
    assert passed_snapshots == (snap1, snap2)


def test_orchestrator_passes_validated_event_to_enricher():
    validated = _make_event(event_id="validated-evt")
    validator = _RecordingValidator(
        result=ValidationResult(
            event_id="validated-evt",
            status=ValidationStatus.VALID,
            errors=(),
            validated_event=validated,
        )
    )
    enricher = _RecordingEnricher()
    executor = _RecordingExecutor()
    pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)

    raw_input_event = _make_event(event_id="input-evt")
    pipeline.process_event(raw_input_event)

    assert len(enricher.calls) == 1
    passed_event, _ = enricher.calls[0]
    assert passed_event is validated


def test_orchestrator_returns_detection_results():
    expected_result = DetectionResult(
        result_id="res-1",
        event_id="evt-1",
        module_id="test-module",
        timestamp=TS,
        asset="BTC",
        metric_value=Decimal("0.5"),
        threshold=Decimal("1.0"),
        anomaly_ratio=Decimal("0.5"),
        status=ResultStatus.NORMAL,
        persistence=0,
    )
    validator = _RecordingValidator()
    enricher = _RecordingEnricher()
    executor = _RecordingExecutor(results=(expected_result,))
    pipeline = EventPipeline(validator=validator, enricher=enricher, executor=executor)

    event = _make_event()
    result = pipeline.process_event(event)

    assert isinstance(result.detection_results, tuple)
    assert result.detection_results == (expected_result,)


def test_orchestrator_preserves_event_id():
    pipeline = _build_real_pipeline()
    event = _make_event(event_id="custom-trace-id-999")

    result = pipeline.process_event(event)

    assert result.event_id == "custom-trace-id-999"
    assert result.validation_result.event_id == "custom-trace-id-999"
    assert result.enriched_event is not None
    assert result.enriched_event.event_id == "custom-trace-id-999"
    assert len(result.detection_results) == 1
    assert result.detection_results[0].event_id == "custom-trace-id-999"


def test_orchestrator_rejects_none_event():
    pipeline = _build_real_pipeline()
    with pytest.raises(TypeError, match="event must not be None"):
        pipeline.process_event(None)  # type: ignore[arg-type]


def test_orchestrator_rejects_invalid_event_type():
    pipeline = _build_real_pipeline()
    with pytest.raises(TypeError, match="event must be an instance of NormalizedEvent"):
        pipeline.process_event({"event_id": "123"})  # type: ignore[arg-type]


def test_orchestrator_is_deterministic():
    pipeline = _build_real_pipeline()
    event = _make_event()
    snap = _make_snapshot()

    result1 = pipeline.process_event(event, (snap,))
    result2 = pipeline.process_event(event, (snap,))

    assert result1 == result2


def test_pipeline_execution_result_contract():
    event = _make_event()
    val_result = ValidationResult(
        event_id=event.event_id,
        status=ValidationStatus.VALID,
        errors=(),
        validated_event=event,
    )
    pipeline_result = PipelineExecutionResult(
        event_id=event.event_id,
        status=ValidationStatus.VALID,
        validation_result=val_result,
        enriched_event=None,
        detection_results=(),
    )

    dumped = pipeline_result.model_dump(by_alias=True)
    assert dumped["eventId"] == event.event_id
    assert dumped["status"] == "VALID"
    assert dumped["validationResult"]["status"] == "VALID"
    assert dumped["enrichedEvent"] is None
    assert dumped["detectionResults"] == ()

    with pytest.raises(PydanticValidationError):
        # frozen=True
        pipeline_result.status = ValidationStatus.INVALID  # type: ignore[misc]

    with pytest.raises(PydanticValidationError):
        # extra="forbid"
        PipelineExecutionResult(
            event_id="evt-1",
            status=ValidationStatus.VALID,
            validation_result=val_result,
            unknown_arg="invalid",  # type: ignore[call-arg]
        )


def test_pipeline_does_not_execute_downstream_on_invalid():
    real_pipeline = _build_real_pipeline()
    # bid > ask fails semantic validation
    invalid_event = _make_event(bid=Decimal("65000"), ask=Decimal("64000"))

    result = real_pipeline.process_event(invalid_event)

    assert result.status is ValidationStatus.INVALID
    assert result.enriched_event is None
    assert result.detection_results == ()
    assert len(result.validation_result.errors) == 1
    assert result.validation_result.errors[0].code == "BID_EXCEEDS_ASK"
