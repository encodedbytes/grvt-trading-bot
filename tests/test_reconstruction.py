from decimal import Decimal

from gravity_dca.config import DcaSettings
from gravity_dca.exchange import AccountFill, PositionSnapshot
from gravity_dca.reconstruction import reconstruct_active_cycle


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


def position(**overrides) -> PositionSnapshot:
    payload = {
        "symbol": "ETH_USDT_Perp",
        "side": "buy",
        "size": Decimal("2.11"),
        "average_entry_price": Decimal("2125.060189572"),
        "leverage": Decimal("10"),
        "margin_type": "CROSS",
        "raw": {},
    }
    payload.update(overrides)
    return PositionSnapshot(**payload)


def fill(**overrides) -> AccountFill:
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


def test_reconstruct_active_cycle_from_grouped_entry_fills() -> None:
    result = reconstruct_active_cycle(
        settings=settings(),
        position=position(),
        fills=[
            fill(
                event_time=1773440838451832111,
                size=Decimal("0.72"),
                price=Decimal("2082.36"),
                order_id="0x03",
                client_order_id="3",
            ),
            fill(
                event_time=1773418648883397746,
                size=Decimal("0.4"),
                price=Decimal("2120.0"),
                order_id="0x02",
                client_order_id="2",
            ),
            fill(
                event_time=1773418648883397745,
                size=Decimal("0.3"),
                price=Decimal("2120.0"),
                order_id="0x02",
                client_order_id="2",
            ),
            fill(
                event_time=1773407868617255413,
                size=Decimal("0.54"),
                price=Decimal("2174.87"),
                order_id="0x01",
                client_order_id="1",
            ),
            fill(
                event_time=1773407868617255412,
                size=Decimal("0.15"),
                price=Decimal("2174.32"),
                order_id="0x01",
                client_order_id="1",
            ),
        ],
    )

    assert result.succeeded is True
    assert result.cycle is not None
    assert result.cycle.total_quantity == Decimal("2.11")
    assert result.cycle.completed_safety_orders == 2
    assert result.cycle.last_client_order_id == "3"
    assert result.cycle.last_order_id == "0x03"


def test_reconstruct_fails_when_recent_fill_side_conflicts_with_live_position() -> None:
    result = reconstruct_active_cycle(
        settings=settings(),
        position=position(size=Decimal("0.72"), average_entry_price=Decimal("2082.36")),
        fills=[
            fill(side="sell", size=Decimal("0.72"), price=Decimal("2082.36")),
            fill(
                event_time=1773418648883397746,
                size=Decimal("0.72"),
                price=Decimal("2080.0"),
                order_id="0x02",
                client_order_id="2",
            ),
        ],
    )

    assert result.succeeded is False
    assert "Most recent fill side does not match" in result.message


def test_reconstruct_fails_when_notional_does_not_match_ladder() -> None:
    result = reconstruct_active_cycle(
        settings=settings(),
        position=position(size=Decimal("0.72"), average_entry_price=Decimal("2082.36")),
        fills=[
            fill(size=Decimal("0.72"), price=Decimal("2800.0")),
        ],
    )

    assert result.succeeded is False
    assert "did not match the configured DCA ladder" in result.message
