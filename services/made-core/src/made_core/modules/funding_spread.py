"""Deterministic futures-to-futures funding-rate spread detection module."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from made_core.domain.enums import MarketType, ResultStatus
from made_core.domain.interfaces import DetectionModule
from made_core.domain.models import DetectionResult, EnrichedEvent, MarketSnapshot


@dataclass(frozen=True, slots=True)
class FundingSpreadConfig:
    """Domain-level configuration for the funding-rate spread rule.

    Unlike price-spread modules, ``ReferencePriceMode`` does not apply here
    because the funding-spread formula is an absolute difference with no
    reference denominator.
    """

    threshold: Decimal

    def __post_init__(self) -> None:
        if self.threshold <= Decimal("0"):
            raise ValueError("threshold must be greater than zero")


class FundingSpreadModule(DetectionModule):
    """Compares funding rates from the first two distinct-source futures observations.

    Observation selection (MVP):
    - Trigger event market type must be FUTURES.
    - Snapshots must match the normalised asset/symbol.
    - Only FUTURES snapshots with a non-None ``funding_rate`` are considered.
    - The first two such snapshots with distinct ``source`` values in
      ``MarketContext`` order form the compared pair.
    - The detection metric is the absolute difference of the two funding
      rates: ``|F1 - F2|``.
    - No ``ReferencePriceMode`` is used; the formula has no reference
      denominator.
    """

    MODULE_ID = "funding-spread"

    def __init__(self, config: FundingSpreadConfig) -> None:
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
        spread = abs(first.funding_rate - second.funding_rate)
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
            metadata=self._metadata((first, second), None),
        )

    def _select_observations(
        self, event: EnrichedEvent,
    ) -> tuple[MarketSnapshot, MarketSnapshot] | None:
        if event.normalized_data.market_type is not MarketType.FUTURES:
            return None

        observations: list[MarketSnapshot] = []
        for snapshot in event.market_context.snapshots:
            if (
                snapshot.market_type is MarketType.FUTURES
                and snapshot.asset == event.normalized_data.asset
                and snapshot.symbol == event.normalized_data.symbol
                and snapshot.funding_rate is not None
            ):
                observations.append(snapshot)

        for index, first in enumerate(observations):
            for second in observations[index + 1 :]:
                if first.source != second.source:
                    return first, second
        return None

    def _insufficient_context_result(
        self,
        event: EnrichedEvent,
        reason: str = "insufficient_funding_context",
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
            metadata=self._metadata((), reason),
        )

    def _metadata(
        self,
        snapshots: tuple[MarketSnapshot, ...],
        insufficient_reason: str | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "sources": [snapshot.source.value for snapshot in snapshots],
            "symbols": [snapshot.symbol for snapshot in snapshots],
        }
        if len(snapshots) >= 2:
            metadata["fundingRates"] = [snapshot.funding_rate for snapshot in snapshots]
        if insufficient_reason is not None:
            metadata["insufficientContextReason"] = insufficient_reason
        return metadata
