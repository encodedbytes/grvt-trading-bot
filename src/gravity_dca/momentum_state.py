from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path


UTC = timezone.utc


@dataclass
class ActiveMomentumState:
    symbol: str
    side: str
    started_at: str
    total_quantity: Decimal
    total_cost: Decimal
    average_entry_price: Decimal
    leverage: Decimal | None = None
    margin_type: str | None = None
    last_order_id: str | None = None
    last_client_order_id: str | None = None
    highest_price_since_entry: Decimal | None = None
    initial_stop_price: Decimal | None = None
    trailing_stop_price: Decimal | None = None
    breakout_level: Decimal | None = None
    timeframe: str | None = None


@dataclass
class ClosedMomentumState:
    side: str
    closed_at: str
    exit_reason: str
    average_entry_price: Decimal
    exit_price: Decimal
    total_quantity: Decimal
    realized_pnl_estimate: Decimal
    leverage: Decimal | None = None
    margin_type: str | None = None


@dataclass
class MomentumBotState:
    active_position: ActiveMomentumState | None = None
    completed_cycles: int = 0
    last_closed_position: ClosedMomentumState | None = None

    def open_position(
        self,
        *,
        symbol: str,
        side: str,
        when: datetime,
        quantity: Decimal,
        price: Decimal,
        order_id: str | None,
        client_order_id: str,
        leverage: Decimal | None = None,
        margin_type: str | None = None,
        highest_price_since_entry: Decimal | None = None,
        initial_stop_price: Decimal | None = None,
        trailing_stop_price: Decimal | None = None,
        breakout_level: Decimal | None = None,
        timeframe: str | None = None,
    ) -> None:
        total_cost = quantity * price
        self.active_position = ActiveMomentumState(
            symbol=symbol,
            side=side,
            started_at=when.astimezone(UTC).isoformat(),
            total_quantity=quantity,
            total_cost=total_cost,
            average_entry_price=price,
            leverage=leverage,
            margin_type=margin_type,
            last_order_id=order_id,
            last_client_order_id=client_order_id,
            highest_price_since_entry=highest_price_since_entry or price,
            initial_stop_price=initial_stop_price,
            trailing_stop_price=trailing_stop_price,
            breakout_level=breakout_level,
            timeframe=timeframe,
        )

    def update_active_position(
        self,
        *,
        highest_price_since_entry: Decimal | None = None,
        initial_stop_price: Decimal | None = None,
        trailing_stop_price: Decimal | None = None,
        breakout_level: Decimal | None = None,
        last_order_id: str | None = None,
        last_client_order_id: str | None = None,
    ) -> None:
        if self.active_position is None:
            raise ValueError("No active momentum position to update")
        position = self.active_position
        if highest_price_since_entry is not None:
            if (
                position.highest_price_since_entry is None
                or highest_price_since_entry > position.highest_price_since_entry
            ):
                position.highest_price_since_entry = highest_price_since_entry
        if initial_stop_price is not None:
            position.initial_stop_price = initial_stop_price
        if trailing_stop_price is not None:
            position.trailing_stop_price = trailing_stop_price
        if breakout_level is not None:
            position.breakout_level = breakout_level
        if last_order_id is not None:
            position.last_order_id = last_order_id
        if last_client_order_id is not None:
            position.last_client_order_id = last_client_order_id

    def close_position(
        self,
        *,
        when: datetime,
        exit_reason: str,
        exit_price: Decimal,
    ) -> None:
        if self.active_position is None:
            raise ValueError("No active momentum position to close")
        position = self.active_position
        if position.side == "buy":
            pnl = (exit_price - position.average_entry_price) * position.total_quantity
        else:
            pnl = (position.average_entry_price - exit_price) * position.total_quantity
        self.last_closed_position = ClosedMomentumState(
            side=position.side,
            closed_at=when.astimezone(UTC).isoformat(),
            exit_reason=exit_reason,
            average_entry_price=position.average_entry_price,
            exit_price=exit_price,
            total_quantity=position.total_quantity,
            realized_pnl_estimate=pnl,
            leverage=position.leverage,
            margin_type=position.margin_type,
        )
        self.completed_cycles += 1
        self.active_position = None

    def replace_active_position(self, position: ActiveMomentumState | None) -> None:
        self.active_position = position


def _encode_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _encode_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_encode_value(inner) for inner in value]
    return value


def _optional_decimal(payload: dict, key: str) -> Decimal | None:
    return Decimal(str(payload[key])) if payload.get(key) is not None else None


def _decode_active_position(payload: dict | None) -> ActiveMomentumState | None:
    if payload is None:
        return None
    return ActiveMomentumState(
        symbol=str(payload["symbol"]),
        side=str(payload["side"]),
        started_at=str(payload["started_at"]),
        total_quantity=Decimal(str(payload["total_quantity"])),
        total_cost=Decimal(str(payload["total_cost"])),
        average_entry_price=Decimal(str(payload["average_entry_price"])),
        leverage=_optional_decimal(payload, "leverage"),
        margin_type=str(payload["margin_type"]) if payload.get("margin_type") else None,
        last_order_id=str(payload["last_order_id"]) if payload.get("last_order_id") else None,
        last_client_order_id=(
            str(payload["last_client_order_id"]) if payload.get("last_client_order_id") else None
        ),
        highest_price_since_entry=_optional_decimal(payload, "highest_price_since_entry"),
        initial_stop_price=_optional_decimal(payload, "initial_stop_price"),
        trailing_stop_price=_optional_decimal(payload, "trailing_stop_price"),
        breakout_level=_optional_decimal(payload, "breakout_level"),
        timeframe=str(payload["timeframe"]) if payload.get("timeframe") else None,
    )


def _decode_closed_position(payload: dict | None) -> ClosedMomentumState | None:
    if payload is None:
        return None
    return ClosedMomentumState(
        side=str(payload["side"]),
        closed_at=str(payload["closed_at"]),
        exit_reason=str(payload["exit_reason"]),
        average_entry_price=Decimal(str(payload["average_entry_price"])),
        exit_price=Decimal(str(payload["exit_price"])),
        total_quantity=Decimal(str(payload["total_quantity"])),
        realized_pnl_estimate=Decimal(str(payload["realized_pnl_estimate"])),
        leverage=_optional_decimal(payload, "leverage"),
        margin_type=str(payload["margin_type"]) if payload.get("margin_type") else None,
    )


def load_momentum_state(path: Path) -> MomentumBotState:
    if not path.exists():
        return MomentumBotState()
    return load_momentum_state_text(path.read_text())


def load_momentum_state_text(raw_text: str) -> MomentumBotState:
    payload = json.loads(raw_text)
    return MomentumBotState(
        active_position=_decode_active_position(payload.get("active_position")),
        completed_cycles=int(payload.get("completed_cycles", 0)),
        last_closed_position=_decode_closed_position(payload.get("last_closed_position")),
    )


def save_momentum_state(path: Path, state: MomentumBotState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _encode_value(asdict(state))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
