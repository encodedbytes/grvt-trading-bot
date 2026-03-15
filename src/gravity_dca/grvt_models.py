from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


PRICE_SCALE = Decimal("1000000000")
MARGIN_TYPE_ALIASES = {
    "cross": "CROSS",
    "cross_margin": "CROSS",
    "simple_cross_margin": "CROSS",
    "portfolio_cross_margin": "CROSS",
    "isolated": "ISOLATED",
    "isolated_margin": "ISOLATED",
}


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    last: Decimal


@dataclass(frozen=True)
class InstrumentMeta:
    symbol: str
    tick_size: Decimal
    min_size: Decimal
    min_notional: Decimal
    base_decimals: int


@dataclass(frozen=True)
class FillReport:
    order_id: str
    client_order_id: str
    status: str
    traded_size: Decimal
    avg_fill_price: Decimal
    raw: dict


@dataclass(frozen=True)
class PositionConfig:
    leverage: Decimal | None = None
    margin_type: str | None = None


@dataclass(frozen=True)
class InitialPositionConfig:
    symbol: str
    leverage: Decimal | None = None
    min_leverage: Decimal | None = None
    max_leverage: Decimal | None = None
    margin_type: str | None = None
    raw: dict | None = None


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    size: Decimal
    average_entry_price: Decimal
    leverage: Decimal | None = None
    margin_type: str | None = None
    raw: dict | None = None


@dataclass(frozen=True)
class AccountFill:
    event_time: int
    symbol: str
    side: str
    size: Decimal
    price: Decimal
    order_id: str | None = None
    client_order_id: str | None = None
    raw: dict | None = None


class TransientExchangeError(RuntimeError):
    pass


def parse_grvt_decimal(value: str | int | float | Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    text = str(value)
    parsed = Decimal(text)
    if "." in text:
        return parsed
    if abs(parsed) >= PRICE_SCALE:
        return parsed / PRICE_SCALE
    return parsed


def normalize_margin_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return MARGIN_TYPE_ALIASES.get(normalized.lower(), normalized.upper())
