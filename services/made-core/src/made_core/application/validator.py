"""Application-layer validator for incoming NormalizedEvents."""

from __future__ import annotations

from made_core.domain.enums import ValidationStatus
from made_core.domain.interfaces import EventValidator
from made_core.domain.models import NormalizedEvent, ValidationError, ValidationResult


class NormalizedEventValidator(EventValidator):
    """Validates incoming NormalizedEvent against semantic domain rules."""

    def validate(self, event: NormalizedEvent) -> ValidationResult:
        if event is None:
            raise TypeError("event must not be None")
        if not isinstance(event, NormalizedEvent):
            raise TypeError("event must be an instance of NormalizedEvent")

        errors: list[ValidationError] = []

        if event.bid > event.ask:
            errors.append(
                ValidationError(
                    code="BID_EXCEEDS_ASK",
                    message=f"Bid price ({event.bid}) cannot exceed ask price ({event.ask})",
                    field="bid,ask",
                    event_id=event.event_id,
                )
            )

        if errors:
            return ValidationResult(
                event_id=event.event_id,
                status=ValidationStatus.INVALID,
                errors=tuple(errors),
                validated_event=None,
            )

        return ValidationResult(
            event_id=event.event_id,
            status=ValidationStatus.VALID,
            errors=(),
            validated_event=event,
        )
