from __future__ import annotations

from decimal import Decimal

import pytest

from gravity_dca.grvt_models import Candle
from gravity_dca.indicators import adx, atr, ema, highest_close, true_range


def candle(
    open_time: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> Candle:
    return Candle(
        symbol="ETH_USDT_Perp",
        open_time=open_time,
        close_time=open_time + 299,
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=Decimal("1"),
        quote_volume=Decimal("1000"),
        trades=1,
    )


def test_ema_uses_sma_seed_then_exponential_smoothing() -> None:
    values = [Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13"), Decimal("14")]

    result = ema(values, period=3)

    assert result == [
        None,
        None,
        Decimal("11"),
        Decimal("12.0"),
        Decimal("13.00"),
    ]


def test_true_range_uses_previous_close_gap_when_larger_than_intrabar_range() -> None:
    candles = [
        candle(0, "10", "11", "9", "10"),
        candle(300, "13", "14", "13", "13.5"),
    ]

    result = true_range(candles)

    assert result == [Decimal("2"), Decimal("4")]


def test_atr_uses_wilder_smoothing() -> None:
    candles = [
        candle(0, "10", "11", "9", "10"),
        candle(300, "11", "12", "10", "11"),
        candle(600, "12", "13", "11", "12"),
        candle(900, "13", "17", "13", "16"),
        candle(1200, "16", "18", "15", "17"),
    ]

    result = atr(candles, period=3)

    assert result == [
        None,
        None,
        Decimal("2"),
        Decimal("3"),
        Decimal("3"),
    ]


def test_highest_close_can_exclude_latest_candle() -> None:
    candles = [
        candle(0, "10", "11", "9", "10"),
        candle(300, "11", "12", "10", "11"),
        candle(600, "12", "13", "11", "12"),
        candle(900, "13", "14", "12", "13"),
    ]

    assert highest_close(candles, lookback=3) == Decimal("13")
    assert highest_close(candles, lookback=3, offset=1) == Decimal("12")


def test_adx_reaches_one_hundred_for_a_clean_one_way_trend() -> None:
    candles = [
        candle(0, "9", "10", "8", "9"),
        candle(300, "10", "11", "9", "10"),
        candle(600, "11", "12", "10", "11"),
        candle(900, "12", "13", "11", "12"),
        candle(1200, "13", "14", "12", "13"),
    ]

    result = adx(candles, period=3)

    assert result == [None, None, None, None, Decimal("100")]


@pytest.mark.parametrize(
    ("func", "kwargs", "message"),
    [
        (ema, {"values": [Decimal("1")], "period": 0}, "period must be positive"),
        (atr, {"candles": [], "period": 0}, "period must be positive"),
        (adx, {"candles": [], "period": 0}, "period must be positive"),
        (
            highest_close,
            {"candles": [], "lookback": 0},
            "lookback must be positive",
        ),
    ],
)
def test_indicator_validation(func, kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        func(**kwargs)


def test_highest_close_rejects_negative_offset() -> None:
    with pytest.raises(ValueError, match="offset must be non-negative"):
        highest_close([candle(0, "10", "11", "9", "10")], lookback=1, offset=-1)
