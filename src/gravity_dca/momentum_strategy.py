from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .config import MomentumSettings
from .grvt_models import Candle
from .indicators import adx, atr, ema, highest_close
from .momentum_state import ActiveMomentumState, MomentumBotState


@dataclass(frozen=True)
class MomentumIndicatorSnapshot:
    close_price: Decimal
    ema_fast: Decimal
    ema_slow: Decimal
    adx: Decimal
    atr: Decimal
    atr_percent: Decimal
    breakout_level: Decimal


@dataclass(frozen=True)
class MomentumEntryDecision:
    should_enter: bool
    reason: str
    breakout_level: Decimal | None = None
    initial_stop_price: Decimal | None = None
    trailing_stop_price: Decimal | None = None
    indicator_snapshot: MomentumIndicatorSnapshot | None = None


@dataclass(frozen=True)
class MomentumExitDecision:
    should_exit: bool
    reason: str | None = None
    stop_price: Decimal | None = None
    trailing_stop_price: Decimal | None = None
    highest_price_since_entry: Decimal | None = None
    indicator_snapshot: MomentumIndicatorSnapshot | None = None


def _required_candle_count(settings: MomentumSettings) -> int:
    indicator_periods = max(
        settings.ema_fast_period,
        settings.ema_slow_period,
        settings.breakout_lookback + 1,
        (settings.adx_period * 2) - 1,
        settings.atr_period,
    )
    return indicator_periods


def build_indicator_snapshot(
    candles: Sequence[Candle],
    settings: MomentumSettings,
) -> MomentumIndicatorSnapshot | None:
    if len(candles) < _required_candle_count(settings):
        return None
    closes = [candle.close for candle in candles]
    ema_fast_values = ema(closes, settings.ema_fast_period)
    ema_slow_values = ema(closes, settings.ema_slow_period)
    atr_values = atr(candles, settings.atr_period)
    adx_values = adx(candles, settings.adx_period)

    ema_fast_value = ema_fast_values[-1]
    ema_slow_value = ema_slow_values[-1]
    atr_value = atr_values[-1]
    adx_value = adx_values[-1]
    breakout_level = highest_close(candles, settings.breakout_lookback, offset=1)

    if None in {
        ema_fast_value,
        ema_slow_value,
        atr_value,
        adx_value,
        breakout_level,
    }:
        return None

    close_price = candles[-1].close
    if close_price <= 0:
        raise ValueError("latest close price must be positive")
    atr_percent = (atr_value / close_price) * Decimal("100")
    return MomentumIndicatorSnapshot(
        close_price=close_price,
        ema_fast=ema_fast_value,
        ema_slow=ema_slow_value,
        adx=adx_value,
        atr=atr_value,
        atr_percent=atr_percent,
        breakout_level=breakout_level,
    )


def should_start_new_position(state: MomentumBotState, settings: MomentumSettings) -> bool:
    if state.active_position is not None:
        return False
    if settings.max_cycles is not None and state.completed_cycles >= settings.max_cycles:
        return False
    return True


def evaluate_entry(
    candles: Sequence[Candle],
    settings: MomentumSettings,
    state: MomentumBotState,
) -> MomentumEntryDecision:
    if not should_start_new_position(state, settings):
        return MomentumEntryDecision(should_enter=False, reason="position-not-allowed")

    snapshot = build_indicator_snapshot(candles, settings)
    if snapshot is None:
        return MomentumEntryDecision(should_enter=False, reason="insufficient-history")
    if snapshot.ema_fast <= snapshot.ema_slow:
        return MomentumEntryDecision(
            should_enter=False,
            reason="trend-not-confirmed",
            indicator_snapshot=snapshot,
        )
    if snapshot.close_price <= snapshot.breakout_level:
        return MomentumEntryDecision(
            should_enter=False,
            reason="breakout-not-confirmed",
            indicator_snapshot=snapshot,
        )
    if snapshot.adx < settings.min_adx:
        return MomentumEntryDecision(
            should_enter=False,
            reason="adx-too-low",
            indicator_snapshot=snapshot,
        )
    if snapshot.atr_percent < settings.min_atr_percent:
        return MomentumEntryDecision(
            should_enter=False,
            reason="atr-too-low",
            indicator_snapshot=snapshot,
        )

    initial_stop = snapshot.close_price - (snapshot.atr * settings.stop_atr_multiple)
    trailing_stop = snapshot.close_price - (snapshot.atr * settings.trailing_atr_multiple)
    return MomentumEntryDecision(
        should_enter=True,
        reason="enter",
        breakout_level=snapshot.breakout_level,
        initial_stop_price=initial_stop,
        trailing_stop_price=trailing_stop,
        indicator_snapshot=snapshot,
    )


def fixed_take_profit_price(
    position: ActiveMomentumState,
    settings: MomentumSettings,
) -> Decimal | None:
    if settings.take_profit_percent is None:
        return None
    if position.side == "buy":
        return position.average_entry_price * (
            Decimal("1") + (settings.take_profit_percent / Decimal("100"))
        )
    return position.average_entry_price * (
        Decimal("1") - (settings.take_profit_percent / Decimal("100"))
    )


def next_trailing_stop_price(
    position: ActiveMomentumState,
    atr_value: Decimal,
    settings: MomentumSettings,
) -> Decimal:
    highest_price = position.highest_price_since_entry or position.average_entry_price
    candidate = highest_price - (atr_value * settings.trailing_atr_multiple)
    if position.trailing_stop_price is None:
        return candidate
    return max(position.trailing_stop_price, candidate)


def evaluate_exit(
    candles: Sequence[Candle],
    settings: MomentumSettings,
    state: MomentumBotState,
) -> MomentumExitDecision:
    position = state.active_position
    if position is None:
        return MomentumExitDecision(should_exit=False)

    snapshot = build_indicator_snapshot(candles, settings)
    if snapshot is None:
        return MomentumExitDecision(should_exit=False, reason="insufficient-history")

    highest_price = position.highest_price_since_entry or position.average_entry_price
    highest_price = max(highest_price, snapshot.close_price)
    trailing_stop = next_trailing_stop_price(
        ActiveMomentumState(
            **{
                **position.__dict__,
                "highest_price_since_entry": highest_price,
            }
        ),
        snapshot.atr,
        settings,
    )
    initial_stop = position.initial_stop_price
    effective_stop = max(
        value
        for value in (initial_stop, trailing_stop)
        if value is not None
    )

    if snapshot.close_price <= effective_stop:
        return MomentumExitDecision(
            should_exit=True,
            reason="stop-loss" if initial_stop is not None and effective_stop == initial_stop else "trailing-stop",
            stop_price=effective_stop,
            trailing_stop_price=trailing_stop,
            highest_price_since_entry=highest_price,
            indicator_snapshot=snapshot,
        )

    take_profit = fixed_take_profit_price(position, settings)
    if take_profit is not None and snapshot.close_price >= take_profit:
        return MomentumExitDecision(
            should_exit=True,
            reason="take-profit",
            stop_price=take_profit,
            trailing_stop_price=trailing_stop,
            highest_price_since_entry=highest_price,
            indicator_snapshot=snapshot,
        )

    if settings.use_trend_failure_exit and snapshot.ema_fast < snapshot.ema_slow:
        return MomentumExitDecision(
            should_exit=True,
            reason="trend-failure",
            trailing_stop_price=trailing_stop,
            highest_price_since_entry=highest_price,
            indicator_snapshot=snapshot,
        )

    return MomentumExitDecision(
        should_exit=False,
        reason="hold",
        stop_price=effective_stop,
        trailing_stop_price=trailing_stop,
        highest_price_since_entry=highest_price,
        indicator_snapshot=snapshot,
    )
