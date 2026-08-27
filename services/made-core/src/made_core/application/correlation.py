"""Application-layer correlation engine for detection results."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from made_core.domain.interfaces import CorrelationEngine
from made_core.domain.models import CorrelatedGroup, DetectionResult


class DefaultCorrelationEngine(CorrelationEngine):
    """Groups detection results by asset and time window."""

    def correlate(
        self,
        results: Sequence[DetectionResult],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> CorrelatedGroup:
        if results is None:
            raise TypeError("results must not be None")
        if not results:
            raise ValueError("results must contain at least one DetectionResult")

        for r in results:
            if not isinstance(r, DetectionResult):
                raise TypeError("all elements in results must be DetectionResult instances")

        asset = results[0].asset
        if any(r.asset != asset for r in results):
            raise ValueError("all detection results must belong to the same asset")

        start = window_start if window_start is not None else min(r.timestamp for r in results)
        end = window_end if window_end is not None else max(r.timestamp for r in results)

        if end < start:
            raise ValueError("window_end must not precede window_start")

        correlation_id = f"corr:{asset}:{results[0].event_id}"

        return CorrelatedGroup(
            correlation_id=correlation_id,
            asset=asset,
            window_start=start,
            window_end=end,
            results=tuple(results),
        )
