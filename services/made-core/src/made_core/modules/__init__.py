"""Independent MADE detection modules."""

from made_core.modules.dex_futures_spread import DexFuturesSpreadConfig, DexFuturesSpreadModule
from made_core.modules.funding_spread import FundingSpreadConfig, FundingSpreadModule
from made_core.modules.futures_futures_spread import FuturesFuturesSpreadConfig, FuturesFuturesSpreadModule
from made_core.modules.spot_futures_spread import SpotFuturesSpreadConfig, SpotFuturesSpreadModule

__all__ = [
    "DexFuturesSpreadConfig",
    "DexFuturesSpreadModule",
    "FundingSpreadConfig",
    "FundingSpreadModule",
    "FuturesFuturesSpreadConfig",
    "FuturesFuturesSpreadModule",
    "SpotFuturesSpreadConfig",
    "SpotFuturesSpreadModule",
]
