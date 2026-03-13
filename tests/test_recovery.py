from datetime import datetime, timezone
from decimal import Decimal

import pytest

from gravity_dca.exchange import PositionSnapshot
from gravity_dca.recovery import reconcile_state
from gravity_dca.state import BotState


UTC = timezone.utc


def position_snapshot(**overrides) -> PositionSnapshot:
    payload = {
        "symbol": "ETH_USDT_Perp",
        "side": "buy",
        "size": Decimal("0.50"),
        "average_entry_price": Decimal("2000"),
        "leverage": Decimal("10"),
        "margin_type": "CROSS",
        "raw": {},
    }
    payload.update(overrides)
    return PositionSnapshot(**payload)


def test_reconcile_rebuilds_when_exchange_has_position_and_local_state_is_missing() -> None:
    decision = reconcile_state(
        state=BotState(),
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(),
        when=datetime.now(tz=UTC),
    )

    assert decision.action == "rebuild-from-exchange"
    assert decision.recovered_cycle is not None
    assert decision.recovered_cycle.total_quantity == Decimal("0.50")
    assert decision.recovered_cycle.average_entry_price == Decimal("2000")
    assert decision.recovered_cycle.leverage == Decimal("10")
    assert decision.recovered_cycle.margin_type == "CROSS"


def test_reconcile_clears_stale_local_state_when_exchange_position_is_missing() -> None:
    state = BotState()
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime.now(tz=UTC),
        quantity=Decimal("0.50"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
    )

    decision = reconcile_state(
        state=state,
        symbol="ETH_USDT_Perp",
        exchange_position=None,
        when=datetime.now(tz=UTC),
    )

    assert decision.action == "clear-stale-local"
    assert decision.recovered_cycle is None


def test_reconcile_keeps_matching_local_state_and_refreshes_exchange_backed_fields() -> None:
    state = BotState()
    when = datetime.now(tz=UTC)
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=when,
        quantity=Decimal("0.50"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
    )

    decision = reconcile_state(
        state=state,
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(leverage=Decimal("5"), margin_type="ISOLATED"),
        when=when,
    )

    assert decision.action == "keep-local"
    assert decision.recovered_cycle is not None
    assert decision.recovered_cycle.started_at == state.active_cycle.started_at
    assert decision.recovered_cycle.leverage == Decimal("5")
    assert decision.recovered_cycle.margin_type == "ISOLATED"


def test_reconcile_raises_when_side_mismatches() -> None:
    state = BotState()
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime.now(tz=UTC),
        quantity=Decimal("0.50"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
    )

    with pytest.raises(ValueError, match="sides do not match"):
        reconcile_state(
            state=state,
            symbol="ETH_USDT_Perp",
            exchange_position=position_snapshot(side="sell"),
            when=datetime.now(tz=UTC),
        )


def test_reconcile_raises_when_quantity_mismatches() -> None:
    state = BotState()
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime.now(tz=UTC),
        quantity=Decimal("0.50"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
    )

    with pytest.raises(ValueError, match="quantities do not match"):
        reconcile_state(
            state=state,
            symbol="ETH_USDT_Perp",
            exchange_position=position_snapshot(size=Decimal("0.75")),
            when=datetime.now(tz=UTC),
        )
