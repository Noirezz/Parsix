"""Deterministic futures-to-futures price-spread detection module."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from made_core.domain.enums import MarketType, ReferencePriceMode, ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent, MarketSnapshot


@dataclass(frozen=True, slots=True)
class FuturesFuturesSpreadConfig:
    """Domain-level configuration for the futures-to-futures spread rule."""

    threshold: Decimal
    reference_price_mode: ReferencePriceMode = ReferencePriceMode.AVERAGE
    homonym_blacklist: Any = None
    max_price_ratio: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        if self.threshold <= Decimal("0"):
            raise ValueError("threshold must be greater than zero")
        if self.max_price_ratio <= Decimal("1.0"):
            raise ValueError("max_price_ratio must be greater than 1.0")


class FuturesFuturesSpreadModule(DetectionModule):
    """Compares the first two distinct-source futures observations for one pair."""

    MODULE_ID = "futures-futures-spread"

    def __init__(self, config: FuturesFuturesSpreadConfig) -> None:
        self._config = config

    def get_module_id(self) -> str:
        return self.MODULE_ID

    def get_config(self) -> FuturesFuturesSpreadConfig:
        return self._config

    def update_config(
        self,
        threshold: Decimal | None = None,
        reference_price_mode: ReferencePriceMode | None = None,
        max_price_ratio: Decimal | None = None,
    ) -> None:
        self._config = FuturesFuturesSpreadConfig(
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

        first, second = selected
        if first.price is None or second.price is None:
            return self._insufficient_context_result(event, (first, second), "missing_price")
        reference_price = self._reference_price(first.price, second.price)
        if reference_price is None or reference_price <= Decimal("0"):
            return self._insufficient_context_result(event, (first, second), "invalid_reference_price")

        # 1. Fast O(1) Blacklist check
        blacklist = self._config.homonym_blacklist
        symbol = event.normalized_data.symbol
        if blacklist is not None and (blacklist.is_blacklisted(symbol) or blacklist.is_blacklisted(event.asset)):
            return self._insufficient_context_result(event, (first, second), "blacklisted_homonym_pair")

        # 2. Check for homonym scale discrepancy (e.g. $0.25 vs $73.0 is 292x ratio)
        min_p = min(first.price, second.price)
        max_p = max(first.price, second.price)
        if min_p > Decimal("0") and (max_p / min_p) >= self._config.max_price_ratio:
            if blacklist is not None:
                blacklist.add(symbol, reason=f"auto_detected_ratio_{max_p/min_p:.1f}x")
                blacklist.add(event.asset, reason=f"auto_detected_ratio_{max_p/min_p:.1f}x")
            return self._insufficient_context_result(event, (first, second), "homonym_symbol_price_mismatch")

        spread = abs(first.price - second.price) / reference_price * Decimal("100")
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
            metadata=self._metadata((first, second), reference_price, None),
        )

    def _select_observations(self, event: EnrichedEvent) -> tuple[MarketSnapshot, MarketSnapshot] | None:
        if event.normalized_data.market_type is not MarketType.FUTURES:
            return None

        observations: list[MarketSnapshot] = []
        for snapshot in event.market_context.snapshots:
            if (
                snapshot.market_type is MarketType.FUTURES
                and snapshot.asset == event.normalized_data.asset
                and snapshot.symbol == event.normalized_data.symbol
            ):
                observations.append(snapshot)

        for index, first in enumerate(observations):
            for second in observations[index + 1 :]:
                if first.source != second.source:
                    return first, second
        return None

    @staticmethod
    def _usable_price(price: object) -> bool:
        return isinstance(price, Decimal) and price > Decimal("0")

    def _reference_price(self, first: Decimal, second: Decimal) -> Decimal | None:
        if not self._usable_price(first) or not self._usable_price(second):
            return None
        match self._config.reference_price_mode:
            case ReferencePriceMode.FIRST:
                return first
            case ReferencePriceMode.SECOND | ReferencePriceMode.LAST:
                return second
            case ReferencePriceMode.AVERAGE:
                return (first + second) / Decimal("2")

    def _insufficient_context_result(
        self,
        event: EnrichedEvent,
        selected: tuple[MarketSnapshot, ...] = (),
        reason: str = "insufficient_futures_context",
    ) -> DetectionResult:
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
            metadata=self._metadata(selected, None, reason),
        )

    def _metadata(
        self,
        snapshots: tuple[MarketSnapshot, ...],
        reference_price: Decimal | None,
        insufficient_reason: str | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "referencePriceMode": self._config.reference_price_mode.value,
            "sources": [snapshot.source.value for snapshot in snapshots],
            "symbols": [snapshot.symbol for snapshot in snapshots],
        }
        if len(snapshots) >= 2:
            metadata["firstSource"] = snapshots[0].source.value
            metadata["firstMarketType"] = snapshots[0].market_type.value
            metadata["firstSymbol"] = snapshots[0].symbol
            metadata["firstPrice"] = str(snapshots[0].price) if snapshots[0].price is not None else None
            metadata["secondSource"] = snapshots[1].source.value
            metadata["secondMarketType"] = snapshots[1].market_type.value
            metadata["secondSymbol"] = snapshots[1].symbol
            metadata["secondPrice"] = str(snapshots[1].price) if snapshots[1].price is not None else None
        if reference_price is not None:
            metadata["referencePrice"] = reference_price
        if insufficient_reason is not None:
            metadata["insufficientContextReason"] = insufficient_reason
        return metadata
