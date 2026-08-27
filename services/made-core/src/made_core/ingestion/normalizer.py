"""Normalizer converting raw exchange events into canonical NormalizedEvents."""

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


class BinanceNormalizer:
    """Normalizes raw Binance market events into canonical NormalizedEvent domain models."""

    def normalize(self, raw_event: RawEvent) -> NormalizedEvent:
        """Transform a RawEvent from Binance into a canonical NormalizedEvent."""
        if raw_event is None:
            raise NormalizerError("raw_event must not be None")
        if not isinstance(raw_event, RawEvent):
            raise NormalizerError(f"Expected RawEvent, got {type(raw_event)}")

        payload = raw_event.payload
        if not isinstance(payload, dict):
            raise NormalizerError(f"Expected dictionary payload, got {type(payload)}")

        metadata = raw_event.metadata or {}
        symbol = str(payload.get("symbol") or metadata.get("symbol") or "").strip().upper()
        if not symbol:
            raise NormalizerError("Payload does not contain a valid symbol identifier")

        asset = str(metadata.get("asset") or "").strip().upper()
        if not asset:
            # Fallback: derive base asset from symbol (e.g. BTCUSDT -> BTC)
            for quote in ("USDT", "BUSD", "USDC", "FDUSD", "BTC", "ETH"):
                if symbol.endswith(quote) and len(symbol) > len(quote):
                    asset = symbol[: -len(quote)]
                    break
            if not asset:
                asset = symbol

        market_type_raw = metadata.get("market_type") or metadata.get("marketType") or "SPOT"
        try:
            market_type = MarketType(str(market_type_raw).upper())
        except ValueError:
            market_type = MarketType.SPOT

        # Extract numeric fields with strict Decimal precision
        try:
            # Bid Price
            bid_raw = payload.get("bidPrice") or payload.get("bid") or payload.get("b")
            if bid_raw is None:
                raise NormalizerError("Missing required field 'bidPrice'")
            bid = Decimal(str(bid_raw))

            # Ask Price
            ask_raw = payload.get("askPrice") or payload.get("ask") or payload.get("a")
            if ask_raw is None:
                raise NormalizerError("Missing required field 'askPrice'")
            ask = Decimal(str(ask_raw))

            # Last Price / Mid Price
            price_raw = payload.get("lastPrice") or payload.get("price") or payload.get("c")
            if price_raw is not None:
                price = Decimal(str(price_raw))
            else:
                price = (bid + ask) / Decimal("2")

            # Volume
            vol_raw = payload.get("volume") or payload.get("vol") or payload.get("v") or "0"
            volume = Decimal(str(vol_raw))

        except (InvalidOperation, TypeError, ValueError) as exc:
            raise NormalizerError(f"Invalid numeric value in Binance payload: {exc}") from exc

        # Timestamp normalization
        close_time = payload.get("closeTime") or payload.get("time") or payload.get("E")
        if close_time is not None:
            try:
                # Millisecond epoch timestamp from Binance
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
