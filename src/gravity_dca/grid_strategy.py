from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import GridSettings
from .grid_state import GridBotState, GridLevelState


@dataclass(frozen=True)
class GridDesiredOrder:
    level_index: int
    side: str
    price: Decimal
    paired_level_index: int | None = None


@dataclass(frozen=True)
class GridStrategySnapshot:
    market_price: Decimal
    levels: list[Decimal]
    active_buy_level_indices: list[int]
    inventory_level_indices: list[int]
    eligible_buy_level_indices: list[int]


@dataclass(frozen=True)
class GridStrategyDecision:
    snapshot: GridStrategySnapshot
    desired_buy_orders: list[GridDesiredOrder]
    desired_sell_orders: list[GridDesiredOrder]
    cancel_buy_level_indices: list[int]


def build_grid_levels(settings: GridSettings) -> list[Decimal]:
    if settings.spacing_mode != "arithmetic":
        raise ValueError("Only arithmetic spacing is supported")
    if settings.grid_levels < 2:
        raise ValueError("grid_levels must be at least 2")
    step = (settings.price_band_high - settings.price_band_low) / Decimal(
        settings.grid_levels - 1
    )
    return [
        settings.price_band_low + (step * Decimal(index))
        for index in range(settings.grid_levels)
    ]


def paired_sell_price(level_index: int, levels: list[Decimal]) -> Decimal | None:
    next_index = level_index + 1
    if next_index >= len(levels):
        return None
    return levels[next_index]


def _state_level_by_index(state: GridBotState) -> dict[int, GridLevelState]:
    return {level.level_index: level for level in state.levels}


def plan_grid_orders(
    *,
    state: GridBotState,
    settings: GridSettings,
    market_price: Decimal,
) -> GridStrategyDecision:
    levels = build_grid_levels(settings)
    state_levels = _state_level_by_index(state)

    active_buy_level_indices = sorted(
        level.level_index
        for level in state.levels
        if level.status == "buy_open"
    )
    inventory_level_indices = sorted(
        level.level_index
        for level in state.levels
        if level.status in {"filled_inventory", "sell_open"}
    )

    candidate_buy_level_indices = [
        index
        for index, price in enumerate(levels[:-1])
        if price < market_price
        and state_levels.get(index, GridLevelState(level_index=index, price=price)).status in {"idle", "buy_open"}
    ]
    inventory_capacity = max(0, settings.max_inventory_levels - len(inventory_level_indices))
    target_buy_capacity = min(settings.max_active_buy_orders, inventory_capacity)
    target_open_buy_indices = sorted(
        candidate_buy_level_indices,
        key=lambda current: levels[current],
        reverse=True,
    )[:target_buy_capacity]
    eligible_buy_level_indices = [
        index
        for index in candidate_buy_level_indices
        if state_levels.get(index, GridLevelState(level_index=index, price=levels[index])).status == "idle"
    ]

    desired_buy_orders = [
        GridDesiredOrder(level_index=index, side="buy", price=levels[index])
        for index in target_open_buy_indices
        if state_levels.get(index, GridLevelState(level_index=index, price=levels[index])).status == "idle"
    ]

    cancel_buy_level_indices = [
        level_index
        for level_index in active_buy_level_indices
        if level_index not in target_open_buy_indices
    ]

    desired_sell_orders: list[GridDesiredOrder] = []
    for level in state.levels:
        if level.status != "filled_inventory":
            continue
        target_price = paired_sell_price(level.level_index, levels)
        if target_price is None:
            continue
        desired_sell_orders.append(
            GridDesiredOrder(
                level_index=level.level_index,
                side="sell",
                price=target_price,
                paired_level_index=level.level_index + 1,
            )
        )

    snapshot = GridStrategySnapshot(
        market_price=market_price,
        levels=levels,
        active_buy_level_indices=active_buy_level_indices,
        inventory_level_indices=inventory_level_indices,
        eligible_buy_level_indices=eligible_buy_level_indices,
    )
    return GridStrategyDecision(
        snapshot=snapshot,
        desired_buy_orders=desired_buy_orders,
        desired_sell_orders=desired_sell_orders,
        cancel_buy_level_indices=cancel_buy_level_indices,
    )
