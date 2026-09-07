"""Deterministic synthetic market event generator."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from made_core.domain.enums import EventSource, MarketType
from made_core.domain.models import NormalizedEvent


class SyntheticMarketGenerator:
    """Generates deterministic synthetic cryptocurrency market events."""

    def __init__(
        self,
        seed: int = 42,
        base_prices: dict[str, float] | None = None,
        volatility: float = 0.002,
        spread_pct: float = 0.0005,
        default_volume: float = 1.5,
        start_time: datetime | None = None,
        tick_interval_ms: int = 10,
    ) -> None:
        self._seed = seed
        self._rng = random.Random(seed)
        self._base_prices = base_prices or {"BTC": 50000.0, "ETH": 3000.0}
        self._current_prices = dict(self._base_prices)
        self._volatility = volatility
        self._spread_pct = spread_pct
        self._default_volume = default_volume
        self._current_time = start_time or datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._tick_interval = timedelta(milliseconds=tick_interval_ms)
        self._event_counter = 0

    def reset(self, seed: int | None = None) -> None:
        """Reset the generator to initial state."""
        if seed is not None:
            self._seed = seed
        self._rng = random.Random(self._seed)
        self._current_prices = dict(self._base_prices)
        self._current_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._event_counter = 0

    def generate_event(
        self,
        asset: str = "BTC",
        source: EventSource = EventSource.BINANCE,
        market_type: MarketType = MarketType.SPOT,
        price_override: Decimal | None = None,
        bid_override: Decimal | None = None,
        ask_override: Decimal | None = None,
        funding_rate: Decimal | None = None,
        timestamp: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizedEvent:
        """Generate a single deterministic NormalizedEvent."""
        self._event_counter += 1
        event_time = timestamp or self._current_time
        self._current_time += self._tick_interval

        if price_override is not None:
            price = price_override
        else:
            base = self._current_prices.get(asset, 50000.0)
            # Random walk
            delta = base * self._rng.gauss(0, self._volatility)
            new_price = max(1.0, base + delta)
            self._current_prices[asset] = new_price
            price = Decimal(f"{new_price:.4f}")

        half_spread = price * Decimal(str(self._spread_pct)) / Decimal("2")
        bid = bid_override if bid_override is not None else price - half_spread
        ask = ask_override if ask_override is not None else price + half_spread
        if bid <= 0:
            bid = price * Decimal("0.999")
        if ask < bid:
            ask = bid + Decimal("0.01")

        vol_variation = Decimal(str(max(0.1, self._default_volume + self._rng.gauss(0, 0.2))))
        volume = Decimal(f"{vol_variation:.4f}")

        symbol = f"{asset}USDT"
        event_id = f"synth:{source.value.lower()}:{symbol}:{market_type.value.lower()}:{self._event_counter:08d}"

        meta = dict(metadata or {})
        if funding_rate is not None:
            meta["funding_rate"] = str(funding_rate)

        return NormalizedEvent(
            event_id=event_id,
            timestamp=event_time,
            source=source,
            market_type=market_type,
            asset=asset,
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            volume=volume,
            metadata=meta,
        )

    def generate_stream(
        self,
        count: int,
        assets: list[str] | None = None,
    ) -> list[NormalizedEvent]:
        """Generate a sequential stream of market events across all standard sources."""
        assets = assets or ["BTC", "ETH"]
        sources = [
            (EventSource.BINANCE, MarketType.SPOT),
            (EventSource.BINANCE, MarketType.FUTURES),
            (EventSource.BYBIT, MarketType.SPOT),
            (EventSource.BYBIT, MarketType.FUTURES),
        ]

        events: list[NormalizedEvent] = []
        for _ in range(count):
            asset = self._rng.choice(assets)
            source, mtype = self._rng.choice(sources)
            fr = Decimal(f"{self._rng.uniform(-0.0002, 0.0002):.6f}") if mtype is MarketType.FUTURES else None
            evt = self.generate_event(asset=asset, source=source, market_type=mtype, funding_rate=fr)
            events.append(evt)

        return events
