"""Unit tests for AnomalyProcessingPipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.application.anomaly_pipeline import AnomalyProcessingPipeline
from made_core.domain.enums import Priority, ResultStatus, ValidationStatus
from made_core.domain.interfaces import (
    AlertGenerator,
    CorrelationEngine,
    PriorityEvaluator,
    ResultAggregator,
)
from made_core.domain.models import (
    AggregatedResult,
    Alert,
    CorrelatedGroup,
    DetectionResult,
    PipelineExecutionResult,
    ValidationError,
    ValidationResult,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _make_result(
    *,
    result_id: str = "res-1",
    event_id: str = "evt-1",
    module_id: str = "futures-futures-spread",
    timestamp: datetime = TS,
    asset: str = "BTC",
    metric_value: Decimal = Decimal("2.0"),
    threshold: Decimal = Decimal("1.0"),
    anomaly_ratio: Decimal = Decimal("2.0"),
    status: ResultStatus = ResultStatus.ANOMALY,
) -> DetectionResult:
    return DetectionResult(
        result_id=result_id,
        event_id=event_id,
        module_id=module_id,
        timestamp=timestamp,
        asset=asset,
        metric_value=metric_value,
        threshold=threshold,
        anomaly_ratio=anomaly_ratio,
        status=status,
        persistence=0,
    )


class _RecordingAggregator(ResultAggregator):
    def __init__(self, return_val: AggregatedResult | None = None) -> None:
        self.calls: list[tuple[DetectionResult, ...]] = []
        self.return_val = return_val

    def aggregate(self, results, correlation_window=None):
        self.calls.append(tuple(results))
        return self.return_val


class _RecordingAlertGenerator(AlertGenerator):
    def __init__(self, return_val: Alert | None = None) -> None:
        self.calls: list[AggregatedResult] = []
        self.return_val = return_val

    def generate(self, aggregate):
        self.calls.append(aggregate)
        return self.return_val


def test_normal_only_results_produce_no_alert():
    pipeline = AnomalyProcessingPipeline()
    r1 = _make_result(status=ResultStatus.NORMAL, anomaly_ratio=Decimal("0.5"))
    r2 = _make_result(status=ResultStatus.NORMAL, anomaly_ratio=Decimal("0.8"))

    alert = pipeline.process_results((r1, r2))
    assert alert is None


def test_empty_results_produce_no_alert():
    pipeline = AnomalyProcessingPipeline()
    assert pipeline.process_results(()) is None


def test_single_anomaly_medium_produces_alert():
    pipeline = AnomalyProcessingPipeline()
    r = _make_result(anomaly_ratio=Decimal("2.0"), status=ResultStatus.ANOMALY)

    alert = pipeline.process_results((r,))

    assert isinstance(alert, Alert)
    assert alert.priority is Priority.MEDIUM
    assert alert.asset == "BTC"
    assert alert.title == "[MEDIUM] BTC anomaly detected"


def test_single_anomaly_low_produces_no_alert():
    pipeline = AnomalyProcessingPipeline()
    r = _make_result(anomaly_ratio=Decimal("1.2"), status=ResultStatus.ANOMALY)

    alert = pipeline.process_results((r,))
    assert alert is None


def test_multiple_anomalies_produce_high_alert():
    pipeline = AnomalyProcessingPipeline()
    r1 = _make_result(
        result_id="res-1",
        module_id="futures-futures-spread",
        anomaly_ratio=Decimal("1.8"),
    )
    r2 = _make_result(
        result_id="res-2",
        module_id="spot-futures-spread",
        anomaly_ratio=Decimal("2.2"),
    )

    alert = pipeline.process_results((r1, r2))

    assert isinstance(alert, Alert)
    assert alert.priority is Priority.HIGH
    assert alert.title == "[HIGH] BTC anomaly detected"
    assert alert.triggered_modules == ("futures-futures-spread", "spot-futures-spread")


def test_single_anomaly_high_ratio_produces_high_alert():
    pipeline = AnomalyProcessingPipeline()
    r = _make_result(anomaly_ratio=Decimal("3.5"), status=ResultStatus.ANOMALY)

    alert = pipeline.process_results((r,))

    assert isinstance(alert, Alert)
    assert alert.priority is Priority.HIGH
    assert alert.title == "[HIGH] BTC anomaly detected"


def test_process_pipeline_result_with_valid_event():
    pipeline = AnomalyProcessingPipeline()
    r = _make_result(anomaly_ratio=Decimal("2.0"), status=ResultStatus.ANOMALY)
    val_res = ValidationResult(
        event_id="evt-1",
        status=ValidationStatus.VALID,
        errors=(),
        validated_event=None,
    )
    pipe_res = PipelineExecutionResult(
        event_id="evt-1",
        status=ValidationStatus.VALID,
        validation_result=val_res,
        enriched_event=None,
        detection_results=(r,),
    )

    alert = pipeline.process_pipeline_result(pipe_res)

    assert isinstance(alert, Alert)
    assert alert.priority is Priority.MEDIUM


def test_process_pipeline_result_with_invalid_event_stops():
    pipeline = AnomalyProcessingPipeline()
    r = _make_result(anomaly_ratio=Decimal("2.0"), status=ResultStatus.ANOMALY)
    val_res = ValidationResult(
        event_id="evt-1",
        status=ValidationStatus.INVALID,
        errors=(
            ValidationError(
                code="BID_EXCEEDS_ASK",
                message="invalid",
                field="bid,ask",
                event_id="evt-1",
            ),
        ),
        validated_event=None,
    )
    pipe_res = PipelineExecutionResult(
        event_id="evt-1",
        status=ValidationStatus.INVALID,
        validation_result=val_res,
        enriched_event=None,
        detection_results=(r,),
    )

    alert = pipeline.process_pipeline_result(pipe_res)
    assert alert is None


def test_dependency_injection_with_custom_stubs():
    mock_aggregator = _RecordingAggregator()
    mock_alert_gen = _RecordingAlertGenerator()

    pipeline = AnomalyProcessingPipeline(
        aggregator=mock_aggregator,
        alert_generator=mock_alert_gen,
    )

    r = _make_result(status=ResultStatus.ANOMALY)
    pipeline.process_results((r,))

    assert len(mock_aggregator.calls) == 1
    assert mock_aggregator.calls[0] == (r,)
    # If aggregator returned None, alert generator is not called
    assert len(mock_alert_gen.calls) == 0


def test_rejects_none_results():
    pipeline = AnomalyProcessingPipeline()
    with pytest.raises(TypeError, match="results must not be None"):
        pipeline.process_results(None)  # type: ignore[arg-type]


def test_rejects_invalid_elements_in_results():
    pipeline = AnomalyProcessingPipeline()
    with pytest.raises(TypeError, match="all elements in results must be DetectionResult instances"):
        pipeline.process_results(["invalid_type"])  # type: ignore[list-item]


def test_rejects_none_pipeline_result():
    pipeline = AnomalyProcessingPipeline()
    with pytest.raises(TypeError, match="pipeline_result must not be None"):
        pipeline.process_pipeline_result(None)  # type: ignore[arg-type]


def test_rejects_invalid_pipeline_result_type():
    pipeline = AnomalyProcessingPipeline()
    with pytest.raises(TypeError, match="pipeline_result must be an instance of PipelineExecutionResult"):
        pipeline.process_pipeline_result({"status": "VALID"})  # type: ignore[arg-type]


def test_deterministic_behavior():
    pipeline = AnomalyProcessingPipeline()
    r = _make_result(anomaly_ratio=Decimal("2.0"), status=ResultStatus.ANOMALY)

    alert1 = pipeline.process_results((r,))
    alert2 = pipeline.process_results((r,))

    assert alert1 is not None and alert2 is not None
    assert alert1 == alert2
