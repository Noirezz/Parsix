"""Normalizer converting raw DEX on-chain events into canonical NormalizedEvents."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent, RawEvent
from made_core.ingestion.normalizer import NormalizerError, _derive_asset_from_symbol

logger = logging.getLogger(__name__)


class DexNormalizer:
    """Normalizes raw DEX liquidity pool events into canonical NormalizedEvent domain models."""

    def normalize(self, raw_event: RawEvent) -> NormalizedEvent:
        """Transform a RawEvent from DEX collectors into a canonical NormalizedEvent."""
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

        # Extract numeric fields with strict Decimal precision
        try:
            price_raw = payload.get("lastPrice") or payload.get("price") or payload.get("p")
            if price_raw is None:
                raise NormalizerError("Payload missing required price attribute")
            price = Decimal(str(price_raw))
            if price <= Decimal("0"):
                raise NormalizerError(f"Price must be strictly positive, got {price}")

            bid_raw = payload.get("bidPrice") or payload.get("bid")
            bid = Decimal(str(bid_raw)) if bid_raw is not None else price * Decimal("0.9995")

            ask_raw = payload.get("askPrice") or payload.get("ask")
            ask = Decimal(str(ask_raw)) if ask_raw is not None else price * Decimal("1.0005")

            if bid > ask:
                # DEX pools do not have traditional orderbooks; enforce valid bid <= ask
                bid, ask = min(bid, ask), max(bid, ask)

            volume_raw = payload.get("volume") or payload.get("v") or "0"
            volume = Decimal(str(volume_raw))
            if volume < Decimal("0"):
                volume = Decimal("0")

        except (InvalidOperation, TypeError, ValueError) as err:
            raise NormalizerError(f"Failed parsing numeric pricing values: {err}") from err

        ts = raw_event.timestamp if isinstance(raw_event.timestamp, datetime) else datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts_ms = int(ts.timestamp() * 1000)

        source = raw_event.source if isinstance(raw_event.source, EventSource) else EventSource.DEXSCREENER
        src_name = source.value.lower()
        norm_event_id = f"norm:dex:{src_name}:{symbol}:{ts_ms}"

        norm_meta = {
            "source": source.value,
            "market_type": MarketType.DEX.value,
            "asset": asset,
            "symbol": symbol,
            "dex": metadata.get("dex") or payload.get("dexId") or "DEX",
            "chain": metadata.get("chain") or payload.get("chainId") or "on-chain",
            "pair_url": metadata.get("pair_url") or payload.get("url") or f"https://dexscreener.com/search?q={symbol}",
            "liquidity_usd": str(metadata.get("liquidity_usd") or payload.get("liquidityUsd") or "0"),
            "pair_address": metadata.get("pair_address") or payload.get("pairAddress"),
        }

        return NormalizedEvent(
            event_id=norm_event_id,
            timestamp=ts,
            source=source,
            market_type=MarketType.DEX,
            asset=asset,
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            volume=volume,
            metadata=norm_meta,
        )
