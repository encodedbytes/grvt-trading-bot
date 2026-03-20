from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from gravity_dca.config import load_config_text
from gravity_dca.exchange import AccountFill, PositionSnapshot
from gravity_dca.grvt_models import Candle
from gravity_dca.momentum_recovery import reconcile_momentum_state
from gravity_dca.momentum_state import MomentumBotState


UTC = timezone.utc


def settings():
    config = load_config_text(
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
""",
        resolve_state_paths=False,
    )
    assert config.momentum is not None
    return config.momentum


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


def position_snapshot(**overrides) -> PositionSnapshot:
    payload = {
        "symbol": "ETH_USDT_Perp",
        "side": "buy",
        "size": Decimal("1"),
        "average_entry_price": Decimal("12.0"),
        "leverage": Decimal("5"),
        "margin_type": "CROSS",
        "raw": {},
    }
    payload.update(overrides)
    return PositionSnapshot(**payload)


def account_fill(**overrides) -> AccountFill:
    payload = {
        "event_time": 1_763_427_200_000_000_000,
        "symbol": "ETH_USDT_Perp",
        "side": "buy",
        "size": Decimal("1"),
        "price": Decimal("12.0"),
        "order_id": "0x01",
        "client_order_id": "cid-1",
        "raw": {},
    }
    payload.update(overrides)
    return AccountFill(**payload)


def test_reconcile_momentum_rebuilds_from_exchange_when_local_state_missing() -> None:
    decision = reconcile_momentum_state(
        state=MomentumBotState(),
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(),
        exchange_fills=None,
        candles=bullish_breakout_candles(),
        when=datetime.now(tz=UTC),
    )

    assert decision.action == "rebuild-from-exchange"
    assert decision.recovered_position is not None
    assert decision.recovered_position.average_entry_price == Decimal("12.0")
    assert decision.recovered_position.initial_stop_price is not None
    assert decision.recovered_position.trailing_stop_price is not None


def test_reconcile_momentum_uses_entry_fill_metadata_when_available() -> None:
    decision = reconcile_momentum_state(
        state=MomentumBotState(),
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(),
        exchange_fills=[account_fill()],
        candles=bullish_breakout_candles(),
        when=datetime.now(tz=UTC),
    )

    assert decision.action == "rebuild-from-exchange-history"
    assert decision.recovered_position is not None
    assert decision.recovered_position.last_order_id == "0x01"
    assert decision.recovered_position.last_client_order_id == "cid-1"


def test_reconcile_momentum_refreshes_matching_local_state() -> None:
    state = MomentumBotState()
    now = datetime.now(tz=UTC)
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=now,
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="cid-1",
        highest_price_since_entry=Decimal("12.9"),
        initial_stop_price=Decimal("11.0"),
        trailing_stop_price=Decimal("11.5"),
        breakout_level=Decimal("12.1"),
        timeframe="5m",
    )

    decision = reconcile_momentum_state(
        state=state,
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(),
        exchange_fills=[account_fill()],
        candles=bullish_breakout_candles(),
        when=now,
    )

    assert decision.action == "keep-local"
    assert decision.recovered_position is not None
    assert decision.recovered_position.highest_price_since_entry == Decimal("13.6")
    assert decision.recovered_position.trailing_stop_price is not None


def test_reconcile_momentum_clears_stale_local_state_when_exchange_missing() -> None:
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime.now(tz=UTC),
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="cid-1",
    )

    decision = reconcile_momentum_state(
        state=state,
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=None,
        exchange_fills=None,
        candles=bullish_breakout_candles(),
        when=datetime.now(tz=UTC),
    )

    assert decision.action == "clear-stale-local"


def test_reconcile_momentum_raises_when_position_mismatches() -> None:
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime.now(tz=UTC),
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="cid-1",
    )

    with pytest.raises(ValueError, match="quantities do not match"):
        reconcile_momentum_state(
            state=state,
            settings=settings(),
            symbol="ETH_USDT_Perp",
            exchange_position=position_snapshot(size=Decimal("1.25")),
            exchange_fills=None,
            candles=bullish_breakout_candles(),
            when=datetime.now(tz=UTC),
        )
