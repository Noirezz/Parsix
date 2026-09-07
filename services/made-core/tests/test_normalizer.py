"""Unit tests for BinanceNormalizer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.ingestion.normalizer import BinanceNormalizer, NormalizerError


def _make_raw_event(
    payload: dict | None = None,
    metadata: dict | None = None,
) -> RawEvent:
    return RawEvent(
        event_id="raw-1",
        timestamp=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        source=EventSource.BINANCE,
        payload=payload
        if payload is not None
        else {
            "symbol": "BTCUSDT",
            "lastPrice": "64000.50000000",
            "bidPrice": "64000.00000000",
            "askPrice": "64001.00000000",
            "volume": "123.45670000",
            "closeTime": 1700000000000,
        },
        metadata=metadata if metadata is not None else {"asset": "BTC", "symbol": "BTCUSDT", "market_type": "SPOT"},
    )


def test_binance_normalizer_success():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event()
    norm = normalizer.normalize(raw)

    assert isinstance(norm, NormalizedEvent)
    assert norm.source == EventSource.BINANCE
    assert norm.market_type == MarketType.SPOT
    assert norm.asset == "BTC"
    assert norm.symbol == "BTCUSDT"
    assert norm.price == Decimal("64000.50000000")
    assert norm.bid == Decimal("64000.00000000")
    assert norm.ask == Decimal("64001.00000000")
    assert norm.volume == Decimal("123.45670000")
    assert norm.timestamp.tzinfo is not None


def test_binance_normalizer_preserves_decimal_precision():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event(
        payload={
            "symbol": "ETHUSDT",
            "lastPrice": "3456.78912345",
            "bidPrice": "3456.78912340",
            "askPrice": "3456.78912350",
            "volume": "0.00001234",
        },
        metadata={"asset": "ETH", "symbol": "ETHUSDT", "market_type": "FUTURES"},
    )
    norm = normalizer.normalize(raw)

    assert norm.market_type == MarketType.FUTURES
    assert norm.price == Decimal("3456.78912345")
    assert norm.bid == Decimal("3456.78912340")
    assert norm.ask == Decimal("3456.78912350")
    assert norm.volume == Decimal("0.00001234")


def test_binance_normalizer_asset_fallback_inference():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event(
        payload={
            "symbol": "SOLUSDT",
            "bidPrice": "145.50",
            "askPrice": "145.60",
        },
        metadata={},  # Empty metadata
    )
    norm = normalizer.normalize(raw)

    assert norm.asset == "SOL"
    assert norm.symbol == "SOLUSDT"
    assert norm.price == Decimal("145.55")  # Mid price (145.50 + 145.60) / 2


def test_binance_normalizer_rejects_none():
    normalizer = BinanceNormalizer()
    with pytest.raises(NormalizerError, match="raw_event must not be None"):
        normalizer.normalize(None)  # type: ignore[arg-type]


def test_binance_normalizer_rejects_missing_symbol():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event(
        payload={"bidPrice": "100.0", "askPrice": "101.0"},
        metadata={},
    )
    with pytest.raises(NormalizerError, match="valid symbol identifier"):
        normalizer.normalize(raw)


def test_binance_normalizer_rejects_missing_price_fields():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event(
        payload={"symbol": "BTCUSDT"},
    )
    with pytest.raises(NormalizerError, match="Missing required price fields"):
        normalizer.normalize(raw)


def test_binance_normalizer_rejects_malformed_numeric():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event(
        payload={"symbol": "BTCUSDT", "bidPrice": "invalid_decimal", "askPrice": "64000.0"},
    )
    with pytest.raises(NormalizerError, match="Invalid numeric value"):
        normalizer.normalize(raw)


def test_binance_normalizer_futures_funding_rate():
    normalizer = BinanceNormalizer()
    raw = _make_raw_event(
        payload={
            "symbol": "BTCUSDT",
            "bidPrice": "65000",
            "askPrice": "65001",
            "lastPrice": "65000.5",
            "fundingRate": "0.00010000",
            "closeTime": 1700000000000,
        },
        metadata={"asset": "BTC", "symbol": "BTCUSDT", "market_type": "FUTURES"},
    )
    norm = normalizer.normalize(raw)

    assert norm.market_type == MarketType.FUTURES
    assert Decimal(str(norm.metadata.get("funding_rate"))) == Decimal("0.0001")
    assert norm.event_id == "norm:binance:BTCUSDT:futures:1700000000000"


def test_binance_normalizer_deterministic_event_id_duplicate_stability():
    normalizer = BinanceNormalizer()
    payload = {
        "symbol": "BTCUSDT",
        "bidPrice": "65000",
        "askPrice": "65001",
        "lastPrice": "65000.5",
        "closeTime": 1700000000000,
    }
    raw1 = _make_raw_event(payload=payload, metadata={"market_type": "SPOT"})
    raw2 = _make_raw_event(payload=payload, metadata={"market_type": "SPOT"})

    norm1 = normalizer.normalize(raw1)
    norm2 = normalizer.normalize(raw2)

    assert norm1.event_id == norm2.event_id == "norm:binance:BTCUSDT:spot:1700000000000"
