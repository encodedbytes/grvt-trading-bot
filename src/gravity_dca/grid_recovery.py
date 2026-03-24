from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .config import GridSettings
from .exchange import AccountFill, PositionSnapshot
from .grid_state import GridBotState, GridLevelState
from .grid_strategy import build_grid_levels, paired_sell_price
from .recovery_common import PRICE_TOLERANCE_RATIO, QTY_TOLERANCE_RATIO, within_tolerance


@dataclass(frozen=True)
class GridOpenOrderSnapshot:
    symbol: str
    side: str
    price: Decimal
    size: Decimal
    order_id: str | None = None
    client_order_id: str | None = None
    reduce_only: bool = False


@dataclass(frozen=True)
class GridRecoveryDecision:
    action: str
    message: str
    recovered_state: GridBotState


def _level_for_price(settings: GridSettings, price: Decimal) -> int:
    for index, level_price in enumerate(build_grid_levels(settings)):
        if within_tolerance(level_price, price, PRICE_TOLERANCE_RATIO):
            return index
    raise ValueError(f"Open order price does not map to a configured grid level: price={price}")


def _source_level_for_sell_order(
    recovered: GridBotState,
    settings: GridSettings,
    price: Decimal,
) -> int:
    levels = build_grid_levels(settings)
    candidates: list[int] = []
    for level in recovered.levels:
        target_price = paired_sell_price(level.level_index, levels)
        if target_price is None:
            continue
        if within_tolerance(target_price, price, PRICE_TOLERANCE_RATIO):
            candidates.append(level.level_index)
    if len(candidates) != 1:
        raise ValueError(
            f"Open sell order does not map cleanly to a grid inventory level: price={price}"
        )
    return candidates[0]


def _ensure_initialized(state: GridBotState, settings: GridSettings, when: datetime) -> GridBotState:
    recovered = deepcopy(state)
    expected_levels = build_grid_levels(settings)
    if recovered.grid is None:
        recovered.initialize_grid(
            symbol=settings.symbol,
            side=settings.side,
            price_band_low=settings.price_band_low,
            price_band_high=settings.price_band_high,
            grid_levels=settings.grid_levels,
            spacing_mode=settings.spacing_mode,
            quote_amount_per_level=settings.quote_amount_per_level,
            prices=expected_levels,
            when=when,
        )
        return recovered
    if (
        recovered.grid.symbol != settings.symbol
        or recovered.grid.side != settings.side
        or recovered.grid.grid_levels != settings.grid_levels
    ):
        raise ValueError("Local grid state does not match configured symbol/side/grid_levels")
    if len(recovered.levels) != settings.grid_levels:
        raise ValueError("Local grid state does not match configured level count")
    for index, level in enumerate(recovered.levels):
        if level.level_index != index:
            raise ValueError("Local grid state level indices are inconsistent")
        if not within_tolerance(level.price, expected_levels[index], PRICE_TOLERANCE_RATIO):
            raise ValueError("Local grid state prices do not match configured grid levels")
    return recovered


def _matching_fill(level: GridLevelState, fills: list[AccountFill], *, side: str) -> AccountFill | None:
    candidates: list[AccountFill] = []
    for fill in fills:
        if fill.side != side:
            continue
        if side == "buy":
            if level.entry_order_id and fill.order_id == level.entry_order_id:
                candidates.append(fill)
                continue
            if level.entry_client_order_id and fill.client_order_id == level.entry_client_order_id:
                candidates.append(fill)
                continue
        else:
            if level.exit_order_id and fill.order_id == level.exit_order_id:
                candidates.append(fill)
                continue
            if level.exit_client_order_id and fill.client_order_id == level.exit_client_order_id:
                candidates.append(fill)
                continue
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.event_time)[-1]


def _aggregate_fill_candidates(candidates: list[AccountFill]) -> AccountFill | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda item: item.event_time)
    total_size = sum((fill.size for fill in ordered), Decimal("0"))
    if total_size <= 0:
        return ordered[-1]
    total_notional = sum((fill.size * fill.price for fill in ordered), Decimal("0"))
    latest = ordered[-1]
    return AccountFill(
        event_time=latest.event_time,
        symbol=latest.symbol,
        side=latest.side,
        size=total_size,
        price=(total_notional / total_size),
        order_id=latest.order_id,
        client_order_id=latest.client_order_id,
        raw=latest.raw,
    )


def _matching_fill_aggregate(
    level: GridLevelState,
    fills: list[AccountFill],
    *,
    side: str,
) -> AccountFill | None:
    candidates: list[AccountFill] = []
    for fill in fills:
        if fill.side != side:
            continue
        if side == "buy":
            if level.entry_order_id and fill.order_id == level.entry_order_id:
                candidates.append(fill)
                continue
            if level.entry_client_order_id and fill.client_order_id == level.entry_client_order_id:
                candidates.append(fill)
                continue
        else:
            if level.exit_order_id and fill.order_id == level.exit_order_id:
                candidates.append(fill)
                continue
            if level.exit_client_order_id and fill.client_order_id == level.exit_client_order_id:
                candidates.append(fill)
                continue
    return _aggregate_fill_candidates(candidates)


def _matching_fill_by_level(
    settings: GridSettings,
    fills: list[AccountFill],
    *,
    side: str,
    level_index: int,
) -> AccountFill | None:
    levels = build_grid_levels(settings)
    candidates: list[AccountFill] = []
    for fill in fills:
        if fill.side != side or fill.symbol != settings.symbol:
            continue
        if side == "buy":
            lower_bound = levels[level_index]
            upper_bound = paired_sell_price(level_index, levels)
            if upper_bound is None:
                continue
            if fill.price < lower_bound:
                continue
            if fill.price >= upper_bound and not within_tolerance(
                fill.price, upper_bound, PRICE_TOLERANCE_RATIO
            ):
                continue
            fill_level_index = level_index
        else:
            try:
                fill_level_index = _level_for_price(settings, fill.price)
            except ValueError:
                continue
        if fill_level_index == level_index:
            candidates.append(fill)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.event_time)[-1]


def _matching_fill_by_level_aggregate(
    settings: GridSettings,
    fills: list[AccountFill],
    *,
    side: str,
    level_index: int,
) -> AccountFill | None:
    levels = build_grid_levels(settings)
    candidates: list[AccountFill] = []
    for fill in fills:
        if fill.side != side or fill.symbol != settings.symbol:
            continue
        if side == "buy":
            lower_bound = levels[level_index]
            upper_bound = paired_sell_price(level_index, levels)
            if upper_bound is None:
                continue
            if fill.price < lower_bound:
                continue
            if fill.price >= upper_bound and not within_tolerance(
                fill.price, upper_bound, PRICE_TOLERANCE_RATIO
            ):
                continue
            fill_level_index = level_index
        else:
            try:
                fill_level_index = _level_for_price(settings, fill.price)
            except ValueError:
                continue
        if fill_level_index == level_index:
            candidates.append(fill)
    return _aggregate_fill_candidates(candidates)


def _clear_stale_buy(level: GridLevelState) -> None:
    level.status = "idle"
    level.entry_order_id = None
    level.entry_client_order_id = None
    level.updated_at = None


def _clear_stale_sell(level: GridLevelState) -> None:
    level.status = "filled_inventory"
    level.exit_order_id = None
    level.exit_client_order_id = None
    level.updated_at = None


def _refresh_counts(recovered: GridBotState) -> None:
    recovered.active_inventory_levels = sum(
        1 for level in recovered.levels if level.status in {"filled_inventory", "sell_open"}
    )


def reconcile_grid_state(
    *,
    state: GridBotState,
    settings: GridSettings,
    open_orders: list[GridOpenOrderSnapshot],
    exchange_position: PositionSnapshot | None,
    fills: list[AccountFill],
    when: datetime,
) -> GridRecoveryDecision:
    local_grid_missing = state.grid is None
    recovered = _ensure_initialized(state, settings, when)
    changes: list[str] = []
    if local_grid_missing:
        changes.append("initialized")

    order_levels: dict[tuple[str, int], GridOpenOrderSnapshot] = {}
    for order in open_orders:
        if order.symbol != settings.symbol:
            continue
        if order.side == "buy":
            level_index = _level_for_price(settings, order.price)
        elif order.side == "sell":
            level_index = _source_level_for_sell_order(recovered, settings, order.price)
        else:
            raise ValueError(f"Unsupported open order side for grid reconciliation: {order.side}")
        key = (order.side, level_index)
        if key in order_levels:
            raise ValueError(
                f"Multiple open orders map to the same grid slot: side={order.side} level_index={level_index}"
            )
        order_levels[key] = order

    for level in recovered.levels:
        if level.status == "buy_open" and ("buy", level.level_index) not in order_levels:
            fill = _matching_fill_aggregate(level, fills, side="buy")
            if fill is not None:
                recovered.mark_buy_filled(
                    level_index=level.level_index,
                    when=when,
                    fill_price=fill.price,
                    quantity=fill.size,
                    order_id=fill.order_id,
                    client_order_id=fill.client_order_id,
                )
                changes.append(f"buy-filled:{level.level_index}")
            else:
                _clear_stale_buy(level)
                changes.append(f"stale-buy-cleared:{level.level_index}")
        elif level.status == "sell_open" and ("sell", level.level_index) not in order_levels:
            fill = _matching_fill(level, fills, side="sell")
            if fill is not None:
                recovered.mark_sell_filled(
                    level_index=level.level_index,
                    when=when,
                    fill_price=fill.price,
                    order_id=fill.order_id,
                    client_order_id=fill.client_order_id,
                )
                changes.append(f"sell-filled:{level.level_index}")
            else:
                _clear_stale_sell(level)
                changes.append(f"stale-sell-cleared:{level.level_index}")

    for (side, level_index), order in order_levels.items():
        level = recovered.level(level_index)
        if side == "buy":
            if level.status in {"filled_inventory", "sell_open"}:
                raise ValueError(
                    f"Open buy order conflicts with inventory-bearing level: level_index={level_index}"
                )
            level.status = "buy_open"
            level.entry_order_id = order.order_id
            level.entry_client_order_id = order.client_order_id
            level.updated_at = when.isoformat()
        elif side == "sell":
            if level.status == "buy_open":
                fill = _matching_fill_aggregate(level, fills, side="buy")
                if fill is None:
                    raise ValueError(
                        f"Open sell order has no matching inventory for level: level_index={level_index}"
                    )
                recovered.mark_buy_filled(
                    level_index=level_index,
                    when=when,
                    fill_price=fill.price,
                    quantity=fill.size,
                    order_id=fill.order_id,
                    client_order_id=fill.client_order_id,
                )
                changes.append(f"buy-filled:{level_index}")
                level = recovered.level(level_index)
            if level.status == "idle":
                fill = _matching_fill_by_level_aggregate(
                    settings,
                    fills,
                    side="buy",
                    level_index=level_index,
                )
                if fill is None:
                    raise ValueError(
                        f"Open sell order has no matching inventory for level: level_index={level_index}"
                    )
                recovered.mark_buy_filled(
                    level_index=level_index,
                    when=when,
                    fill_price=fill.price,
                    quantity=fill.size,
                    order_id=fill.order_id,
                    client_order_id=fill.client_order_id,
                )
                changes.append(f"buy-filled:{level_index}")
                level = recovered.level(level_index)
            level.status = "sell_open"
            level.exit_order_id = order.order_id
            level.exit_client_order_id = order.client_order_id
            level.updated_at = when.isoformat()
        else:
            raise ValueError(f"Unsupported open order side for grid reconciliation: {side}")

    _refresh_counts(recovered)

    inventory_quantity = sum(
        level.entry_quantity or Decimal("0")
        for level in recovered.levels
        if level.status in {"filled_inventory", "sell_open"}
    )
    if exchange_position is None:
        if inventory_quantity > 0:
            raise ValueError("Grid local inventory exists but no exchange position is open")
    else:
        if exchange_position.side != settings.side:
            raise ValueError(
                f"Exchange position side does not match grid strategy side: exchange_side={exchange_position.side} strategy_side={settings.side}"
            )
        if not within_tolerance(inventory_quantity, exchange_position.size, QTY_TOLERANCE_RATIO):
            raise ValueError(
                f"Grid inventory quantity does not match exchange position: local_qty={inventory_quantity} exchange_qty={exchange_position.size}"
            )

    recovered.mark_reconciled(when)

    if recovered != state:
        if local_grid_missing:
            if any(change.startswith("buy-filled:") or change.startswith("sell-filled:") for change in changes):
                action = "rebuild-from-open-orders-and-fills"
                message = "Rebuilt grid state from open orders and exchange fills."
            elif open_orders:
                action = "rebuild-from-open-orders"
                message = "Rebuilt grid state from live open orders."
            else:
                action = "initialize-from-config"
                message = "Initialized grid state from the configured grid definition."
        else:
            action = "reconciled"
            message = "Grid state reconciled from open orders and fills." if changes else "Grid state refreshed."
        return GridRecoveryDecision(
            action=action,
            message=message,
            recovered_state=recovered,
        )
    return GridRecoveryDecision(
        action="keep-local",
        message="Local grid state already matches open orders and fills.",
        recovered_state=recovered,
    )
