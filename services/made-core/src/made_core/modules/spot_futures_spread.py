"""Deterministic spot-to-futures price-spread detection module."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from made_core.domain.enums import MarketType, ReferencePriceMode, ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent, MarketSnapshot


@dataclass(frozen=True, slots=True)
class SpotFuturesSpreadConfig:
    """Domain-level configuration for the spot-to-futures spread rule."""

    threshold: Decimal
    reference_price_mode: ReferencePriceMode = ReferencePriceMode.AVERAGE
    homonym_blacklist: Any = None
    max_price_ratio: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        if self.threshold <= Decimal("0"):
            raise ValueError("threshold must be greater than zero")
        if self.max_price_ratio <= Decimal("1.0"):
            raise ValueError("max_price_ratio must be greater than 1.0")


class SpotFuturesSpreadModule(DetectionModule):
    """Compares the first matching SPOT and FUTURES observations for one pair.

    Observation selection (MVP):
    - Trigger event market type must be SPOT or FUTURES.
    - Snapshots must match the normalised asset/symbol.
    - The first SPOT snapshot and the first FUTURES snapshot in
      ``MarketContext`` order form the compared pair.
    - ``ReferencePriceMode.FIRST`` uses the spot price; ``SECOND`` and
      ``LAST`` use the futures price; ``AVERAGE`` uses their mean.
    """

    MODULE_ID = "spot-futures-spread"

    def __init__(self, config: SpotFuturesSpreadConfig) -> None:
        self._config = config

    def get_module_id(self) -> str:
        return self.MODULE_ID

    def get_config(self) -> SpotFuturesSpreadConfig:
        return self._config

    def update_config(
        self,
        threshold: Decimal | None = None,
        reference_price_mode: ReferencePriceMode | None = None,
        max_price_ratio: Decimal | None = None,
    ) -> None:
        self._config = SpotFuturesSpreadConfig(
            threshold=threshold if threshold is not None else self._config.threshold,
            reference_price_mode=reference_price_mode if reference_price_mode is not None else self._config.reference_price_mode,
            homonym_blacklist=self._config.homonym_blacklist,
            max_price_ratio=max_price_ratio if max_price_ratio is not None else self._config.max_price_ratio,
        )

    def detect(self, event: EnrichedEvent) -> DetectionResult:
        if event is None:
            raise TypeError("event must not be None")

        selected = self._select_observations(event)
        if selected is None:
            return self._insufficient_context_result(event)

        spot, futures = selected
        if spot.price is None or futures.price is None:
            return self._insufficient_context_result(event, (spot, futures), "missing_price")
        reference_price = self._reference_price(spot.price, futures.price)
        if reference_price is None or reference_price <= Decimal("0"):
            return self._insufficient_context_result(event, (spot, futures), "invalid_reference_price")

        # 1. Fast O(1) Blacklist check
        blacklist = self._config.homonym_blacklist
        symbol = event.normalized_data.symbol
        if blacklist is not None and (blacklist.is_blacklisted(symbol) or blacklist.is_blacklisted(event.asset)):
            return self._insufficient_context_result(event, (spot, futures), "blacklisted_homonym_pair")

        # 2. Check for homonym scale discrepancy (e.g. $0.25 vs $73.0 is 292x ratio)
        min_p = min(spot.price, futures.price)
        max_p = max(spot.price, futures.price)
        if min_p > Decimal("0") and (max_p / min_p) >= self._config.max_price_ratio:
            if blacklist is not None:
                blacklist.add(symbol, reason=f"auto_detected_ratio_{max_p/min_p:.1f}x")
                blacklist.add(event.asset, reason=f"auto_detected_ratio_{max_p/min_p:.1f}x")
            return self._insufficient_context_result(event, (spot, futures), "homonym_symbol_price_mismatch")

        spread = abs(spot.price - futures.price) / reference_price * Decimal("100")
        status = ResultStatus.ANOMALY if spread >= self._config.threshold else ResultStatus.NORMAL
        return DetectionResult(
            result_id=f"{event.event_id}:{self.MODULE_ID}",
            event_id=event.event_id,
            module_id=self.MODULE_ID,
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=spread,
            threshold=self._config.threshold,
            anomaly_ratio=spread / self._config.threshold,
            status=status,
            persistence=0,
            metadata=self._metadata(spot, futures, reference_price, None),
        )

    def _select_observations(self, event: EnrichedEvent) -> tuple[MarketSnapshot, MarketSnapshot] | None:
        if event.normalized_data.market_type not in (MarketType.SPOT, MarketType.FUTURES):
            return None

        spot_observations: list[MarketSnapshot] = []
        futures_observations: list[MarketSnapshot] = []
        for snapshot in event.market_context.snapshots:
            if (
                snapshot.asset != event.normalized_data.asset
                or snapshot.symbol != event.normalized_data.symbol
            ):
                continue
            if snapshot.market_type is MarketType.SPOT:
                spot_observations.append(snapshot)
            elif snapshot.market_type is MarketType.FUTURES:
                futures_observations.append(snapshot)

        if not spot_observations or not futures_observations:
            return None
        return spot_observations[0], futures_observations[0]

    @staticmethod
    def _usable_price(price: object) -> bool:
        return isinstance(price, Decimal) and price > Decimal("0")

    def _reference_price(self, spot: Decimal, futures: Decimal) -> Decimal | None:
        if not self._usable_price(spot) or not self._usable_price(futures):
            return None
        match self._config.reference_price_mode:
            case ReferencePriceMode.FIRST:
                return spot
            case ReferencePriceMode.SECOND | ReferencePriceMode.LAST:
                return futures
            case ReferencePriceMode.AVERAGE:
                return (spot + futures) / Decimal("2")

    def _insufficient_context_result(
        self,
        event: EnrichedEvent,
        selected: tuple[MarketSnapshot, ...] = (),
        reason: str = "insufficient_spot_futures_context",
    ) -> DetectionResult:
        spot = selected[0] if len(selected) > 0 else None
        futures = selected[1] if len(selected) > 1 else None
        return DetectionResult(
            result_id=f"{event.event_id}:{self.MODULE_ID}",
            event_id=event.event_id,
            module_id=self.MODULE_ID,
            timestamp=event.timestamp,
            asset=event.asset,
            metric_value=Decimal("0"),
            threshold=self._config.threshold,
            anomaly_ratio=Decimal("0"),
            status=ResultStatus.NORMAL,
            persistence=0,
            metadata=self._metadata(spot, futures, None, reason),
        )

    def _metadata(
        self,
        spot: MarketSnapshot | None,
        futures: MarketSnapshot | None,
        reference_price: Decimal | None,
        insufficient_reason: str | None,
    ) -> dict[str, object]:
        snapshots = tuple(snapshot for snapshot in (spot, futures) if snapshot is not None)
        metadata: dict[str, object] = {
            "referencePriceMode": self._config.reference_price_mode.value,
            "sources": [snapshot.source.value for snapshot in snapshots],
            "symbols": [snapshot.symbol for snapshot in snapshots],
            "marketTypes": [snapshot.market_type.value for snapshot in snapshots],
        }
        if spot is not None:
            metadata["spotSource"] = spot.source.value
            metadata["spotSymbol"] = spot.symbol
            metadata["spotPrice"] = str(spot.price) if spot.price is not None else None
        if futures is not None:
            metadata["futuresSource"] = futures.source.value
            metadata["futuresSymbol"] = futures.symbol
            metadata["futuresPrice"] = str(futures.price) if futures.price is not None else None
        if reference_price is not None:
            metadata["referencePrice"] = reference_price
        if insufficient_reason is not None:
            metadata["insufficientContextReason"] = insufficient_reason
        return metadata
