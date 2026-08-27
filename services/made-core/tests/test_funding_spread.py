"""Unit tests for FundingSpreadModule.

Covers:
- Normal / anomaly / boundary detection
- Insufficient-context scenarios
- Deterministic observation selection
- Result structure and metadata
- Edge cases (negative rates, zero spread)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from made_core.domain.enums import EventSource, MarketType, ResultStatus
from made_core.domain.models import (
    DetectionResult,
    EnrichedEvent,
    MarketContext,
    MarketSnapshot,
    NormalizedEvent,
)
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule

TS = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(
    source: EventSource = EventSource.BINANCE,
    market_type: MarketType = MarketType.FUTURES,
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("64000"),
    funding_rate: Decimal | None = Decimal("0.0001"),
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=TS,
        source=source,
        market_type=market_type,
        asset=asset,
        symbol=symbol,
        price=price,
        bid=price - Decimal("1"),
        ask=price + Decimal("1"),
        volume=Decimal("100"),
        funding_rate=funding_rate,
    )


def _enriched(
    *snapshots: MarketSnapshot,
    market_type: MarketType = MarketType.FUTURES,
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
) -> EnrichedEvent:
    normalized = NormalizedEvent(
        event_id="event-1",
        timestamp=TS,
        source=EventSource.BINANCE,
        market_type=market_type,
        asset=asset,
        symbol=symbol,
        price=Decimal("64000"),
        bid=Decimal("63999"),
        ask=Decimal("64001"),
        volume=Decimal("12"),
    )
    context = MarketContext(
        asset=asset,
        symbol=symbol,
        snapshots=snapshots if snapshots else (_snapshot(),),
    )
    return EnrichedEvent(
        event_id="event-1",
        timestamp=TS,
        asset=asset,
        market_context=context,
        normalized_data=normalized,
    )


def _module(threshold: Decimal = Decimal("0.0005")) -> FundingSpreadModule:
    return FundingSpreadModule(FundingSpreadConfig(threshold=threshold))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestFundingSpreadConfig:
    def test_accepts_positive_threshold(self):
        config = FundingSpreadConfig(threshold=Decimal("0.001"))
        assert config.threshold == Decimal("0.001")

    def test_rejects_zero_threshold(self):
        with pytest.raises(ValueError, match="threshold must be greater than zero"):
            FundingSpreadConfig(threshold=Decimal("0"))

    def test_rejects_negative_threshold(self):
        with pytest.raises(ValueError, match="threshold must be greater than zero"):
            FundingSpreadConfig(threshold=Decimal("-0.001"))


# ---------------------------------------------------------------------------
# Module identity
# ---------------------------------------------------------------------------


class TestModuleIdentity:
    def test_module_id_is_funding_spread(self):
        assert _module().get_module_id() == "funding-spread"

    def test_detect_rejects_none_event(self):
        with pytest.raises(TypeError, match="event must not be None"):
            _module().detect(None)


# ---------------------------------------------------------------------------
# Normal detection (below threshold)
# ---------------------------------------------------------------------------


class TestNormalDetection:
    def test_normal_when_funding_spread_below_threshold(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module(threshold=Decimal("0.0005")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0.0001")

    def test_normal_when_zero_funding_spread(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0003"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0003"))
        result = _module(threshold=Decimal("0.001")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")
        assert result.anomaly_ratio == Decimal("0")

    def test_normal_when_very_small_funding_spread(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.00010000"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.00010001"))
        result = _module(threshold=Decimal("0.001")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0.00000001")

    def test_zero_spread_is_normal_when_threshold_positive(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0001"))
        result = _module(threshold=Decimal("0.001")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")


# ---------------------------------------------------------------------------
# Anomaly detection (at or above threshold)
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    def test_anomaly_when_funding_spread_above_threshold(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.005"))
        result = _module(threshold=Decimal("0.002")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.ANOMALY
        assert result.metric_value == Decimal("0.004")

    def test_anomaly_when_funding_spread_exactly_at_threshold(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.003"))
        result = _module(threshold=Decimal("0.002")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.ANOMALY
        assert result.metric_value == Decimal("0.002")
        assert result.anomaly_ratio == Decimal("1")


# ---------------------------------------------------------------------------
# Insufficient context
# ---------------------------------------------------------------------------


class TestInsufficientContext:
    def test_insufficient_when_non_futures_trigger_spot(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2, market_type=MarketType.SPOT))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")
        assert result.metadata["insufficientContextReason"] == "insufficient_funding_context"

    def test_insufficient_when_non_futures_trigger_dex(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2, market_type=MarketType.DEX))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")
        assert result.metadata["insufficientContextReason"] == "insufficient_funding_context"

    def test_insufficient_when_no_futures_snapshots(self):
        snap = _snapshot(
            source=EventSource.BINANCE,
            market_type=MarketType.SPOT,
            funding_rate=Decimal("0.0001"),
        )
        result = _module().detect(_enriched(snap, market_type=MarketType.FUTURES))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")

    def test_insufficient_when_only_one_futures_funding_observation(self):
        snap = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        result = _module().detect(_enriched(snap))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")
        assert result.metadata["insufficientContextReason"] == "insufficient_funding_context"

    def test_insufficient_when_two_futures_same_source(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0005"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")

    def test_insufficient_when_funding_rate_missing_on_one(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=None)
        result = _module().detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")

    def test_insufficient_when_funding_rate_missing_on_all(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=None)
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=None)
        result = _module().detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")

    def test_insufficient_when_symbol_does_not_match_normalized_event(self):
        """Snapshots match the context but differ from the normalized event symbol."""
        normalized = NormalizedEvent(
            event_id="event-1", timestamp=TS, source=EventSource.BINANCE,
            market_type=MarketType.FUTURES, asset="BTC", symbol="BTCUSD",
            price=Decimal("64000"), bid=Decimal("63999"), ask=Decimal("64001"), volume=Decimal("12"),
        )
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.001"))
        context = MarketContext(asset="BTC", symbol="BTCUSDT", snapshots=(snap1, snap2))
        event = EnrichedEvent(
            event_id="event-1", timestamp=TS, asset="BTC",
            market_context=context, normalized_data=normalized,
        )
        result = _module().detect(event)

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0")
        assert result.metadata["insufficientContextReason"] == "insufficient_funding_context"


# ---------------------------------------------------------------------------
# Observation selection
# ---------------------------------------------------------------------------


class TestObservationSelection:
    def test_selects_first_distinct_source_pair(self):
        snap_binance = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap_bybit = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0008"))
        snap_okx = _snapshot(source=EventSource.OKX, funding_rate=Decimal("0.0020"))
        result = _module(threshold=Decimal("0.001")).detect(
            _enriched(snap_binance, snap_bybit, snap_okx),
        )

        # Selects Binance (0.0001) + Bybit (0.0008) → spread = 0.0007
        assert result.metric_value == Decimal("0.0007")
        assert result.status is ResultStatus.NORMAL

    def test_skips_same_source_selects_first_distinct(self):
        snap_bin1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap_bin2 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0002"))
        snap_bybit = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.001"))
        result = _module(threshold=Decimal("0.0005")).detect(
            _enriched(snap_bin1, snap_bin2, snap_bybit),
        )

        # First distinct pair: Binance (0.0001) + Bybit (0.001) → spread = 0.0009
        assert result.metric_value == Decimal("0.0009")
        assert result.status is ResultStatus.ANOMALY

    def test_skips_snapshots_without_funding_rate(self):
        snap_no_rate = _snapshot(source=EventSource.BINANCE, funding_rate=None)
        snap_with_rate1 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0001"))
        snap_with_rate2 = _snapshot(source=EventSource.OKX, funding_rate=Decimal("0.0003"))
        result = _module(threshold=Decimal("0.001")).detect(
            _enriched(snap_no_rate, snap_with_rate1, snap_with_rate2),
        )

        # Skips Binance (no rate), selects Bybit + OKX → spread = 0.0002
        assert result.metric_value == Decimal("0.0002")
        assert result.metadata["sources"] == ["BYBIT", "OKX"]

    def test_skips_non_futures_snapshots(self):
        snap_spot = _snapshot(source=EventSource.BINANCE, market_type=MarketType.SPOT,
                              funding_rate=Decimal("0.0001"))
        snap_futures1 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        snap_futures2 = _snapshot(source=EventSource.OKX, funding_rate=Decimal("0.0005"))
        result = _module(threshold=Decimal("0.001")).detect(
            _enriched(snap_spot, snap_futures1, snap_futures2),
        )

        # Skips SPOT, selects Bybit + OKX → spread = 0.0003
        assert result.metric_value == Decimal("0.0003")
        assert result.metadata["sources"] == ["BYBIT", "OKX"]


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------


class TestResultStructure:
    def test_result_is_detection_result(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert isinstance(result, DetectionResult)

    def test_result_contains_correct_module_id(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.module_id == "funding-spread"

    def test_result_contains_correct_result_id(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.result_id == "event-1:funding-spread"

    def test_result_contains_correct_threshold(self):
        threshold = Decimal("0.003")
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module(threshold=threshold).detect(_enriched(snap1, snap2))

        assert result.threshold == threshold

    def test_result_anomaly_ratio_is_spread_over_threshold(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.004"))
        result = _module(threshold=Decimal("0.002")).detect(_enriched(snap1, snap2))

        # spread = 0.003, threshold = 0.002, ratio = 1.5
        assert result.anomaly_ratio == Decimal("1.5")

    def test_result_contains_source_metadata(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.metadata["sources"] == ["BINANCE", "BYBIT"]

    def test_result_contains_symbol_metadata(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.metadata["symbols"] == ["BTCUSDT", "BTCUSDT"]

    def test_result_contains_funding_rates_metadata(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.metadata["fundingRates"] == [Decimal("0.0001"), Decimal("0.0002")]

    def test_insufficient_result_has_no_funding_rates_metadata(self):
        snap = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        result = _module().detect(_enriched(snap))

        assert "fundingRates" not in result.metadata

    def test_result_event_id_matches_input(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        event = _enriched(snap1, snap2)
        result = _module().detect(event)

        assert result.event_id == event.event_id

    def test_result_asset_matches_input(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        event = _enriched(snap1, snap2)
        result = _module().detect(event)

        assert result.asset == event.asset

    def test_result_persistence_is_zero(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0001"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("0.0002"))
        result = _module().detect(_enriched(snap1, snap2))

        assert result.persistence == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_negative_funding_rates(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("-0.0002"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("-0.0001"))
        result = _module(threshold=Decimal("0.001")).detect(_enriched(snap1, snap2))

        assert result.status is ResultStatus.NORMAL
        assert result.metric_value == Decimal("0.0001")

    def test_one_positive_one_negative_funding_rate(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.0003"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("-0.0002"))
        result = _module(threshold=Decimal("0.0004")).detect(_enriched(snap1, snap2))

        # spread = |0.0003 - (-0.0002)| = 0.0005
        assert result.status is ResultStatus.ANOMALY
        assert result.metric_value == Decimal("0.0005")

    def test_large_funding_rate_difference(self):
        snap1 = _snapshot(source=EventSource.BINANCE, funding_rate=Decimal("0.01"))
        snap2 = _snapshot(source=EventSource.BYBIT, funding_rate=Decimal("-0.01"))
        result = _module(threshold=Decimal("0.005")).detect(_enriched(snap1, snap2))

        # spread = 0.02
        assert result.status is ResultStatus.ANOMALY
        assert result.metric_value == Decimal("0.02")
        assert result.anomaly_ratio == Decimal("4")
