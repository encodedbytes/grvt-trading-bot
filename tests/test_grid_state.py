from datetime import datetime, timezone
from decimal import Decimal

import pytest

from gravity_dca.grid_state import GridBotState, load_grid_state, load_grid_state_text, save_grid_state


UTC = timezone.utc


def test_grid_state_round_trip_preserves_grid_definition_and_levels(tmp_path) -> None:
    path = tmp_path / ".gravity-grid-state.json"
    now = datetime.now(tz=UTC)
    state = GridBotState()

    state.initialize_grid(
        symbol="ETH_USDT_Perp",
        side="buy",
        price_band_low=Decimal("1800"),
        price_band_high=Decimal("2200"),
        grid_levels=4,
        spacing_mode="arithmetic",
        quote_amount_per_level=Decimal("100"),
        prices=[
            Decimal("1800"),
            Decimal("1933.33"),
            Decimal("2066.67"),
            Decimal("2200"),
        ],
        when=now,
    )
    state.open_buy_order(
        level_index=0,
        when=now,
        order_id="0xentry",
        client_order_id="entry-1",
    )
    state.mark_buy_filled(
        level_index=0,
        when=now,
        fill_price=Decimal("1800"),
        quantity=Decimal("0.05"),
    )
    state.open_sell_order(
        level_index=0,
        when=now,
        order_id="0xexit",
        client_order_id="exit-1",
    )
    state.mark_reconciled(now)
    save_grid_state(path, state)

    loaded = load_grid_state(path)

    assert loaded.grid is not None
    assert loaded.grid.symbol == "ETH_USDT_Perp"
    assert loaded.grid.price_band_low == Decimal("1800")
    assert loaded.grid.grid_levels == 4
    assert len(loaded.levels) == 4
    assert loaded.levels[0].status == "sell_open"
    assert loaded.levels[0].entry_fill_price == Decimal("1800")
    assert loaded.levels[0].entry_quantity == Decimal("0.05")
    assert loaded.levels[0].exit_order_id == "0xexit"
    assert loaded.active_inventory_levels == 1
    assert loaded.last_reconciled_at == now.astimezone(UTC).isoformat()


def test_mark_sell_filled_resets_level_and_increments_round_trips() -> None:
    now = datetime.now(tz=UTC)
    state = GridBotState()
    state.initialize_grid(
        symbol="ETH_USDT_Perp",
        side="buy",
        price_band_low=Decimal("1800"),
        price_band_high=Decimal("2200"),
        grid_levels=2,
        spacing_mode="arithmetic",
        quote_amount_per_level=Decimal("100"),
        prices=[Decimal("1800"), Decimal("2200")],
        when=now,
    )
    state.mark_buy_filled(
        level_index=0,
        when=now,
        fill_price=Decimal("1800"),
        quantity=Decimal("0.05"),
        order_id="0xentry",
        client_order_id="entry-1",
    )
    state.open_sell_order(
        level_index=0,
        when=now,
        order_id="0xexit",
        client_order_id="exit-1",
    )

    state.mark_sell_filled(
        level_index=0,
        when=now,
        fill_price=Decimal("1820"),
    )

    level = state.level(0)
    assert level.status == "idle"
    assert level.realized_pnl_estimate == Decimal("1.00")
    assert level.entry_fill_price is None
    assert level.entry_quantity is None
    assert level.exit_order_id is None
    assert state.completed_round_trips == 1
    assert state.active_inventory_levels == 0


def test_initialize_grid_requires_matching_level_count() -> None:
    state = GridBotState()

    with pytest.raises(ValueError, match="prices length must match grid_levels"):
        state.initialize_grid(
            symbol="ETH_USDT_Perp",
            side="buy",
            price_band_low=Decimal("1800"),
            price_band_high=Decimal("2200"),
            grid_levels=3,
            spacing_mode="arithmetic",
            quote_amount_per_level=Decimal("100"),
            prices=[Decimal("1800"), Decimal("2000")],
            when=datetime.now(tz=UTC),
        )


def test_open_sell_order_requires_existing_inventory() -> None:
    state = GridBotState()
    now = datetime.now(tz=UTC)
    state.initialize_grid(
        symbol="ETH_USDT_Perp",
        side="buy",
        price_band_low=Decimal("1800"),
        price_band_high=Decimal("2200"),
        grid_levels=2,
        spacing_mode="arithmetic",
        quote_amount_per_level=Decimal("100"),
        prices=[Decimal("1800"), Decimal("2200")],
        when=now,
    )

    with pytest.raises(ValueError, match="Cannot open sell order without filled inventory"):
        state.open_sell_order(
            level_index=0,
            when=now,
            order_id="0xexit",
            client_order_id="exit-1",
        )


def test_load_grid_state_text_defaults_for_empty_payload() -> None:
    loaded = load_grid_state_text("{}")

    assert loaded.grid is None
    assert loaded.levels == []
    assert loaded.completed_round_trips == 0


def test_open_buy_order_clears_stale_exit_fields_from_previous_round_trip() -> None:
    now = datetime.now(tz=UTC)
    state = GridBotState()
    state.initialize_grid(
        symbol="ETH_USDT_Perp",
        side="buy",
        price_band_low=Decimal("1800"),
        price_band_high=Decimal("2200"),
        grid_levels=2,
        spacing_mode="arithmetic",
        quote_amount_per_level=Decimal("100"),
        prices=[Decimal("1800"), Decimal("2200")],
        when=now,
    )
    level = state.level(0)
    level.exit_fill_price = Decimal("1820")
    level.realized_pnl_estimate = Decimal("1.00")
    level.entry_fill_price = Decimal("1800")
    level.entry_quantity = Decimal("0.05")

    state.open_buy_order(level_index=0, when=now, order_id="0xnew", client_order_id="buy-2")

    level = state.level(0)
    assert level.status == "buy_open"
    assert level.entry_fill_price is None
    assert level.entry_quantity is None
    assert level.exit_order_id is None
    assert level.exit_client_order_id is None
    assert level.exit_fill_price is None
    assert level.realized_pnl_estimate is None
    assert state.active_inventory_levels == 0
    assert state.last_error is None
