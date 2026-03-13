from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.config import DcaSettings
from gravity_dca.exchange import InstrumentMeta, MarketSnapshot, parse_grvt_decimal
from gravity_dca.state import ActiveCycleState, BotState
from gravity_dca.strategy import (
    build_entry_order_plan,
    build_exit_order_plan,
    current_deviation_percent,
    current_quote_amount,
    next_safety_trigger_price,
    should_place_safety_order,
    should_start_new_cycle,
    should_take_profit,
)


UTC = timezone.utc


class StubExchange:
    def round_amount(self, amount: Decimal, base_decimals: int) -> Decimal:
        quantum = Decimal("1").scaleb(-base_decimals)
        return amount.quantize(quantum)

    def align_amount_to_market(self, amount: Decimal, instrument: InstrumentMeta) -> Decimal:
        rounded = self.round_amount(amount, instrument.base_decimals)
        return (rounded // instrument.min_size) * instrument.min_size

    def round_price(self, price: Decimal, tick_size: Decimal) -> Decimal:
        return (price // tick_size) * tick_size


def settings() -> DcaSettings:
    return DcaSettings(
        symbol="BTC_USDT_Perp",
        side="buy",
        initial_quote_amount=Decimal("100"),
        safety_order_quote_amount=Decimal("150"),
        order_type="market",
        limit_price_offset_percent=Decimal("0"),
        max_safety_orders=3,
        price_deviation_percent=Decimal("2"),
        take_profit_percent=Decimal("1.5"),
        safety_order_step_scale=Decimal("1.5"),
        safety_order_volume_scale=Decimal("2"),
        stop_loss_percent=Decimal("10"),
    )


def test_cycle_can_start_when_no_active_cycle() -> None:
    assert should_start_new_cycle(BotState(), settings()) is True


def test_quote_amount_scales_for_safety_orders() -> None:
    assert current_quote_amount(settings(), 0) == Decimal("100")
    assert current_quote_amount(settings(), 1) == Decimal("150")
    assert current_quote_amount(settings(), 2) == Decimal("300")


def test_deviation_scales_for_next_safety_order() -> None:
    assert current_deviation_percent(settings(), 1) == Decimal("2")
    assert current_deviation_percent(settings(), 2) == Decimal("3.0")


def test_next_safety_trigger_uses_average_entry() -> None:
    cycle = ActiveCycleState(
        symbol="BTC_USDT_Perp",
        side="buy",
        started_at=datetime.now(tz=UTC).isoformat(),
        total_quantity=Decimal("0.01"),
        total_cost=Decimal("1000"),
        average_entry_price=Decimal("100000"),
    )
    assert next_safety_trigger_price(cycle, settings()) == Decimal("98000")


def test_take_profit_triggers_for_long() -> None:
    cycle = ActiveCycleState(
        symbol="BTC_USDT_Perp",
        side="buy",
        started_at=datetime.now(tz=UTC).isoformat(),
        total_quantity=Decimal("0.01"),
        total_cost=Decimal("1000"),
        average_entry_price=Decimal("100000"),
    )
    snapshot = MarketSnapshot(
        symbol="BTC_USDT_Perp",
        bid=Decimal("101600"),
        ask=Decimal("101620"),
        mid=Decimal("101610"),
        last=Decimal("101615"),
    )
    assert should_take_profit(cycle, snapshot, settings()) is True


def test_safety_order_triggers_after_price_moves_against_position() -> None:
    cycle = ActiveCycleState(
        symbol="BTC_USDT_Perp",
        side="buy",
        started_at=datetime.now(tz=UTC).isoformat(),
        total_quantity=Decimal("0.01"),
        total_cost=Decimal("1000"),
        average_entry_price=Decimal("100000"),
    )
    snapshot = MarketSnapshot(
        symbol="BTC_USDT_Perp",
        bid=Decimal("97990"),
        ask=Decimal("97999"),
        mid=Decimal("97995"),
        last=Decimal("97998"),
    )
    assert should_place_safety_order(cycle, snapshot, settings()) is True


def test_entry_order_sizes_from_quote_budget() -> None:
    instrument = InstrumentMeta(
        symbol="BTC_USDT_Perp",
        tick_size=Decimal("0.1"),
        min_size=Decimal("0.001"),
        min_notional=Decimal("10"),
        base_decimals=3,
    )
    snapshot = MarketSnapshot(
        symbol="BTC_USDT_Perp",
        bid=Decimal("49999"),
        ask=Decimal("50000"),
        mid=Decimal("49999.5"),
        last=Decimal("50001"),
    )
    plan = build_entry_order_plan(
        settings=settings(),
        symbol="BTC_USDT_Perp",
        side="buy",
        quote_amount=Decimal("100"),
        instrument=instrument,
        snapshot=snapshot,
        exchange=StubExchange(),
        reason="initial-entry",
    )
    assert plan.amount == Decimal("0.002")
    assert plan.order_type == "market"
    assert plan.price is None


def test_amount_aligns_to_exchange_min_size_step() -> None:
    instrument = InstrumentMeta(
        symbol="ETH_USDT_Perp",
        tick_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
        min_notional=Decimal("20"),
        base_decimals=9,
    )
    snapshot = MarketSnapshot(
        symbol="ETH_USDT_Perp",
        bid=Decimal("2024.40"),
        ask=Decimal("2024.41"),
        mid=Decimal("2024.405"),
        last=Decimal("2024.41"),
    )
    plan = build_entry_order_plan(
        settings=settings(),
        symbol="ETH_USDT_Perp",
        side="buy",
        quote_amount=Decimal("25"),
        instrument=instrument,
        snapshot=snapshot,
        exchange=StubExchange(),
        reason="initial-entry",
    )
    assert plan.amount == Decimal("0.01")


def test_limit_entry_order_uses_aggressive_limit_price() -> None:
    instrument = InstrumentMeta(
        symbol="ETH_USDT_Perp",
        tick_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
        min_notional=Decimal("20"),
        base_decimals=9,
    )
    snapshot = MarketSnapshot(
        symbol="ETH_USDT_Perp",
        bid=Decimal("2024.40"),
        ask=Decimal("2024.41"),
        mid=Decimal("2024.405"),
        last=Decimal("2024.41"),
    )
    limit_settings = DcaSettings(
        symbol="ETH_USDT_Perp",
        side="buy",
        initial_quote_amount=Decimal("25"),
        safety_order_quote_amount=Decimal("25"),
        order_type="limit",
        limit_price_offset_percent=Decimal("0.1"),
        max_safety_orders=1,
        price_deviation_percent=Decimal("2"),
        take_profit_percent=Decimal("1.5"),
    )
    plan = build_entry_order_plan(
        settings=limit_settings,
        symbol="ETH_USDT_Perp",
        side="buy",
        quote_amount=Decimal("25"),
        instrument=instrument,
        snapshot=snapshot,
        exchange=StubExchange(),
        reason="initial-entry",
    )
    assert plan.order_type == "limit"
    assert plan.price == Decimal("2026.43")


def test_limit_exit_order_uses_aggressive_limit_price() -> None:
    instrument = InstrumentMeta(
        symbol="ETH_USDT_Perp",
        tick_size=Decimal("0.01"),
        min_size=Decimal("0.01"),
        min_notional=Decimal("20"),
        base_decimals=9,
    )
    cycle = ActiveCycleState(
        symbol="ETH_USDT_Perp",
        side="buy",
        started_at=datetime.now(tz=UTC).isoformat(),
        total_quantity=Decimal("0.50"),
        total_cost=Decimal("1000"),
        average_entry_price=Decimal("2000"),
    )
    snapshot = MarketSnapshot(
        symbol="ETH_USDT_Perp",
        bid=Decimal("2050.00"),
        ask=Decimal("2050.05"),
        mid=Decimal("2050.025"),
        last=Decimal("2050.03"),
    )
    limit_settings = DcaSettings(
        symbol="ETH_USDT_Perp",
        side="buy",
        initial_quote_amount=Decimal("25"),
        safety_order_quote_amount=Decimal("25"),
        order_type="limit",
        limit_price_offset_percent=Decimal("0.2"),
        max_safety_orders=1,
        price_deviation_percent=Decimal("2"),
        take_profit_percent=Decimal("1.5"),
    )
    plan = build_exit_order_plan(
        cycle=cycle,
        settings=limit_settings,
        instrument=instrument,
        snapshot=snapshot,
        exchange=StubExchange(),
        reason="take-profit",
    )
    assert plan.order_type == "limit"
    assert plan.side == "sell"
    assert plan.price == Decimal("2045.90")


def test_parse_grvt_decimal_supports_current_decimal_strings() -> None:
    assert parse_grvt_decimal("69425.0") == Decimal("69425.0")


def test_parse_grvt_decimal_supports_legacy_scaled_integers() -> None:
    assert parse_grvt_decimal("69425000000000") == Decimal("69425")
