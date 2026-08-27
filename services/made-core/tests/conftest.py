from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import MarketSnapshot, NormalizedEvent


@pytest.fixture
def timestamp() -> datetime:
    return datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def normalized_event(timestamp: datetime) -> NormalizedEvent:
    return NormalizedEvent(
        event_id="event-1", timestamp=timestamp, source=EventSource.BINANCE,
        market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSDT",
        price=Decimal("64000"), bid=Decimal("63999"), ask=Decimal("64001"), volume=Decimal("12"),
    )


@pytest.fixture
def market_snapshot(timestamp: datetime) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp, source=EventSource.BINANCE, market_type=MarketType.FUTURES,
        asset="BTC", symbol="BTCUSDT", price=Decimal("64000"), bid=Decimal("63999"),
        ask=Decimal("64001"), volume=Decimal("12"),
    )
