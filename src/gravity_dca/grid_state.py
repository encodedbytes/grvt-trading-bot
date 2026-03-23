from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path


UTC = timezone.utc


@dataclass
class GridLevelState:
    level_index: int
    price: Decimal
    status: str = "idle"
    entry_order_id: str | None = None
    entry_client_order_id: str | None = None
    entry_fill_price: Decimal | None = None
    entry_quantity: Decimal | None = None
    exit_order_id: str | None = None
    exit_client_order_id: str | None = None
    exit_fill_price: Decimal | None = None
    realized_pnl_estimate: Decimal | None = None
    updated_at: str | None = None


@dataclass
class GridDefinitionState:
    symbol: str
    side: str
    price_band_low: Decimal
    price_band_high: Decimal
    grid_levels: int
    spacing_mode: str
    quote_amount_per_level: Decimal


@dataclass
class GridBotState:
    grid: GridDefinitionState | None = None
    levels: list[GridLevelState] = field(default_factory=list)
    started_at: str | None = None
    completed_round_trips: int = 0
    active_inventory_levels: int = 0
    last_error: str | None = None
    last_reconciled_at: str | None = None

    def initialize_grid(
        self,
        *,
        symbol: str,
        side: str,
        price_band_low: Decimal,
        price_band_high: Decimal,
        grid_levels: int,
        spacing_mode: str,
        quote_amount_per_level: Decimal,
        prices: list[Decimal],
        when: datetime,
    ) -> None:
        if len(prices) != grid_levels:
            raise ValueError("prices length must match grid_levels")
        self.grid = GridDefinitionState(
            symbol=symbol,
            side=side,
            price_band_low=price_band_low,
            price_band_high=price_band_high,
            grid_levels=grid_levels,
            spacing_mode=spacing_mode,
            quote_amount_per_level=quote_amount_per_level,
        )
        self.levels = [
            GridLevelState(level_index=index, price=price)
            for index, price in enumerate(prices)
        ]
        self.started_at = when.astimezone(UTC).isoformat()

    def level(self, level_index: int) -> GridLevelState:
        for level in self.levels:
            if level.level_index == level_index:
                return level
        raise ValueError(f"Unknown grid level: {level_index}")

    def open_buy_order(
        self,
        *,
        level_index: int,
        when: datetime,
        order_id: str | None,
        client_order_id: str,
    ) -> None:
        level = self.level(level_index)
        level.status = "buy_open"
        level.entry_order_id = order_id
        level.entry_client_order_id = client_order_id
        level.entry_fill_price = None
        level.entry_quantity = None
        level.exit_order_id = None
        level.exit_client_order_id = None
        level.exit_fill_price = None
        level.realized_pnl_estimate = None
        level.updated_at = when.astimezone(UTC).isoformat()

    def mark_buy_filled(
        self,
        *,
        level_index: int,
        when: datetime,
        fill_price: Decimal,
        quantity: Decimal,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> None:
        level = self.level(level_index)
        if level.status == "sell_open":
            raise ValueError("Cannot mark buy filled while exit order is open")
        level.status = "filled_inventory"
        level.entry_fill_price = fill_price
        level.entry_quantity = quantity
        if order_id is not None:
            level.entry_order_id = order_id
        if client_order_id is not None:
            level.entry_client_order_id = client_order_id
        level.updated_at = when.astimezone(UTC).isoformat()
        self.active_inventory_levels = sum(
            1 for existing in self.levels if existing.status in {"filled_inventory", "sell_open"}
        )

    def open_sell_order(
        self,
        *,
        level_index: int,
        when: datetime,
        order_id: str | None,
        client_order_id: str,
    ) -> None:
        level = self.level(level_index)
        if level.entry_fill_price is None or level.entry_quantity is None:
            raise ValueError("Cannot open sell order without filled inventory")
        level.status = "sell_open"
        level.exit_order_id = order_id
        level.exit_client_order_id = client_order_id
        level.updated_at = when.astimezone(UTC).isoformat()
        self.active_inventory_levels = sum(
            1 for existing in self.levels if existing.status in {"filled_inventory", "sell_open"}
        )

    def mark_sell_filled(
        self,
        *,
        level_index: int,
        when: datetime,
        fill_price: Decimal,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> None:
        level = self.level(level_index)
        if level.entry_fill_price is None or level.entry_quantity is None:
            raise ValueError("Cannot close grid level without entry inventory")
        level.status = "idle"
        level.exit_fill_price = fill_price
        if order_id is not None:
            level.exit_order_id = order_id
        if client_order_id is not None:
            level.exit_client_order_id = client_order_id
        level.realized_pnl_estimate = (
            fill_price - level.entry_fill_price
        ) * level.entry_quantity
        level.entry_order_id = None
        level.entry_client_order_id = None
        level.entry_fill_price = None
        level.entry_quantity = None
        level.exit_order_id = None
        level.exit_client_order_id = None
        level.updated_at = when.astimezone(UTC).isoformat()
        self.completed_round_trips += 1
        self.active_inventory_levels = sum(
            1 for existing in self.levels if existing.status in {"filled_inventory", "sell_open"}
        )

    def set_last_error(self, message: str | None) -> None:
        self.last_error = message

    def mark_reconciled(self, when: datetime) -> None:
        self.last_reconciled_at = when.astimezone(UTC).isoformat()


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


def _decode_grid(payload: dict | None) -> GridDefinitionState | None:
    if payload is None:
        return None
    return GridDefinitionState(
        symbol=str(payload["symbol"]),
        side=str(payload["side"]),
        price_band_low=Decimal(str(payload["price_band_low"])),
        price_band_high=Decimal(str(payload["price_band_high"])),
        grid_levels=int(payload["grid_levels"]),
        spacing_mode=str(payload["spacing_mode"]),
        quote_amount_per_level=Decimal(str(payload["quote_amount_per_level"])),
    )


def _decode_level(payload: dict) -> GridLevelState:
    return GridLevelState(
        level_index=int(payload["level_index"]),
        price=Decimal(str(payload["price"])),
        status=str(payload.get("status", "idle")),
        entry_order_id=str(payload["entry_order_id"]) if payload.get("entry_order_id") else None,
        entry_client_order_id=(
            str(payload["entry_client_order_id"]) if payload.get("entry_client_order_id") else None
        ),
        entry_fill_price=_optional_decimal(payload, "entry_fill_price"),
        entry_quantity=_optional_decimal(payload, "entry_quantity"),
        exit_order_id=str(payload["exit_order_id"]) if payload.get("exit_order_id") else None,
        exit_client_order_id=(
            str(payload["exit_client_order_id"]) if payload.get("exit_client_order_id") else None
        ),
        exit_fill_price=_optional_decimal(payload, "exit_fill_price"),
        realized_pnl_estimate=_optional_decimal(payload, "realized_pnl_estimate"),
        updated_at=str(payload["updated_at"]) if payload.get("updated_at") else None,
    )


def load_grid_state(path: Path) -> GridBotState:
    if not path.exists():
        return GridBotState()
    return load_grid_state_text(path.read_text())


def load_grid_state_text(raw_text: str) -> GridBotState:
    payload = json.loads(raw_text)
    return GridBotState(
        grid=_decode_grid(payload.get("grid")),
        levels=[_decode_level(level) for level in payload.get("levels", [])],
        started_at=str(payload["started_at"]) if payload.get("started_at") else None,
        completed_round_trips=int(payload.get("completed_round_trips", 0)),
        active_inventory_levels=int(payload.get("active_inventory_levels", 0)),
        last_error=str(payload["last_error"]) if payload.get("last_error") else None,
        last_reconciled_at=(
            str(payload["last_reconciled_at"]) if payload.get("last_reconciled_at") else None
        ),
    )


def save_grid_state(path: Path, state: GridBotState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _encode_value(asdict(state))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
