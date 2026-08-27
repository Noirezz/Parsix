"""Unit tests for NormalizedEventValidator and validation domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from made_core.application.validator import NormalizedEventValidator
from made_core.domain.enums import EventSource, MarketType, ValidationStatus
from made_core.domain.interfaces import EventValidator
from made_core.domain.models import NormalizedEvent, ValidationError, ValidationResult

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


def test_validator_implements_event_validator_protocol():
    assert EventValidator in NormalizedEventValidator.__mro__
    validator = NormalizedEventValidator()
    assert callable(getattr(validator, "validate", None))


def test_valid_event_passes_validation():
    validator = NormalizedEventValidator()
    event = _make_event(bid=Decimal("63999"), ask=Decimal("64001"))

    result = validator.validate(event)

    assert isinstance(result, ValidationResult)
    assert result.status is ValidationStatus.VALID
    assert result.event_id == event.event_id
    assert result.errors == ()
    assert result.validated_event is event


def test_bid_exceeds_ask_fails_validation():
    validator = NormalizedEventValidator()
    event = _make_event(bid=Decimal("64010"), ask=Decimal("64000"))

    result = validator.validate(event)

    assert isinstance(result, ValidationResult)
    assert result.status is ValidationStatus.INVALID
    assert result.event_id == event.event_id
    assert result.validated_event is None
    assert len(result.errors) == 1

    error = result.errors[0]
    assert isinstance(error, ValidationError)
    assert error.code == "BID_EXCEEDS_ASK"
    assert error.field == "bid,ask"
    assert error.event_id == event.event_id
    assert "Bid price (64010) cannot exceed ask price (64000)" in error.message


def test_bid_equals_ask_passes_validation():
    validator = NormalizedEventValidator()
    event = _make_event(bid=Decimal("64000"), ask=Decimal("64000"))

    result = validator.validate(event)

    assert result.status is ValidationStatus.VALID
    assert result.errors == ()
    assert result.validated_event is event


def test_event_id_propagated_in_result_and_errors():
    validator = NormalizedEventValidator()
    event = _make_event(event_id="custom-event-uuid-1234", bid=Decimal("105"), ask=Decimal("100"))

    result = validator.validate(event)

    assert result.event_id == "custom-event-uuid-1234"
    assert len(result.errors) == 1
    assert result.errors[0].event_id == "custom-event-uuid-1234"


def test_validator_rejects_none_event():
    validator = NormalizedEventValidator()
    with pytest.raises(TypeError, match="event must not be None"):
        validator.validate(None)


def test_validator_rejects_invalid_event_type():
    validator = NormalizedEventValidator()
    with pytest.raises(TypeError, match="event must be an instance of NormalizedEvent"):
        validator.validate({"bid": 100, "ask": 105})  # type: ignore[arg-type]


def test_validator_is_deterministic_and_side_effect_free():
    validator = NormalizedEventValidator()
    event = _make_event(bid=Decimal("64010"), ask=Decimal("64000"))

    result1 = validator.validate(event)
    result2 = validator.validate(event)

    assert result1 == result2
    assert event.bid == Decimal("64010")
    assert event.ask == Decimal("64000")


def test_validation_result_and_error_model_contracts():
    error = ValidationError(
        code="BID_EXCEEDS_ASK",
        message="Invalid spread",
        field="bid,ask",
        event_id="evt-1",
    )
    result = ValidationResult(
        event_id="evt-1",
        status=ValidationStatus.INVALID,
        errors=(error,),
        validated_event=None,
    )

    dumped = result.model_dump(by_alias=True)
    assert dumped["eventId"] == "evt-1"
    assert dumped["status"] == "INVALID"
    assert dumped["validatedEvent"] is None
    assert len(dumped["errors"]) == 1
    assert dumped["errors"][0]["code"] == "BID_EXCEEDS_ASK"

    with pytest.raises(PydanticValidationError):
        # Immutable / frozen
        result.status = ValidationStatus.VALID  # type: ignore[misc]

    with pytest.raises(PydanticValidationError):
        # extra="forbid"
        ValidationResult(
            event_id="evt-1",
            status=ValidationStatus.VALID,
            unknown_field=123,  # type: ignore[call-arg]
        )
