"""Normalizers converting raw exchange events into canonical NormalizedEvents."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent

logger = logging.getLogger(__name__)


class NormalizerError(Exception):
    """Exception raised when payload normalization fails."""


def _derive_asset_from_symbol(symbol: str) -> str:
    """Derive base asset from common quote currencies if asset is not explicitly specified."""
    for quote in ("USDT", "BUSD", "USDC", "FDUSD", "BTC", "ETH"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)]
    return symbol


class BinanceNormalizer:
    """Normalizes raw Binance Spot and Futures events into canonical NormalizedEvent domain models."""

    def normalize(self, raw_event: RawEvent) -> NormalizedEvent:
        """Transform a RawEvent from Binance into a canonical NormalizedEvent."""
        if raw_event is None:
            raise NormalizerError("raw_event must not be None")
        if not isinstance(raw_event, RawEvent):
            raise NormalizerError(f"Expected RawEvent, got {type(raw_event)}")

        payload = raw_event.payload
        if not isinstance(payload, dict):
            raise NormalizerError(f"Expected dictionary payload, got {type(payload)}")

        metadata = (raw_event.metadata or {}).copy()
        symbol = str(payload.get("symbol") or metadata.get("symbol") or "").strip().upper()
        if not symbol:
            raise NormalizerError("Payload does not contain a valid symbol identifier")

        asset = str(metadata.get("asset") or "").strip().upper()
        if not asset:
            asset = _derive_asset_from_symbol(symbol)

        market_type_raw = metadata.get("market_type") or metadata.get("marketType") or "SPOT"
        try:
            market_type = MarketType(str(market_type_raw).upper())
        except ValueError:
            market_type = MarketType.SPOT

        # Extract numeric fields with strict Decimal precision
        try:
            bid_raw = payload.get("bidPrice") or payload.get("bid") or payload.get("b")
            ask_raw = payload.get("askPrice") or payload.get("ask") or payload.get("a")
            price_raw = payload.get("lastPrice") or payload.get("price") or payload.get("c")

            if bid_raw is None and ask_raw is None and price_raw is None:
                raise NormalizerError("Missing required price fields in Binance payload")

            if price_raw is not None:
                price = Decimal(str(price_raw))
            elif bid_raw is not None and ask_raw is not None:
                price = (Decimal(str(bid_raw)) + Decimal(str(ask_raw))) / Decimal("2")
            else:
                price = Decimal(str(bid_raw or ask_raw))

            bid = Decimal(str(bid_raw)) if bid_raw is not None else price
            ask = Decimal(str(ask_raw)) if ask_raw is not None else price

            vol_raw = payload.get("volume") or payload.get("vol") or payload.get("v") or "0"
            volume = Decimal(str(vol_raw))

        except (InvalidOperation, TypeError, ValueError) as exc:
            raise NormalizerError(f"Invalid numeric value in Binance payload: {exc}") from exc

        # Funding rate extraction for Futures
        if market_type is MarketType.FUTURES:
            raw_funding = payload.get("fundingRate") or payload.get("lastFundingRate")
            if raw_funding is not None and str(raw_funding).strip() != "":
                try:
                    metadata["funding_rate"] = str(Decimal(str(raw_funding)))
                except (InvalidOperation, TypeError, ValueError):
                    pass

        # Timestamp and deterministic Event ID
        close_time = payload.get("closeTime") or payload.get("time") or payload.get("E")
        if close_time is not None:
            try:
                ts = datetime.fromtimestamp(float(close_time) / 1000.0, tz=UTC)
            except (ValueError, OSError, OverflowError):
                ts = raw_event.timestamp
            event_id = f"norm:binance:{symbol}:{market_type.value.lower()}:{close_time}"
        else:
            ts = raw_event.timestamp
            event_id = f"norm:binance:{symbol}:{market_type.value.lower()}:{int(ts.timestamp() * 1000)}"

        return NormalizedEvent(
            event_id=event_id,
            timestamp=ts,
            source=EventSource.BINANCE,
            market_type=market_type,
            asset=asset,
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            volume=volume,
            metadata={
                "raw_event_id": raw_event.event_id,
                **metadata,
            },
        )

    def normalize_batch(self, raw_events: Sequence[RawEvent]) -> list[NormalizedEvent]:
        """Normalize a sequence of raw events, filtering out invalid or unpriced items."""
        results: list[NormalizedEvent] = []
        for raw in raw_events:
            try:
                norm = self.normalize(raw)
                if norm.price > 0:
                    results.append(norm)
            except Exception as exc:
                logger.debug("Skipping invalid Binance event %s: %s", getattr(raw, "event_id", "unknown"), exc)
        return results


class BybitNormalizer:
    """Normalizes raw Bybit Spot and Linear/Futures events into canonical NormalizedEvent domain models."""

    def normalize(self, raw_event: RawEvent) -> NormalizedEvent:
        """Transform a RawEvent from Bybit into a canonical NormalizedEvent."""
        if raw_event is None:
            raise NormalizerError("raw_event must not be None")
        if not isinstance(raw_event, RawEvent):
            raise NormalizerError(f"Expected RawEvent, got {type(raw_event)}")

        payload = raw_event.payload
        if not isinstance(payload, dict):
            raise NormalizerError(f"Expected dictionary payload, got {type(payload)}")

        metadata = (raw_event.metadata or {}).copy()
        symbol = str(payload.get("symbol") or metadata.get("symbol") or "").strip().upper()
        if not symbol:
            raise NormalizerError("Payload does not contain a valid symbol identifier")

        asset = str(metadata.get("asset") or "").strip().upper()
        if not asset:
            asset = _derive_asset_from_symbol(symbol)

        market_type_raw = metadata.get("market_type") or metadata.get("marketType") or "SPOT"
        try:
            market_type = MarketType(str(market_type_raw).upper())
        except ValueError:
            market_type = MarketType.SPOT

        # Extract numeric fields with strict Decimal precision
        try:
            bid_raw = payload.get("bid1Price") or payload.get("bidPrice") or payload.get("bid")
            if bid_raw is None or str(bid_raw).strip() == "":
                raise NormalizerError("Missing required field 'bid1Price' in Bybit payload")
            bid = Decimal(str(bid_raw))

            ask_raw = payload.get("ask1Price") or payload.get("askPrice") or payload.get("ask")
            if ask_raw is None or str(ask_raw).strip() == "":
                raise NormalizerError("Missing required field 'ask1Price' in Bybit payload")
            ask = Decimal(str(ask_raw))

            price_raw = payload.get("lastPrice") or payload.get("price")
            if price_raw is not None and str(price_raw).strip() != "":
                price = Decimal(str(price_raw))
            else:
                price = (bid + ask) / Decimal("2")

            vol_raw = payload.get("volume24h") or payload.get("volume") or "0"
            volume = Decimal(str(vol_raw))

        except (InvalidOperation, TypeError, ValueError) as exc:
            raise NormalizerError(f"Invalid numeric value in Bybit payload: {exc}") from exc

        # Funding rate extraction for Futures / Linear
        if market_type is MarketType.FUTURES:
            raw_funding = payload.get("fundingRate")
            if raw_funding is not None and str(raw_funding).strip() != "":
                try:
                    metadata["funding_rate"] = str(Decimal(str(raw_funding)))
                except (InvalidOperation, TypeError, ValueError):
                    pass

        # Timestamp and deterministic Event ID
        server_time = payload.get("serverTime") or payload.get("time") or payload.get("ts")
        if server_time is not None:
            try:
                ts = datetime.fromtimestamp(float(server_time) / 1000.0, tz=UTC)
            except (ValueError, OSError, OverflowError):
                ts = raw_event.timestamp
            event_id = f"norm:bybit:{symbol}:{market_type.value.lower()}:{server_time}"
        else:
            ts = raw_event.timestamp
            event_id = f"norm:bybit:{symbol}:{market_type.value.lower()}:{int(ts.timestamp() * 1000)}"

        return NormalizedEvent(
            event_id=event_id,
            timestamp=ts,
            source=EventSource.BYBIT,
            market_type=market_type,
            asset=asset,
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            volume=volume,
            metadata={
                "raw_event_id": raw_event.event_id,
                **metadata,
            },
        )

    def normalize_batch(self, raw_events: Sequence[RawEvent]) -> list[NormalizedEvent]:
        """Normalize a sequence of raw events, filtering out invalid or unpriced items."""
        results: list[NormalizedEvent] = []
        for raw in raw_events:
            try:
                norm = self.normalize(raw)
                if norm.price > 0:
                    results.append(norm)
            except Exception as exc:
                logger.debug("Skipping invalid Bybit event %s: %s", getattr(raw, "event_id", "unknown"), exc)
        return results
