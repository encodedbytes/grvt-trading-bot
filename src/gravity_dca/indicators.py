from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .grvt_models import Candle


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def _validate_lookback(lookback: int) -> None:
    if lookback <= 0:
        raise ValueError("lookback must be positive")


def ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    _validate_period(period)
    results: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return results
    period_decimal = Decimal(period)
    multiplier = Decimal("2") / Decimal(period + 1)
    seed = sum(values[:period], Decimal("0")) / period_decimal
    results[period - 1] = seed
    previous = seed
    for index in range(period, len(values)):
        previous = ((values[index] - previous) * multiplier) + previous
        results[index] = previous
    return results


def true_range(candles: Sequence[Candle]) -> list[Decimal]:
    if not candles:
        return []
    ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in candles:
        intrabar_range = candle.high - candle.low
        if previous_close is None:
            ranges.append(intrabar_range)
        else:
            ranges.append(
                max(
                    intrabar_range,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            )
        previous_close = candle.close
    return ranges


def atr(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    _validate_period(period)
    results: list[Decimal | None] = [None] * len(candles)
    if len(candles) < period:
        return results
    ranges = true_range(candles)
    period_decimal = Decimal(period)
    previous = sum(ranges[:period], Decimal("0")) / period_decimal
    results[period - 1] = previous
    for index in range(period, len(ranges)):
        previous = ((previous * Decimal(period - 1)) + ranges[index]) / period_decimal
        results[index] = previous
    return results


def highest_close(
    candles: Sequence[Candle],
    lookback: int,
    *,
    offset: int = 0,
) -> Decimal | None:
    _validate_lookback(lookback)
    if offset < 0:
        raise ValueError("offset must be non-negative")
    end = len(candles) - offset
    if end < lookback:
        return None
    window = candles[end - lookback : end]
    return max(candle.close for candle in window)


def adx(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    _validate_period(period)
    results: list[Decimal | None] = [None] * len(candles)
    if len(candles) < (period * 2) - 1:
        return results

    ranges = true_range(candles)
    plus_dm: list[Decimal] = [Decimal("0")]
    minus_dm: list[Decimal] = [Decimal("0")]
    for index in range(1, len(candles)):
        up_move = candles[index].high - candles[index - 1].high
        down_move = candles[index - 1].low - candles[index].low
        plus_dm.append(
            up_move if up_move > down_move and up_move > 0 else Decimal("0")
        )
        minus_dm.append(
            down_move if down_move > up_move and down_move > 0 else Decimal("0")
        )

    period_decimal = Decimal(period)
    smoothed_tr = sum(ranges[:period], Decimal("0"))
    smoothed_plus_dm = sum(plus_dm[:period], Decimal("0"))
    smoothed_minus_dm = sum(minus_dm[:period], Decimal("0"))

    dx_values: list[tuple[int, Decimal]] = []
    for index in range(period - 1, len(candles)):
        if index > period - 1:
            smoothed_tr = smoothed_tr - (smoothed_tr / period_decimal) + ranges[index]
            smoothed_plus_dm = (
                smoothed_plus_dm - (smoothed_plus_dm / period_decimal) + plus_dm[index]
            )
            smoothed_minus_dm = (
                smoothed_minus_dm - (smoothed_minus_dm / period_decimal) + minus_dm[index]
            )
        if smoothed_tr <= 0:
            dx = Decimal("0")
        else:
            plus_di = (smoothed_plus_dm / smoothed_tr) * Decimal("100")
            minus_di = (smoothed_minus_dm / smoothed_tr) * Decimal("100")
            denominator = plus_di + minus_di
            if denominator <= 0:
                dx = Decimal("0")
            else:
                dx = (abs(plus_di - minus_di) / denominator) * Decimal("100")
        dx_values.append((index, dx))

    seed_window = [value for _, value in dx_values[:period]]
    previous = sum(seed_window, Decimal("0")) / period_decimal
    results[(period * 2) - 2] = previous
    for index, dx in dx_values[period:]:
        previous = ((previous * Decimal(period - 1)) + dx) / period_decimal
        results[index] = previous
    return results
