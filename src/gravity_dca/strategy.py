from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import uuid

from .config import DcaSettings
from .exchange import GrvtExchange, InstrumentMeta, MarketSnapshot
from .state import ActiveCycleState, BotState


@dataclass(frozen=True)
class OrderPlan:
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    amount: Decimal
    price: Decimal | None
    reduce_only: bool = False
    reason: str = ""


def validate_order_type(order_type: str) -> str:
    normalized = order_type.strip().lower()
    if normalized not in {"market", "limit"}:
        raise ValueError(f"Unsupported order_type: {order_type!r}")
    return normalized


def opposite_side(side: str) -> str:
    return "sell" if side == "buy" else "buy"


def entry_price(snapshot: MarketSnapshot, side: str) -> Decimal:
    return snapshot.ask if side == "buy" else snapshot.bid


def exit_price(snapshot: MarketSnapshot, side: str) -> Decimal:
    return snapshot.bid if side == "buy" else snapshot.ask


def current_quote_amount(settings: DcaSettings, safety_order_index: int) -> Decimal:
    if safety_order_index == 0:
        return settings.initial_quote_amount
    exponent = Decimal(safety_order_index - 1)
    return settings.safety_order_quote_amount * (settings.safety_order_volume_scale**exponent)


def current_deviation_percent(settings: DcaSettings, safety_order_index: int) -> Decimal:
    if safety_order_index <= 0:
        return Decimal("0")
    exponent = Decimal(safety_order_index - 1)
    return settings.price_deviation_percent * (settings.safety_order_step_scale**exponent)


def next_safety_trigger_price(cycle: ActiveCycleState, settings: DcaSettings) -> Decimal | None:
    if cycle.completed_safety_orders >= settings.max_safety_orders:
        return None
    deviation = current_deviation_percent(settings, cycle.completed_safety_orders + 1) / Decimal(
        "100"
    )
    if cycle.side == "buy":
        return cycle.average_entry_price * (Decimal("1") - deviation)
    return cycle.average_entry_price * (Decimal("1") + deviation)


def take_profit_price(cycle: ActiveCycleState, settings: DcaSettings) -> Decimal:
    tp = settings.take_profit_percent / Decimal("100")
    if cycle.side == "buy":
        return cycle.average_entry_price * (Decimal("1") + tp)
    return cycle.average_entry_price * (Decimal("1") - tp)


def stop_loss_price(cycle: ActiveCycleState, settings: DcaSettings) -> Decimal | None:
    if settings.stop_loss_percent is None:
        return None
    sl = settings.stop_loss_percent / Decimal("100")
    if cycle.side == "buy":
        return cycle.average_entry_price * (Decimal("1") - sl)
    return cycle.average_entry_price * (Decimal("1") + sl)


def should_take_profit(cycle: ActiveCycleState, snapshot: MarketSnapshot, settings: DcaSettings) -> bool:
    price = exit_price(snapshot, cycle.side)
    target = take_profit_price(cycle, settings)
    return price >= target if cycle.side == "buy" else price <= target


def should_stop_loss(cycle: ActiveCycleState, snapshot: MarketSnapshot, settings: DcaSettings) -> bool:
    stop_price = stop_loss_price(cycle, settings)
    if stop_price is None:
        return False
    price = exit_price(snapshot, cycle.side)
    return price <= stop_price if cycle.side == "buy" else price >= stop_price


def should_place_safety_order(
    cycle: ActiveCycleState,
    snapshot: MarketSnapshot,
    settings: DcaSettings,
) -> bool:
    trigger = next_safety_trigger_price(cycle, settings)
    if trigger is None:
        return False
    market_price = entry_price(snapshot, cycle.side)
    return market_price <= trigger if cycle.side == "buy" else market_price >= trigger


def compute_amount_from_quote(
    *,
    quote_amount: Decimal,
    reference_price: Decimal,
    instrument: InstrumentMeta,
    exchange: GrvtExchange,
) -> Decimal:
    if quote_amount < instrument.min_notional:
        raise ValueError(
            f"Configured quote amount {quote_amount} is smaller than exchange min_notional "
            f"{instrument.min_notional} for {instrument.symbol}"
        )
    raw_amount = quote_amount / reference_price
    amount = exchange.align_amount_to_market(raw_amount, instrument)
    if amount < instrument.min_size:
        raise ValueError(
            f"Computed amount {amount} is smaller than exchange min_size {instrument.min_size}"
        )
    return amount


def new_client_order_id() -> str:
    return str(uuid.uuid4().int % (2**63 - 1) + 2**63)


def limit_price_from_reference(
    *,
    side: str,
    reference_price: Decimal,
    offset_percent: Decimal,
    instrument: InstrumentMeta,
    exchange: GrvtExchange,
) -> Decimal:
    offset = offset_percent / Decimal("100")
    if side == "buy":
        price = reference_price * (Decimal("1") + offset)
    else:
        price = reference_price * (Decimal("1") - offset)
    rounded = exchange.round_price(price, instrument.tick_size)
    if rounded <= 0:
        raise ValueError(
            f"Computed limit price must be positive. side={side} "
            f"reference_price={reference_price} offset_percent={offset_percent}"
        )
    return rounded


def planned_price(
    *,
    settings: DcaSettings,
    side: str,
    reference_price: Decimal,
    instrument: InstrumentMeta,
    exchange: GrvtExchange,
) -> Decimal | None:
    if validate_order_type(settings.order_type) == "market":
        return None
    return limit_price_from_reference(
        side=side,
        reference_price=reference_price,
        offset_percent=settings.limit_price_offset_percent,
        instrument=instrument,
        exchange=exchange,
    )


def build_entry_order_plan(
    *,
    settings: DcaSettings,
    symbol: str,
    side: str,
    quote_amount: Decimal,
    instrument: InstrumentMeta,
    snapshot: MarketSnapshot,
    exchange: GrvtExchange,
    reason: str,
) -> OrderPlan:
    reference_price = entry_price(snapshot, side)
    amount = compute_amount_from_quote(
        quote_amount=quote_amount,
        reference_price=reference_price,
        instrument=instrument,
        exchange=exchange,
    )
    return OrderPlan(
        client_order_id=new_client_order_id(),
        symbol=symbol,
        side=side,
        order_type=validate_order_type(settings.order_type),
        amount=amount,
        price=planned_price(
            settings=settings,
            side=side,
            reference_price=reference_price,
            instrument=instrument,
            exchange=exchange,
        ),
        reduce_only=False,
        reason=reason,
    )


def build_exit_order_plan(
    *,
    cycle: ActiveCycleState,
    settings: DcaSettings,
    instrument: InstrumentMeta,
    snapshot: MarketSnapshot,
    exchange: GrvtExchange,
    reason: str,
) -> OrderPlan:
    side = opposite_side(cycle.side)
    return OrderPlan(
        client_order_id=new_client_order_id(),
        symbol=cycle.symbol,
        side=side,
        order_type=validate_order_type(settings.order_type),
        amount=cycle.total_quantity,
        price=planned_price(
            settings=settings,
            side=side,
            reference_price=exit_price(snapshot, cycle.side),
            instrument=instrument,
            exchange=exchange,
        ),
        reduce_only=True,
        reason=reason,
    )


def should_start_new_cycle(state: BotState, settings: DcaSettings) -> bool:
    if state.active_cycle is not None:
        return False
    if settings.max_cycles is not None and state.completed_cycles >= settings.max_cycles:
        return False
    return True
