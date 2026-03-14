from datetime import datetime, timezone
from decimal import Decimal

import pytest

from gravity_dca.config import DcaSettings
from gravity_dca.exchange import AccountFill
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


def settings() -> DcaSettings:
    return DcaSettings(
        symbol="ETH_USDT_Perp",
        side="buy",
        initial_quote_amount=Decimal("1500"),
        safety_order_quote_amount=Decimal("1500"),
        order_type="market",
        limit_price_offset_percent=Decimal("0"),
        max_safety_orders=3,
        price_deviation_percent=Decimal("2.5"),
        take_profit_percent=Decimal("2.0"),
        safety_order_step_scale=Decimal("1.2"),
        safety_order_volume_scale=Decimal("1.0"),
        stop_loss_percent=Decimal("10.0"),
    )


def account_fill(**overrides) -> AccountFill:
    payload = {
        "event_time": 1773440838451832111,
        "symbol": "ETH_USDT_Perp",
        "side": "buy",
        "size": Decimal("0.72"),
        "price": Decimal("2082.36"),
        "order_id": "0x03",
        "client_order_id": "3",
        "raw": {},
    }
    payload.update(overrides)
    return AccountFill(**payload)


def test_reconcile_rebuilds_when_exchange_has_position_and_local_state_is_missing() -> None:
    decision = reconcile_state(
        state=BotState(),
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(),
        exchange_fills=[],
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
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=None,
        exchange_fills=None,
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
        settings=settings(),
        symbol="ETH_USDT_Perp",
        exchange_position=position_snapshot(
            size=Decimal("2.11"),
            average_entry_price=Decimal("2125.060189572"),
            leverage=Decimal("10"),
            margin_type="CROSS",
        ),
        exchange_fills=[
            account_fill(
                event_time=1773440838451832111,
                size=Decimal("0.72"),
                price=Decimal("2082.36"),
                order_id="0x03",
                client_order_id="3",
            ),
            account_fill(
                event_time=1773418648883397746,
                size=Decimal("0.7"),
                price=Decimal("2120.0"),
                order_id="0x02",
                client_order_id="2",
            ),
            account_fill(
                event_time=1773407868617255413,
                size=Decimal("0.69"),
                price=Decimal("2174.750289855072463768115942"),
                order_id="0x01",
                client_order_id="1",
            ),
        ],
        when=when,
    )

    assert decision.action == "rebuild-from-exchange-history"
    assert decision.recovered_cycle is not None
    assert decision.recovered_cycle.total_quantity == Decimal("2.11")
    assert decision.recovered_cycle.completed_safety_orders == 2
    assert decision.recovered_cycle.leverage == Decimal("10")
    assert decision.recovered_cycle.margin_type == "CROSS"
    assert decision.reconstruction_attempted is True
    assert decision.reconstruction_succeeded is True


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
            settings=settings(),
            symbol="ETH_USDT_Perp",
            exchange_position=position_snapshot(side="sell"),
            exchange_fills=[],
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
            settings=settings(),
            symbol="ETH_USDT_Perp",
            exchange_position=position_snapshot(size=Decimal("0.75")),
            exchange_fills=[],
            when=datetime.now(tz=UTC),
        )
