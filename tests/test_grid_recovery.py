from datetime import datetime, timezone
from decimal import Decimal

import pytest

from gravity_dca.config import load_config_text
from gravity_dca.exchange import AccountFill, PositionSnapshot
from gravity_dca.grid_recovery import GridOpenOrderSnapshot, reconcile_grid_state
from gravity_dca.grid_state import GridBotState
from gravity_dca.grid_strategy import build_grid_levels


UTC = timezone.utc


def config():
    loaded = load_config_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 5
quote_amount_per_level = "100"
max_active_buy_orders = 2
max_inventory_levels = 2
""",
        resolve_state_paths=False,
    )
    assert loaded.grid is not None
    return loaded.grid


def initialized_state() -> GridBotState:
    state = GridBotState()
    state.initialize_grid(
        symbol="ETH_USDT_Perp",
        side="buy",
        price_band_low=Decimal("1800"),
        price_band_high=Decimal("2200"),
        grid_levels=5,
        spacing_mode="arithmetic",
        quote_amount_per_level=Decimal("100"),
        prices=build_grid_levels(config()),
        when=datetime(2026, 3, 20, tzinfo=UTC),
    )
    return state


def fill(*, side: str, size: str, price: str, order_id: str | None, client_order_id: str | None) -> AccountFill:
    return AccountFill(
        event_time=1,
        symbol="ETH_USDT_Perp",
        side=side,
        size=Decimal(size),
        price=Decimal(price),
        order_id=order_id,
        client_order_id=client_order_id,
    )


def test_reconcile_grid_state_applies_missing_open_buy_order() -> None:
    decision = reconcile_grid_state(
        state=GridBotState(),
        settings=config(),
        open_orders=[
            GridOpenOrderSnapshot(
                symbol="ETH_USDT_Perp",
                side="buy",
                price=Decimal("1900"),
                size=Decimal("0.05"),
                order_id="0xbuy",
                client_order_id="buy-1",
            )
        ],
        exchange_position=None,
        fills=[],
        when=datetime(2026, 3, 20, tzinfo=UTC),
    )

    assert decision.action == "rebuild-from-open-orders"
    assert decision.recovered_state.level(1).status == "buy_open"
    assert decision.recovered_state.level(1).entry_order_id == "0xbuy"


def test_reconcile_grid_state_initializes_from_config_when_local_state_is_missing() -> None:
    decision = reconcile_grid_state(
        state=GridBotState(),
        settings=config(),
        open_orders=[],
        exchange_position=None,
        fills=[],
        when=datetime(2026, 3, 20, tzinfo=UTC),
    )

    assert decision.action == "initialize-from-config"
    assert decision.recovered_state.grid is not None
    assert len(decision.recovered_state.levels) == 5


def test_reconcile_grid_state_clears_stale_open_buy_order_without_fill() -> None:
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state = initialized_state()
    state.open_buy_order(level_index=1, when=now, order_id="0xbuy", client_order_id="buy-1")

    decision = reconcile_grid_state(
        state=state,
        settings=config(),
        open_orders=[],
        exchange_position=None,
        fills=[],
        when=now,
    )

    assert decision.action == "reconciled"
    assert decision.recovered_state.level(1).status == "idle"
    assert decision.recovered_state.level(1).entry_order_id is None


def test_reconcile_grid_state_promotes_stale_buy_order_to_inventory_when_fill_exists() -> None:
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state = GridBotState()
    expected = initialized_state()
    state.initialize_grid(
        symbol=expected.grid.symbol,
        side=expected.grid.side,
        price_band_low=expected.grid.price_band_low,
        price_band_high=expected.grid.price_band_high,
        grid_levels=expected.grid.grid_levels,
        spacing_mode=expected.grid.spacing_mode,
        quote_amount_per_level=expected.grid.quote_amount_per_level,
        prices=[level.price for level in expected.levels],
        when=now,
    )
    state.open_buy_order(level_index=1, when=now, order_id="0xbuy", client_order_id="buy-1")

    decision = reconcile_grid_state(
        state=state,
        settings=config(),
        open_orders=[],
        exchange_position=PositionSnapshot(
            symbol="ETH_USDT_Perp",
            side="buy",
            size=Decimal("0.05"),
            average_entry_price=Decimal("1900"),
        ),
        fills=[fill(side="buy", size="0.05", price="1900", order_id="0xbuy", client_order_id="buy-1")],
        when=now,
    )

    assert decision.action == "reconciled"
    assert decision.recovered_state.level(1).status == "filled_inventory"
    assert decision.recovered_state.level(1).entry_fill_price == Decimal("1900")
    assert decision.recovered_state.active_inventory_levels == 1


def test_reconcile_grid_state_rebuilds_sell_inventory_from_empty_local_state() -> None:
    now = datetime(2026, 3, 20, tzinfo=UTC)

    decision = reconcile_grid_state(
        state=GridBotState(),
        settings=config(),
        open_orders=[
            GridOpenOrderSnapshot(
                symbol="ETH_USDT_Perp",
                side="sell",
                price=Decimal("2000"),
                size=Decimal("0.05"),
                order_id="0xsell",
                client_order_id="sell-1",
            )
        ],
        exchange_position=PositionSnapshot(
            symbol="ETH_USDT_Perp",
            side="buy",
            size=Decimal("0.05"),
            average_entry_price=Decimal("1900"),
        ),
        fills=[fill(side="buy", size="0.05", price="1900", order_id="0xbuy", client_order_id="buy-1")],
        when=now,
    )

    assert decision.action == "rebuild-from-open-orders-and-fills"
    assert decision.recovered_state.level(1).status == "sell_open"
    assert decision.recovered_state.level(1).entry_fill_price == Decimal("1900")
    assert decision.recovered_state.level(1).exit_order_id == "0xsell"


def test_reconcile_grid_state_promotes_inventory_to_open_sell_order() -> None:
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state = initialized_state()
    state.mark_buy_filled(
        level_index=1,
        when=now,
        fill_price=Decimal("1900"),
        quantity=Decimal("0.05"),
        order_id="0xbuy",
        client_order_id="buy-1",
    )

    decision = reconcile_grid_state(
        state=state,
        settings=config(),
        open_orders=[
            GridOpenOrderSnapshot(
                symbol="ETH_USDT_Perp",
                side="sell",
                price=Decimal("2000"),
                size=Decimal("0.05"),
                order_id="0xsell",
                client_order_id="sell-1",
            )
        ],
        exchange_position=PositionSnapshot(
            symbol="ETH_USDT_Perp",
            side="buy",
            size=Decimal("0.05"),
            average_entry_price=Decimal("1900"),
        ),
        fills=[],
        when=now,
    )

    assert decision.recovered_state.level(1).status == "sell_open"
    assert decision.recovered_state.level(1).exit_order_id == "0xsell"


def test_reconcile_grid_state_raises_for_duplicate_open_orders_on_same_level() -> None:
    with pytest.raises(ValueError, match="Multiple open orders map to the same grid slot"):
        reconcile_grid_state(
            state=initialized_state(),
            settings=config(),
            open_orders=[
                GridOpenOrderSnapshot(
                    symbol="ETH_USDT_Perp",
                    side="buy",
                    price=Decimal("1900"),
                    size=Decimal("0.05"),
                    order_id="0x01",
                    client_order_id="buy-1",
                ),
                GridOpenOrderSnapshot(
                    symbol="ETH_USDT_Perp",
                    side="buy",
                    price=Decimal("1900"),
                    size=Decimal("0.05"),
                    order_id="0x02",
                    client_order_id="buy-2",
                ),
            ],
            exchange_position=None,
            fills=[],
            when=datetime(2026, 3, 20, tzinfo=UTC),
        )


def test_reconcile_grid_state_raises_when_inventory_disagrees_with_exchange_position() -> None:
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state = initialized_state()
    state.mark_buy_filled(
        level_index=1,
        when=now,
        fill_price=Decimal("1900"),
        quantity=Decimal("0.05"),
    )

    with pytest.raises(ValueError, match="Grid inventory quantity does not match exchange position"):
        reconcile_grid_state(
            state=state,
            settings=config(),
            open_orders=[],
            exchange_position=PositionSnapshot(
                symbol="ETH_USDT_Perp",
                side="buy",
                size=Decimal("0.10"),
                average_entry_price=Decimal("1900"),
            ),
            fills=[],
            when=now,
        )
