from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.state import BotState, load_state, save_state


UTC = timezone.utc


def test_state_round_trip_preserves_position_config(tmp_path) -> None:
    path = tmp_path / ".gravity-dca-state.json"
    state = BotState()
    now = datetime.now(tz=UTC)

    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=now,
        quantity=Decimal("0.25"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
        leverage=Decimal("10"),
        margin_type="CROSS",
    )
    save_state(path, state)

    loaded = load_state(path)

    assert loaded.active_cycle is not None
    assert loaded.active_cycle.leverage == Decimal("10")
    assert loaded.active_cycle.margin_type == "CROSS"


def test_close_cycle_carries_position_config_to_history() -> None:
    state = BotState()
    now = datetime.now(tz=UTC)

    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=now,
        quantity=Decimal("0.25"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
        leverage=Decimal("10"),
        margin_type="CROSS",
    )
    state.close_cycle(
        when=now,
        exit_reason="take-profit",
        exit_price=Decimal("2040"),
    )

    assert state.last_closed_cycle is not None
    assert state.last_closed_cycle.leverage == Decimal("10")
    assert state.last_closed_cycle.margin_type == "CROSS"
