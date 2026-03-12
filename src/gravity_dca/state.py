from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path


UTC = timezone.utc


@dataclass
class ActiveCycleState:
    symbol: str
    side: str
    started_at: str
    total_quantity: Decimal
    total_cost: Decimal
    average_entry_price: Decimal
    completed_safety_orders: int = 0
    last_order_id: str | None = None
    last_client_order_id: str | None = None


@dataclass
class ClosedCycleState:
    side: str
    closed_at: str
    exit_reason: str
    average_entry_price: Decimal
    exit_price: Decimal
    total_quantity: Decimal
    realized_pnl_estimate: Decimal


@dataclass
class BotState:
    active_cycle: ActiveCycleState | None = None
    completed_cycles: int = 0
    last_closed_cycle: ClosedCycleState | None = None

    def start_cycle(
        self,
        *,
        symbol: str,
        side: str,
        when: datetime,
        quantity: Decimal,
        price: Decimal,
        order_id: str | None,
        client_order_id: str,
    ) -> None:
        total_cost = quantity * price
        self.active_cycle = ActiveCycleState(
            symbol=symbol,
            side=side,
            started_at=when.astimezone(UTC).isoformat(),
            total_quantity=quantity,
            total_cost=total_cost,
            average_entry_price=price,
            completed_safety_orders=0,
            last_order_id=order_id,
            last_client_order_id=client_order_id,
        )

    def add_safety_fill(
        self,
        *,
        quantity: Decimal,
        price: Decimal,
        order_id: str | None,
        client_order_id: str,
    ) -> None:
        if self.active_cycle is None:
            raise ValueError("No active cycle to update")
        cycle = self.active_cycle
        cycle.total_quantity += quantity
        cycle.total_cost += quantity * price
        cycle.average_entry_price = cycle.total_cost / cycle.total_quantity
        cycle.completed_safety_orders += 1
        cycle.last_order_id = order_id
        cycle.last_client_order_id = client_order_id

    def close_cycle(
        self,
        *,
        when: datetime,
        exit_reason: str,
        exit_price: Decimal,
    ) -> None:
        if self.active_cycle is None:
            raise ValueError("No active cycle to close")
        cycle = self.active_cycle
        if cycle.side == "buy":
            pnl = (exit_price - cycle.average_entry_price) * cycle.total_quantity
        else:
            pnl = (cycle.average_entry_price - exit_price) * cycle.total_quantity
        self.last_closed_cycle = ClosedCycleState(
            side=cycle.side,
            closed_at=when.astimezone(UTC).isoformat(),
            exit_reason=exit_reason,
            average_entry_price=cycle.average_entry_price,
            exit_price=exit_price,
            total_quantity=cycle.total_quantity,
            realized_pnl_estimate=pnl,
        )
        self.completed_cycles += 1
        self.active_cycle = None


def _encode_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _encode_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_encode_value(inner) for inner in value]
    return value


def _decode_active_cycle(payload: dict | None) -> ActiveCycleState | None:
    if payload is None:
        return None
    return ActiveCycleState(
        symbol=str(payload["symbol"]),
        side=str(payload["side"]),
        started_at=str(payload["started_at"]),
        total_quantity=Decimal(str(payload["total_quantity"])),
        total_cost=Decimal(str(payload["total_cost"])),
        average_entry_price=Decimal(str(payload["average_entry_price"])),
        completed_safety_orders=int(payload.get("completed_safety_orders", 0)),
        last_order_id=str(payload["last_order_id"]) if payload.get("last_order_id") else None,
        last_client_order_id=(
            str(payload["last_client_order_id"]) if payload.get("last_client_order_id") else None
        ),
    )


def _decode_closed_cycle(payload: dict | None) -> ClosedCycleState | None:
    if payload is None:
        return None
    return ClosedCycleState(
        side=str(payload["side"]),
        closed_at=str(payload["closed_at"]),
        exit_reason=str(payload["exit_reason"]),
        average_entry_price=Decimal(str(payload["average_entry_price"])),
        exit_price=Decimal(str(payload["exit_price"])),
        total_quantity=Decimal(str(payload["total_quantity"])),
        realized_pnl_estimate=Decimal(str(payload["realized_pnl_estimate"])),
    )


def load_state(path: Path) -> BotState:
    if not path.exists():
        return BotState()
    payload = json.loads(path.read_text())
    return BotState(
        active_cycle=_decode_active_cycle(payload.get("active_cycle")),
        completed_cycles=int(payload.get("completed_cycles", 0)),
        last_closed_cycle=_decode_closed_cycle(payload.get("last_closed_cycle")),
    )


def save_state(path: Path, state: BotState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _encode_value(asdict(state))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
