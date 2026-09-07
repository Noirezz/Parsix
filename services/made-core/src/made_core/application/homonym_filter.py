"""Homonym detection and symbol blacklisting component for MADE Core."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Collection

logger = logging.getLogger(__name__)


class HomonymBlacklist:
    """In-memory thread-safe symbol and pair blacklist with auto-discovery on scale anomalies."""

    def __init__(
        self,
        initial_blacklist: Collection[str] | None = None,
        max_price_ratio: Decimal = Decimal("2.0"),
        auto_blacklist: bool = True,
    ) -> None:
        self._blacklisted: set[str] = set(s.upper() for s in (initial_blacklist or ()))
        self._max_price_ratio = max_price_ratio
        self._auto_blacklist = auto_blacklist

    def is_blacklisted(self, symbol_or_asset: str) -> bool:
        """Check in O(1) if a symbol or asset is on the blacklist."""
        target = str(symbol_or_asset).upper()
        return target in self._blacklisted

    def add(self, symbol_or_asset: str, reason: str = "manual") -> None:
        """Add a symbol or asset to the blacklist."""
        target = str(symbol_or_asset).upper()
        if target not in self._blacklisted:
            self._blacklisted.add(target)
            logger.warning(
                "Symbol/Asset %s added to Homonym Blacklist (reason: %s). Total blacklisted: %d",
                target,
                reason,
                len(self._blacklisted),
            )

    def check_and_record_homonym(
        self,
        symbol: str,
        asset: str,
        price1: Decimal,
        price2: Decimal,
    ) -> bool:
        """Evaluate if two prices indicate a homonym token collision.

        Returns True if prices indicate a homonym collision.
        If auto_blacklist is enabled, registers the symbol in the blacklist.
        """
        if self.is_blacklisted(symbol) or self.is_blacklisted(asset):
            return True

        if price1 <= Decimal("0") or price2 <= Decimal("0"):
            return False

        min_p = min(price1, price2)
        max_p = max(price1, price2)
        ratio = max_p / min_p

        if ratio >= self._max_price_ratio:
            if self._auto_blacklist:
                self.add(
                    symbol,
                    reason=f"extreme_price_ratio_{ratio:.1f}x ({price1} vs {price2})",
                )
                self.add(
                    asset,
                    reason=f"extreme_price_ratio_{ratio:.1f}x ({price1} vs {price2})",
                )
            return True

        return False

    def get_blacklisted(self) -> set[str]:
        return set(self._blacklisted)
