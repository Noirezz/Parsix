from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from made_core.domain.enums import EventSource, MarketType, Priority, ResultStatus
from made_core.domain.models import (
    AggregatedResult, Alert, CorrelatedGroup, DetectionResult, EnrichedEvent,
    MarketContext, NormalizedEvent, RawEvent,
)


def test_raw_event_accepts_source_payload_and_metadata(timestamp):
    event = RawEvent(event_id="raw-1", timestamp=timestamp, source=EventSource.BINANCE, payload={"price": "64000"})
    assert event.metadata == {}
    assert event.source is EventSource.BINANCE


def test_normalized_event_accepts_canonical_camel_case_contract_fields(timestamp):
    event = NormalizedEvent.model_validate({
        "eventId": "event-1", "timestamp": timestamp, "source": "BINANCE", "marketType": "SPOT",
        "asset": "BTC", "symbol": "BTCUSDT", "price": "64000", "bid": "63999", "ask": "64001", "volume": "12",
        "metadata": {},
    })
    assert event.model_dump(by_alias=True)["eventId"] == "event-1"


def test_normalized_event_rejects_negative_price(timestamp):
    with pytest.raises(ValidationError):
        NormalizedEvent(
            event_id="event-1", timestamp=timestamp, source=EventSource.BINANCE,
            market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT",
            price=Decimal("-1"), bid=Decimal("1"), ask=Decimal("2"), volume=Decimal("1"),
        )


def test_normalized_event_rejects_naive_timestamp(timestamp):
    with pytest.raises(ValidationError):
        NormalizedEvent(
            event_id="event-1", timestamp=datetime(2026, 8, 23), source=EventSource.BINANCE,
            market_type=MarketType.SPOT, asset="BTC", symbol="BTCUSDT",
            price=Decimal("1"), bid=Decimal("1"), ask=Decimal("2"), volume=Decimal("1"),
        )


def test_enriched_event_links_normalized_event_and_context(timestamp, normalized_event, market_snapshot):
    context = MarketContext(asset="BTC", symbol="BTCUSDT", snapshots=(market_snapshot,))
    enriched = EnrichedEvent(
        event_id=normalized_event.event_id, timestamp=timestamp, asset="BTC", market_context=context,
        normalized_data=normalized_event, reference_data={"last": Decimal("64000")},
    )
    assert enriched.market_context.snapshots[0].symbol == "BTCUSDT"


def test_context_rejects_snapshot_for_another_asset(timestamp, market_snapshot):
    with pytest.raises(ValidationError):
        MarketContext(asset="ETH", symbol="BTCUSDT", snapshots=(market_snapshot,))


def test_aggregate_and_alert_contracts(timestamp):
    result = DetectionResult(
        result_id="result-1", event_id="event-1", module_id="futures-futures-spread", timestamp=timestamp,
        asset="BTC", metric_value=Decimal("2.5"), threshold=Decimal("1"), anomaly_ratio=Decimal("2.5"),
        status=ResultStatus.ANOMALY, persistence=1,
    )
    group = CorrelatedGroup(
        correlation_id="group-1", asset="BTC", window_start=timestamp, window_end=timestamp, results=(result,),
    )
    aggregate = AggregatedResult(
        aggregation_id="aggregate-1", timestamp=timestamp, asset="BTC", correlation_window=group,
        triggered_modules=(result.module_id,), module_count=1, composite_anomaly_score=Decimal("2.5"),
        max_anomaly_ratio=Decimal("2.5"), average_anomaly_ratio=Decimal("2.5"), priority=Priority.HIGH,
        source_results=(result,),
    )
    alert = Alert(
        alert_id="alert-1", timestamp=timestamp, asset="BTC", priority=aggregate.priority,
        title="BTC anomaly", summary="Spread threshold exceeded", anomaly_score=aggregate.composite_anomaly_score,
        triggered_modules=aggregate.triggered_modules,
    )
    assert alert.priority is Priority.HIGH


def test_aggregate_rejects_mismatched_module_count(timestamp):
    result = DetectionResult(
        result_id="result-1", event_id="event-1", module_id="module-1", timestamp=timestamp,
        asset="BTC", metric_value=Decimal("1"), threshold=Decimal("1"), anomaly_ratio=Decimal("1"),
        status=ResultStatus.ANOMALY, persistence=1,
    )
    group = CorrelatedGroup(correlation_id="group-1", asset="BTC", window_start=timestamp, window_end=timestamp, results=(result,))
    with pytest.raises(ValidationError):
        AggregatedResult(
            aggregation_id="aggregate-1", timestamp=timestamp, asset="BTC", correlation_window=group,
            triggered_modules=("module-1",), module_count=2, composite_anomaly_score=Decimal("1"),
            max_anomaly_ratio=Decimal("1"), average_anomaly_ratio=Decimal("1"), priority=Priority.LOW,
            source_results=(result,),
        )
