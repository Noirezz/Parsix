"""Application-layer context enrichment for validated NormalizedEvents."""

from __future__ import annotations

from collections.abc import Sequence

from decimal import Decimal, InvalidOperation

from made_core.domain.interfaces import ContextEnricher
from made_core.domain.models import EnrichedEvent, MarketContext, MarketSnapshot, NormalizedEvent


class DefaultContextEnricher(ContextEnricher):
    """Assembles matching market snapshots and constructs an EnrichedEvent."""

    def enrich(
        self,
        event: NormalizedEvent,
        snapshots: Sequence[MarketSnapshot] = (),
    ) -> EnrichedEvent:
        if event is None:
            raise TypeError("event must not be None")
        if not isinstance(event, NormalizedEvent):
            raise TypeError("event must be an instance of NormalizedEvent")

        matching_snapshots: list[MarketSnapshot] = [
            s
            for s in snapshots
            if s.asset == event.asset and s.symbol == event.symbol
        ]

        funding_rate: Decimal | None = None
        raw_funding = event.metadata.get("funding_rate") or event.metadata.get("fundingRate")
        if raw_funding is not None:
            try:
                funding_rate = Decimal(str(raw_funding))
            except (InvalidOperation, TypeError, ValueError):
                funding_rate = None

        self_snapshot = MarketSnapshot(
            timestamp=event.timestamp,
            source=event.source,
            market_type=event.market_type,
            asset=event.asset,
            symbol=event.symbol,
            price=event.price,
            bid=event.bid,
            ask=event.ask,
            volume=event.volume,
            funding_rate=funding_rate,
            metadata=event.metadata.copy(),
        )

        if not matching_snapshots:
            matching_snapshots.append(self_snapshot)

        context = MarketContext(
            asset=event.asset,
            symbol=event.symbol,
            snapshots=tuple(matching_snapshots),
        )

        return EnrichedEvent(
            event_id=event.event_id,
            timestamp=event.timestamp,
            asset=event.asset,
            market_context=context,
            normalized_data=event,
        )
