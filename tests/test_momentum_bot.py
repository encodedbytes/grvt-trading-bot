from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.bot_api import build_shared_status
from gravity_dca.config import load_config_text
from gravity_dca.exchange import FillReport, InstrumentMeta, MarketSnapshot, PositionConfig
from gravity_dca.momentum_bot import MomentumBot
from gravity_dca.momentum_state import MomentumBotState
from gravity_dca.telegram import format_startup_message


UTC = timezone.utc


def config(*, dry_run: bool) -> object:
    return load_config_text(
        f"""
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
order_type = "market"
initial_leverage = "5"
margin_type = "CROSS"
max_cycles = 2
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
state_file = "/state/.gravity-momentum-eth.json"

[runtime]
dry_run = {"true" if dry_run else "false"}
poll_seconds = 30
""",
        resolve_state_paths=False,
    )


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str):
        self.messages.append(text)
        return type("Result", (), {"delivered": True, "detail": "sent"})()


class FakeExchange:
    def __init__(self, candles, report: FillReport | None = None) -> None:
        self._candles = candles
        self._report = report
        self.placed_orders: list[dict] = []

    def get_candles(self, symbol: str, *, timeframe: str, limit: int):
        return list(self._candles)

    def ensure_position_config(self, **kwargs):
        return []

    def get_instrument(self, symbol: str) -> InstrumentMeta:
        return InstrumentMeta(
            symbol=symbol,
            tick_size=Decimal("0.01"),
            min_size=Decimal("0.01"),
            min_notional=Decimal("20"),
            base_decimals=9,
        )

    def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            bid=self._candles[-1].close - Decimal("0.02"),
            ask=self._candles[-1].close,
            mid=self._candles[-1].close - Decimal("0.01"),
            last=self._candles[-1].close,
        )

    def round_amount(self, amount: Decimal, base_decimals: int) -> Decimal:
        quantum = Decimal("1").scaleb(-base_decimals)
        return amount.quantize(quantum)

    def align_amount_to_market(self, amount: Decimal, instrument: InstrumentMeta) -> Decimal:
        rounded = self.round_amount(amount, instrument.base_decimals)
        return (rounded // instrument.min_size) * instrument.min_size

    def round_price(self, price: Decimal, tick_size: Decimal) -> Decimal:
        return (price // tick_size) * tick_size

    def place_order(self, **kwargs):
        self.placed_orders.append(kwargs)
        return {"result": {"order_id": "0x01"}}

    def wait_for_fill(self, **kwargs):
        return self._report

    def get_effective_position_config(self, symbol: str) -> PositionConfig:
        return PositionConfig(leverage=Decimal("5"), margin_type="CROSS")


def candle(open_time: int, open_price: str, high_price: str, low_price: str, close_price: str):
    from gravity_dca.grvt_models import Candle

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


def bullish_breakout_candles():
    return [
        candle(0, "10.0", "10.6", "9.9", "10.5"),
        candle(300, "10.5", "11.2", "10.4", "11.0"),
        candle(600, "11.0", "11.8", "10.9", "11.6"),
        candle(900, "11.6", "12.4", "11.5", "12.1"),
        candle(1200, "12.1", "12.9", "12.0", "12.7"),
        candle(1500, "12.7", "13.8", "12.6", "13.6"),
    ]


def trend_failure_candles():
    return [
        candle(0, "14.0", "14.2", "13.7", "13.8"),
        candle(300, "13.8", "13.9", "13.0", "13.1"),
        candle(600, "13.1", "13.2", "12.2", "12.3"),
        candle(900, "12.3", "12.4", "11.5", "11.7"),
        candle(1200, "11.7", "11.8", "10.9", "11.0"),
        candle(1500, "11.0", "11.1", "10.2", "10.4"),
    ]


def test_momentum_startup_message_includes_symbol_and_side() -> None:
    message = format_startup_message(config(dry_run=True))

    assert "symbol=ETH_USDT_Perp" in message
    assert "side=buy" in message


def test_momentum_bot_enters_in_dry_run_without_persisting(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    bot = MomentumBot.__new__(MomentumBot)
    bot._config = config(dry_run=True)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(bullish_breakout_candles())
    bot._notifier = fake_notifier
    bot._shared_status = build_shared_status(bot._config, bot._logger)
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.momentum_bot.load_momentum_state", lambda path: MomentumBotState())
    monkeypatch.setattr("gravity_dca.momentum_bot.save_momentum_state", lambda path, state: None)

    result = bot.run_once()

    assert result is True
    assert any("GRVT bot started" in message for message in fake_notifier.messages)


def test_momentum_bot_persists_entry_fill(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    saved: list[MomentumBotState] = []
    report = FillReport(
        order_id="0x01",
        client_order_id="123",
        status="filled",
        traded_size=Decimal("36.76"),
        avg_fill_price=Decimal("13.60"),
        raw={},
    )
    bot = MomentumBot.__new__(MomentumBot)
    bot._config = config(dry_run=False)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(bullish_breakout_candles(), report=report)
    bot._notifier = fake_notifier
    bot._shared_status = build_shared_status(bot._config, bot._logger)
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.momentum_bot.load_momentum_state", lambda path: MomentumBotState())
    monkeypatch.setattr("gravity_dca.momentum_bot.save_momentum_state", lambda path, state: saved.append(state))

    result = bot.run_once()

    assert result is True
    assert saved[-1].active_position is not None
    assert saved[-1].active_position.average_entry_price == Decimal("13.60")
    assert saved[-1].active_position.trailing_stop_price is not None
    assert any("momentum entry filled" in message for message in fake_notifier.messages)


def test_momentum_bot_persists_exit_fill(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    saved: list[MomentumBotState] = []
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime(2026, 3, 20, tzinfo=UTC),
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
    report = FillReport(
        order_id="0x02",
        client_order_id="124",
        status="filled",
        traded_size=Decimal("1"),
        avg_fill_price=Decimal("10.40"),
        raw={},
    )
    bot = MomentumBot.__new__(MomentumBot)
    bot._config = config(dry_run=False)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(trend_failure_candles(), report=report)
    bot._notifier = fake_notifier
    bot._shared_status = build_shared_status(bot._config, bot._logger)
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.momentum_bot.load_momentum_state", lambda path: state)
    monkeypatch.setattr("gravity_dca.momentum_bot.save_momentum_state", lambda path, state: saved.append(state))

    result = bot.run_once()

    assert result is True
    assert saved[-1].active_position is None
    assert saved[-1].last_closed_position is not None
    assert saved[-1].last_closed_position.exit_reason == "trend-failure"
    assert any("trend-failure filled" in message for message in fake_notifier.messages)
