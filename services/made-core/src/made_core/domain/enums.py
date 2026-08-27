"""Explicit domain enumerations used by MADE contracts."""

from enum import StrEnum


class MarketType(StrEnum):
    SPOT = "SPOT"
    FUTURES = "FUTURES"
    DEX = "DEX"


class EventSource(StrEnum):
    BINANCE = "BINANCE"
    BYBIT = "BYBIT"
    OKX = "OKX"
    UNISWAP = "UNISWAP"
    OTHER = "OTHER"


class ResultStatus(StrEnum):
    NORMAL = "NORMAL"
    ANOMALY = "ANOMALY"


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReferencePriceMode(StrEnum):
    FIRST = "FIRST"
    SECOND = "SECOND"
    AVERAGE = "AVERAGE"
    LAST = "LAST"


class ValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
