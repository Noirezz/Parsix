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

    def __post_init__(self) -> None:
        if self.threshold <= Decimal("0"):
            raise ValueError("threshold must be greater than zero")


class FuturesFuturesSpreadModule(DetectionModule):
    """Compares the first two distinct-source futures observations for one pair."""

    MODULE_ID = "futures-futures-spread"

    def __init__(self, config: FuturesFuturesSpreadConfig) -> None:
        self._config = config

    def get_module_id(self) -> str:
        return self.MODULE_ID

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
        if reference_price is not None:
            metadata["referencePrice"] = reference_price
        if insufficient_reason is not None:
            metadata["insufficientContextReason"] = insufficient_reason
        return metadata
