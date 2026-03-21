from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.config import load_config_text
from gravity_dca.grid_state import GridBotState
from gravity_dca.grid_strategy import (
    build_grid_levels,
    paired_sell_price,
    plan_grid_orders,
    seed_level_index,
)


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


def test_build_grid_levels_returns_inclusive_arithmetic_levels() -> None:
    assert build_grid_levels(config()) == [
        Decimal("1800"),
        Decimal("1900"),
        Decimal("2000"),
        Decimal("2100"),
        Decimal("2200"),
    ]


def test_plan_grid_orders_places_closest_idle_buys_below_market() -> None:
    decision = plan_grid_orders(
        state=initialized_state(),
        settings=config(),
        market_price=Decimal("2050"),
    )

    assert [order.level_index for order in decision.desired_buy_orders] == [2, 1]
    assert [order.price for order in decision.desired_buy_orders] == [
        Decimal("2000"),
        Decimal("1900"),
    ]
    assert decision.desired_sell_orders == []
    assert decision.cancel_buy_level_indices == []


def test_plan_grid_orders_respects_existing_buy_orders_and_inventory_capacity() -> None:
    state = initialized_state()
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state.open_buy_order(level_index=2, when=now, order_id="0xbuy", client_order_id="buy-2")
    state.mark_buy_filled(
        level_index=1,
        when=now,
        fill_price=Decimal("1900"),
        quantity=Decimal("0.05"),
        order_id="0xfill",
        client_order_id="fill-1",
    )

    decision = plan_grid_orders(
        state=state,
        settings=config(),
        market_price=Decimal("2050"),
    )

    assert [order.level_index for order in decision.desired_buy_orders] == []
    assert decision.cancel_buy_level_indices == []


def test_plan_grid_orders_creates_paired_sell_for_filled_inventory() -> None:
    state = initialized_state()
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state.mark_buy_filled(
        level_index=1,
        when=now,
        fill_price=Decimal("1900"),
        quantity=Decimal("0.05"),
    )

    decision = plan_grid_orders(
        state=state,
        settings=config(),
        market_price=Decimal("2050"),
    )

    assert len(decision.desired_sell_orders) == 1
    assert decision.desired_sell_orders[0].level_index == 1
    assert decision.desired_sell_orders[0].paired_level_index == 2
    assert decision.desired_sell_orders[0].price == Decimal("2000")


def test_plan_grid_orders_marks_stale_buy_orders_for_cancellation() -> None:
    state = initialized_state()
    now = datetime(2026, 3, 20, tzinfo=UTC)
    state.open_buy_order(level_index=3, when=now, order_id="0xbuy", client_order_id="buy-3")

    decision = plan_grid_orders(
        state=state,
        settings=config(),
        market_price=Decimal("2050"),
    )

    assert decision.cancel_buy_level_indices == [3]


def test_seed_level_index_returns_highest_buyable_level_below_market() -> None:
    assert seed_level_index(settings=config(), market_price=Decimal("2050")) == 2
    assert seed_level_index(settings=config(), market_price=Decimal("1810")) == 0
    assert seed_level_index(settings=config(), market_price=Decimal("1800")) is None


def test_paired_sell_price_returns_none_for_top_level() -> None:
    levels = build_grid_levels(config())

    assert paired_sell_price(4, levels) is None
