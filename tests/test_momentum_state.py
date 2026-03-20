from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.momentum_state import (
    ActiveMomentumState,
    MomentumBotState,
    load_momentum_state,
    load_momentum_state_text,
    save_momentum_state,
)


UTC = timezone.utc


def test_momentum_state_round_trip_preserves_active_position_fields(tmp_path) -> None:
    path = tmp_path / ".gravity-momentum-state.json"
    state = MomentumBotState()
    now = datetime.now(tz=UTC)

    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=now,
        quantity=Decimal("0.25"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
        leverage=Decimal("10"),
        margin_type="CROSS",
        highest_price_since_entry=Decimal("2005"),
        initial_stop_price=Decimal("1970"),
        trailing_stop_price=Decimal("1985"),
        breakout_level=Decimal("1998"),
        timeframe="5m",
    )
    save_momentum_state(path, state)

    loaded = load_momentum_state(path)

    assert loaded.active_position is not None
    assert loaded.active_position.symbol == "ETH_USDT_Perp"
    assert loaded.active_position.leverage == Decimal("10")
    assert loaded.active_position.margin_type == "CROSS"
    assert loaded.active_position.highest_price_since_entry == Decimal("2005")
    assert loaded.active_position.initial_stop_price == Decimal("1970")
    assert loaded.active_position.trailing_stop_price == Decimal("1985")
    assert loaded.active_position.breakout_level == Decimal("1998")
    assert loaded.active_position.timeframe == "5m"


def test_close_momentum_position_carries_summary_fields_to_history() -> None:
    state = MomentumBotState()
    now = datetime.now(tz=UTC)

    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=now,
        quantity=Decimal("0.25"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
        leverage=Decimal("10"),
        margin_type="CROSS",
        initial_stop_price=Decimal("1970"),
        trailing_stop_price=Decimal("1985"),
        breakout_level=Decimal("1998"),
        timeframe="5m",
    )
    state.close_position(
        when=now,
        exit_reason="trailing-stop",
        exit_price=Decimal("2040"),
    )

    assert state.last_closed_position is not None
    assert state.last_closed_position.leverage == Decimal("10")
    assert state.last_closed_position.margin_type == "CROSS"
    assert state.last_closed_position.exit_reason == "trailing-stop"
    assert state.last_closed_position.realized_pnl_estimate == Decimal("10.00")
    assert state.completed_cycles == 1
    assert state.active_position is None


def test_update_active_position_only_raises_high_water_mark() -> None:
    state = MomentumBotState(
        active_position=ActiveMomentumState(
            symbol="ETH_USDT_Perp",
            side="buy",
            started_at="2026-03-20T00:00:00+00:00",
            total_quantity=Decimal("1"),
            total_cost=Decimal("2000"),
            average_entry_price=Decimal("2000"),
            highest_price_since_entry=Decimal("2010"),
        )
    )

    state.update_active_position(
        highest_price_since_entry=Decimal("2005"),
        trailing_stop_price=Decimal("1990"),
    )
    assert state.active_position is not None
    assert state.active_position.highest_price_since_entry == Decimal("2010")
    assert state.active_position.trailing_stop_price == Decimal("1990")

    state.update_active_position(highest_price_since_entry=Decimal("2022"))
    assert state.active_position.highest_price_since_entry == Decimal("2022")


def test_load_momentum_state_text_defaults_when_file_is_empty_shape() -> None:
    loaded = load_momentum_state_text("{}")

    assert loaded.active_position is None
    assert loaded.completed_cycles == 0
    assert loaded.last_closed_position is None


def test_update_and_close_require_active_position() -> None:
    state = MomentumBotState()

    try:
        state.update_active_position(trailing_stop_price=Decimal("1900"))
    except ValueError as exc:
        assert str(exc) == "No active momentum position to update"
    else:
        raise AssertionError("ValueError was not raised")

    try:
        state.close_position(
            when=datetime.now(tz=UTC),
            exit_reason="trend-failure",
            exit_price=Decimal("1900"),
        )
    except ValueError as exc:
        assert str(exc) == "No active momentum position to close"
    else:
        raise AssertionError("ValueError was not raised")
