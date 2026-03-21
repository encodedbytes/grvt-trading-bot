from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.config import load_config_text
from gravity_dca.grvt_models import Candle
from gravity_dca.momentum_state import MomentumBotState
from gravity_dca.momentum_strategy import (
    build_indicator_snapshot,
    evaluate_entry,
    evaluate_exit,
    should_start_new_position,
)


def config():
    loaded = load_config_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 3
ema_slow_period = 5
breakout_lookback = 3
adx_period = 3
min_adx = "20"
atr_period = 3
min_atr_percent = "0.1"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
max_cycles = 2
""",
        resolve_state_paths=False,
    )
    assert loaded.momentum is not None
    return loaded.momentum


def candle(open_time: int, open_price: str, high_price: str, low_price: str, close_price: str) -> Candle:
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


def bullish_breakout_candles() -> list[Candle]:
    return [
        candle(0, "10.0", "10.6", "9.9", "10.5"),
        candle(300, "10.5", "11.2", "10.4", "11.0"),
        candle(600, "11.0", "11.8", "10.9", "11.6"),
        candle(900, "11.6", "12.4", "11.5", "12.1"),
        candle(1200, "12.1", "12.9", "12.0", "12.7"),
        candle(1500, "12.7", "13.8", "12.6", "13.6"),
    ]


def trend_failure_candles() -> list[Candle]:
    return [
        candle(0, "14.0", "14.2", "13.7", "13.8"),
        candle(300, "13.8", "13.9", "13.0", "13.1"),
        candle(600, "13.1", "13.2", "12.2", "12.3"),
        candle(900, "12.3", "12.4", "11.5", "11.7"),
        candle(1200, "11.7", "11.8", "10.9", "11.0"),
        candle(1500, "11.0", "11.1", "10.2", "10.4"),
    ]


def test_build_indicator_snapshot_returns_latest_momentum_context() -> None:
    snapshot = build_indicator_snapshot(bullish_breakout_candles(), config())

    assert snapshot is not None
    assert snapshot.close_price == Decimal("13.6")
    assert snapshot.breakout_level == Decimal("12.7")
    assert snapshot.ema_fast > snapshot.ema_slow
    assert snapshot.adx >= Decimal("20")
    assert snapshot.atr_percent > Decimal("0.1")


def test_evaluate_entry_allows_clean_breakout() -> None:
    decision = evaluate_entry(bullish_breakout_candles(), config(), MomentumBotState())

    assert decision.should_enter is True
    assert decision.reason == "enter"
    assert decision.breakout_level == Decimal("12.7")
    assert decision.initial_stop_price is not None
    assert decision.trailing_stop_price is not None
    assert decision.trailing_stop_price < decision.indicator_snapshot.close_price


def test_evaluate_entry_blocks_when_cycle_limit_reached() -> None:
    state = MomentumBotState(completed_cycles=2)

    decision = evaluate_entry(bullish_breakout_candles(), config(), state)

    assert should_start_new_position(state, config()) is False
    assert decision.should_enter is False
    assert decision.reason == "position-not-allowed"


def test_evaluate_exit_holds_and_raises_trailing_stop() -> None:
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime(2026, 3, 20, tzinfo=timezone.utc),
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="123",
        highest_price_since_entry=Decimal("12.9"),
        initial_stop_price=Decimal("11.0"),
        trailing_stop_price=Decimal("11.8"),
        breakout_level=Decimal("12.1"),
        timeframe="5m",
    )

    decision = evaluate_exit(bullish_breakout_candles(), config(), state)

    assert decision.should_exit is False
    assert decision.reason == "hold"
    assert decision.highest_price_since_entry == Decimal("13.6")
    assert decision.trailing_stop_price is not None
    assert decision.trailing_stop_price >= Decimal("11.8")


def test_evaluate_exit_fires_initial_stop_before_other_reasons() -> None:
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime(2026, 3, 20, tzinfo=timezone.utc),
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="123",
        highest_price_since_entry=Decimal("12.5"),
        initial_stop_price=Decimal("11.3"),
        trailing_stop_price=Decimal("10.8"),
        breakout_level=Decimal("12.1"),
        timeframe="5m",
    )

    decision = evaluate_exit(trend_failure_candles(), config(), state)

    assert decision.should_exit is True
    assert decision.reason == "stop-loss"
    assert decision.stop_price == Decimal("11.3")


def test_evaluate_exit_fires_trend_failure_when_stop_not_hit() -> None:
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime(2026, 3, 20, tzinfo=timezone.utc),
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="123",
        highest_price_since_entry=Decimal("10.9"),
        initial_stop_price=Decimal("9.0"),
        trailing_stop_price=Decimal("8.5"),
        breakout_level=Decimal("12.1"),
        timeframe="5m",
    )

    decision = evaluate_exit(trend_failure_candles(), config(), state)

    assert decision.should_exit is True
    assert decision.reason == "trend-failure"
