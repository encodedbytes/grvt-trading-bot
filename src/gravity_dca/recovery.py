from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .exchange import PositionSnapshot
from .state import ActiveCycleState, BotState


QTY_TOLERANCE_RATIO = Decimal("0.0001")
PRICE_TOLERANCE_RATIO = Decimal("0.0001")
MIN_TOLERANCE = Decimal("0.00000001")


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    message: str
    recovered_cycle: ActiveCycleState | None = None


def _within_tolerance(left: Decimal, right: Decimal, ratio: Decimal) -> bool:
    baseline = max(abs(left), abs(right), Decimal("1"))
    tolerance = max(MIN_TOLERANCE, baseline * ratio)
    return abs(left - right) <= tolerance


def _build_recovered_cycle(
    *,
    position: PositionSnapshot,
    when: datetime,
    existing_cycle: ActiveCycleState | None,
) -> ActiveCycleState:
    return ActiveCycleState(
        symbol=position.symbol,
        side=position.side,
        started_at=(existing_cycle.started_at if existing_cycle is not None else when.isoformat()),
        total_quantity=position.size,
        total_cost=position.size * position.average_entry_price,
        average_entry_price=position.average_entry_price,
        leverage=position.leverage,
        margin_type=position.margin_type,
        completed_safety_orders=(
            existing_cycle.completed_safety_orders if existing_cycle is not None else 0
        ),
        last_order_id=(existing_cycle.last_order_id if existing_cycle is not None else None),
        last_client_order_id=(
            existing_cycle.last_client_order_id if existing_cycle is not None else None
        ),
    )


def reconcile_state(
    *,
    state: BotState,
    symbol: str,
    exchange_position: PositionSnapshot | None,
    when: datetime,
) -> RecoveryDecision:
    local_cycle = state.active_cycle
    if local_cycle is not None and local_cycle.symbol != symbol:
        raise ValueError(
            f"Local active cycle symbol mismatch: state_symbol={local_cycle.symbol} config_symbol={symbol}"
        )

    if local_cycle is None and exchange_position is None:
        return RecoveryDecision(
            action="no-op",
            message="No local active cycle and no exchange position.",
        )

    if local_cycle is None and exchange_position is not None:
        return RecoveryDecision(
            action="rebuild-from-exchange",
            message=(
                "Recovered active cycle from exchange position because no local active cycle "
                "was present."
            ),
            recovered_cycle=_build_recovered_cycle(
                position=exchange_position,
                when=when,
                existing_cycle=None,
            ),
        )

    if local_cycle is not None and exchange_position is None:
        return RecoveryDecision(
            action="clear-stale-local",
            message="Cleared stale local active cycle because no exchange position exists.",
        )

    assert local_cycle is not None
    assert exchange_position is not None

    if local_cycle.side != exchange_position.side:
        raise ValueError(
            f"Local and exchange sides do not match: local_side={local_cycle.side} "
            f"exchange_side={exchange_position.side}"
        )
    if not _within_tolerance(local_cycle.total_quantity, exchange_position.size, QTY_TOLERANCE_RATIO):
        raise ValueError(
            f"Local and exchange quantities do not match: local_qty={local_cycle.total_quantity} "
            f"exchange_qty={exchange_position.size}"
        )
    if not _within_tolerance(
        local_cycle.average_entry_price,
        exchange_position.average_entry_price,
        PRICE_TOLERANCE_RATIO,
    ):
        raise ValueError(
            "Local and exchange average entry prices do not match: "
            f"local_avg_entry={local_cycle.average_entry_price} "
            f"exchange_avg_entry={exchange_position.average_entry_price}"
        )

    recovered_cycle = _build_recovered_cycle(
        position=exchange_position,
        when=when,
        existing_cycle=local_cycle,
    )
    return RecoveryDecision(
        action="keep-local",
        message="Local and exchange state match.",
        recovered_cycle=recovered_cycle,
    )
