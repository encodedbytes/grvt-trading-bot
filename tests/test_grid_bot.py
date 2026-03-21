from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.config import load_config_text
from gravity_dca.exchange import InstrumentMeta, MarketSnapshot, PositionSnapshot
from gravity_dca.grid_bot import GridBot
from gravity_dca.grid_state import GridBotState
from gravity_dca.grid_strategy import build_grid_levels
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

[strategy]
type = "grid"

[grid]
symbol = "ETH_USDT_Perp"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 5
quote_amount_per_level = "100"
max_active_buy_orders = 2
max_inventory_levels = 2
state_file = "/state/.gravity-grid-eth.json"

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
    def __init__(self, *, market_price: str, open_orders=None, open_position=None, fills=None) -> None:
        self.market_price = Decimal(market_price)
        self._open_orders = list(open_orders or [])
        self._open_position = open_position
        self._fills = list(fills or [])
        self.placed_orders: list[dict] = []
        self.canceled_orders: list[dict] = []

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
            bid=self.market_price - Decimal("0.02"),
            ask=self.market_price,
            mid=self.market_price - Decimal("0.01"),
            last=self.market_price,
        )

    def fetch_open_orders(self, *, symbol: str):
        return list(self._open_orders)

    def get_open_position(self, symbol: str):
        return self._open_position

    def get_recent_fills(self, symbol: str, limit: int = 100):
        return list(self._fills)

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
        return {"result": {"order_id": f"0x{len(self.placed_orders)}"}}

    def cancel_order(self, **kwargs):
        self.canceled_orders.append(kwargs)
        return True


def initialized_state() -> GridBotState:
    state = GridBotState()
    grid = config(dry_run=False).grid
    assert grid is not None
    state.initialize_grid(
        symbol=grid.symbol,
        side=grid.side,
        price_band_low=grid.price_band_low,
        price_band_high=grid.price_band_high,
        grid_levels=grid.grid_levels,
        spacing_mode=grid.spacing_mode,
        quote_amount_per_level=grid.quote_amount_per_level,
        prices=build_grid_levels(grid),
        when=datetime(2026, 3, 20, tzinfo=UTC),
    )
    return state


def test_grid_startup_message_includes_symbol_and_side() -> None:
    message = format_startup_message(config(dry_run=True))

    assert "symbol=ETH_USDT_Perp" in message
    assert "side=buy" in message
    assert "order_type=limit" in message


def test_grid_bot_places_missing_buy_orders_in_dry_run(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    bot = GridBot.__new__(GridBot)
    bot._config = config(dry_run=True)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(market_price="2050")
    bot._notifier = fake_notifier
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.grid_bot.load_grid_state", lambda path: GridBotState())
    monkeypatch.setattr("gravity_dca.grid_bot.save_grid_state", lambda path, state: None)

    result = bot.run_once()

    assert result is True
    assert bot._exchange.placed_orders == []
    assert any("GRVT bot started" in message for message in fake_notifier.messages)


def test_grid_bot_persists_placed_buy_orders(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    saved: list[GridBotState] = []
    bot = GridBot.__new__(GridBot)
    bot._config = config(dry_run=False)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(market_price="2050")
    bot._notifier = fake_notifier
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.grid_bot.load_grid_state", lambda path: GridBotState())
    monkeypatch.setattr("gravity_dca.grid_bot.save_grid_state", lambda path, state: saved.append(state))

    result = bot.run_once()

    assert result is True
    assert len(bot._exchange.placed_orders) == 2
    assert saved[-1].level(2).status == "buy_open"
    assert saved[-1].level(1).status == "buy_open"
    assert any("grid buy order placed" in message for message in fake_notifier.messages)


def test_grid_bot_places_sell_order_for_filled_inventory(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    saved: list[GridBotState] = []
    state = initialized_state()
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state.mark_buy_filled(
        level_index=1,
        when=now,
        fill_price=Decimal("1900"),
        quantity=Decimal("0.05"),
    )
    bot = GridBot.__new__(GridBot)
    bot._config = config(dry_run=False)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(
        market_price="2050",
        open_position=PositionSnapshot(
            symbol="ETH_USDT_Perp",
            side="buy",
            size=Decimal("0.05"),
            average_entry_price=Decimal("1900"),
        ),
    )
    bot._notifier = fake_notifier
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.grid_bot.load_grid_state", lambda path: state)
    monkeypatch.setattr("gravity_dca.grid_bot.save_grid_state", lambda path, value: saved.append(value))

    result = bot.run_once()

    assert result is True
    assert len(bot._exchange.placed_orders) == 2
    assert any(order["side"] == "sell" and order["price"] == Decimal("2000") for order in bot._exchange.placed_orders)
    assert saved[-1].level(1).status == "sell_open"


def test_grid_bot_cancels_stale_buy_order(monkeypatch) -> None:
    state = initialized_state()
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state.open_buy_order(level_index=3, when=now, order_id="0xstale", client_order_id="buy-3")

    bot = GridBot.__new__(GridBot)
    bot._config = config(dry_run=False)
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange(
        market_price="2050",
        open_orders=[
            {
                "symbol": "ETH_USDT_Perp",
                "side": "buy",
                "price": "2100",
                "amount": "0.05",
                "id": "0xstale",
                "clientOrderId": "buy-3",
            }
        ],
    )
    bot._notifier = FakeNotifier()
    bot._startup_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    monkeypatch.setattr("gravity_dca.grid_bot.load_grid_state", lambda path: state)
    monkeypatch.setattr("gravity_dca.grid_bot.save_grid_state", lambda path, value: None)

    result = bot.run_once()

    assert result is True
    assert bot._exchange.canceled_orders[0]["order_id"] == "0xstale"
