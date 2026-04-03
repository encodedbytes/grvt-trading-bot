from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import AppConfig
from .grid_state import GridBotState
from .momentum_state import MomentumBotState
from .momentum_strategy import MomentumIndicatorSnapshot, fixed_take_profit_price
from .state import BotState
from .strategy import next_safety_trigger_price, stop_loss_price, take_profit_price

UTC = timezone.utc


@dataclass
class RuntimeStatus:
    started_at: str
    last_iteration_started_at: str | None = None
    last_iteration_completed_at: str | None = None
    last_iteration_succeeded_at: str | None = None
    last_iteration_error: str | None = None
    last_iteration_error_at: str | None = None
    risk_reduce_only: bool = False
    risk_reduce_only_reason: str | None = None
    risk_reduce_only_at: str | None = None
    strategy_status: dict[str, Any] | None = None


def new_runtime_status() -> RuntimeStatus:
    return RuntimeStatus(started_at=datetime.now(tz=UTC).isoformat())


def serialize_momentum_indicator_snapshot(
    snapshot: MomentumIndicatorSnapshot | None,
) -> dict[str, str] | None:
    if snapshot is None:
        return None
    return {
        "latest_close": str(snapshot.close_price),
        "breakout_level": str(snapshot.breakout_level),
        "ema_fast": str(snapshot.ema_fast),
        "ema_slow": str(snapshot.ema_slow),
        "adx": str(snapshot.adx),
        "atr": str(snapshot.atr),
        "atr_percent": str(snapshot.atr_percent),
    }


def detect_risk_reduce_only_reason(error: Exception | str) -> str | None:
    text = str(error).strip()
    normalized = text.lower()
    markers = (
        "only risk reducing orders are allowed",
        "only risk-reducing orders are allowed",
        "only risk reducing orders are permitted",
        "only risk-reducing orders are permitted",
    )
    if any(marker in normalized for marker in markers):
        return text
    return None


def serialize_cycle(cycle: Any) -> dict[str, str | int | None]:
    return {
        "started_at": cycle.started_at,
        "side": cycle.side,
        "average_entry_price": str(cycle.average_entry_price),
        "total_quantity": str(cycle.total_quantity),
        "completed_safety_orders": cycle.completed_safety_orders,
        "leverage": str(cycle.leverage) if cycle.leverage is not None else None,
        "margin_type": cycle.margin_type,
        "last_order_id": cycle.last_order_id,
        "last_client_order_id": cycle.last_client_order_id,
    }


def serialize_momentum_position(position: Any) -> dict[str, str | None]:
    return {
        "started_at": position.started_at,
        "side": position.side,
        "average_entry_price": str(position.average_entry_price),
        "total_quantity": str(position.total_quantity),
        "leverage": str(position.leverage) if position.leverage is not None else None,
        "margin_type": position.margin_type,
        "last_order_id": position.last_order_id,
        "last_client_order_id": position.last_client_order_id,
        "highest_price_since_entry": (
            str(position.highest_price_since_entry)
            if position.highest_price_since_entry is not None
            else None
        ),
        "initial_stop_price": (
            str(position.initial_stop_price) if position.initial_stop_price is not None else None
        ),
        "trailing_stop_price": (
            str(position.trailing_stop_price) if position.trailing_stop_price is not None else None
        ),
        "breakout_level": str(position.breakout_level) if position.breakout_level is not None else None,
        "timeframe": position.timeframe,
    }


def serialize_grid_level(level: Any) -> dict[str, str | int | None]:
    return {
        "level_index": level.level_index,
        "price": str(level.price),
        "status": level.status,
        "entry_order_id": level.entry_order_id,
        "entry_client_order_id": level.entry_client_order_id,
        "entry_fill_price": str(level.entry_fill_price) if level.entry_fill_price is not None else None,
        "entry_quantity": str(level.entry_quantity) if level.entry_quantity is not None else None,
        "exit_order_id": level.exit_order_id,
        "exit_client_order_id": level.exit_client_order_id,
        "exit_fill_price": str(level.exit_fill_price) if level.exit_fill_price is not None else None,
        "realized_pnl_estimate": (
            str(level.realized_pnl_estimate) if level.realized_pnl_estimate is not None else None
        ),
        "updated_at": level.updated_at,
    }


def build_status_snapshot(
    config: AppConfig,
    state: BotState | MomentumBotState | GridBotState,
    runtime: RuntimeStatus,
) -> dict[str, Any]:
    if config.strategy_type == "momentum":
        assert isinstance(state, MomentumBotState)
        return _build_momentum_status_snapshot(config, state, runtime)
    if config.strategy_type == "grid":
        assert isinstance(state, GridBotState)
        return _build_grid_status_snapshot(config, state, runtime)
    assert isinstance(state, BotState)
    return _build_dca_status_snapshot(config, state, runtime)


def _build_dca_status_snapshot(
    config: AppConfig,
    state: BotState,
    runtime: RuntimeStatus,
) -> dict[str, Any]:
    settings = config.dca
    assert settings is not None
    active_cycle = state.active_cycle
    lifecycle_state = "idle"
    if active_cycle is not None:
        lifecycle_state = "active"
    elif settings.max_cycles is not None and state.completed_cycles >= settings.max_cycles:
        lifecycle_state = "inactive-max-cycles"

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "symbol": settings.symbol,
        "environment": config.credentials.environment,
        "order_type": settings.order_type,
        "dry_run": config.runtime.dry_run,
        "state_file": str(settings.state_file),
        "lifecycle_state": lifecycle_state,
        "initial_leverage": (
            str(settings.initial_leverage) if settings.initial_leverage is not None else None
        ),
        "margin_type": settings.margin_type,
        "poll_seconds": config.runtime.poll_seconds,
        "bot_api_port": config.runtime.bot_api_port,
        "initial_quote_amount": str(settings.initial_quote_amount),
        "safety_order_quote_amount": str(settings.safety_order_quote_amount),
        "max_safety_orders": settings.max_safety_orders,
        "price_deviation_percent": str(settings.price_deviation_percent),
        "take_profit_percent": str(settings.take_profit_percent),
        "stop_loss_percent": (
            str(settings.stop_loss_percent) if settings.stop_loss_percent is not None else None
        ),
        "safety_order_step_scale": str(settings.safety_order_step_scale),
        "safety_order_volume_scale": str(settings.safety_order_volume_scale),
        "telegram_enabled": config.telegram.enabled,
        "completed_cycles": state.completed_cycles,
        "max_cycles": settings.max_cycles,
        "active_cycle": serialize_cycle(active_cycle) if active_cycle is not None else None,
        "thresholds": {
            "take_profit_price": (
                str(take_profit_price(active_cycle, settings)) if active_cycle is not None else None
            ),
            "stop_loss_price": (
                str(stop_loss_price(active_cycle, settings)) if active_cycle is not None else None
            ),
            "next_safety_trigger_price": (
                str(next_safety_trigger_price(active_cycle, settings))
                if active_cycle is not None
                else None
            ),
        },
        "last_closed_cycle": (
            {
                "closed_at": state.last_closed_cycle.closed_at,
                "exit_reason": state.last_closed_cycle.exit_reason,
                "exit_price": str(state.last_closed_cycle.exit_price),
                "realized_pnl_estimate": str(state.last_closed_cycle.realized_pnl_estimate),
            }
            if state.last_closed_cycle is not None
            else None
        ),
        "runtime_status": {
            "started_at": runtime.started_at,
            "last_iteration_started_at": runtime.last_iteration_started_at,
            "last_iteration_completed_at": runtime.last_iteration_completed_at,
            "last_iteration_succeeded_at": runtime.last_iteration_succeeded_at,
            "last_iteration_error": runtime.last_iteration_error,
            "last_iteration_error_at": runtime.last_iteration_error_at,
            "risk_reduce_only": runtime.risk_reduce_only,
            "risk_reduce_only_reason": runtime.risk_reduce_only_reason,
            "risk_reduce_only_at": runtime.risk_reduce_only_at,
            "strategy_status": runtime.strategy_status,
        },
    }


def _build_momentum_status_snapshot(
    config: AppConfig,
    state: MomentumBotState,
    runtime: RuntimeStatus,
) -> dict[str, Any]:
    settings = config.momentum
    if settings is None:
        raise ValueError("Momentum config is required for momentum status snapshots")
    active_position = state.active_position
    lifecycle_state = "idle"
    if active_position is not None:
        lifecycle_state = "active"
    elif settings.max_cycles is not None and state.completed_cycles >= settings.max_cycles:
        lifecycle_state = "inactive-max-cycles"

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "symbol": settings.symbol,
        "environment": config.credentials.environment,
        "strategy_type": "momentum",
        "order_type": settings.order_type,
        "dry_run": config.runtime.dry_run,
        "state_file": str(settings.state_file),
        "lifecycle_state": lifecycle_state,
        "initial_leverage": (
            str(settings.initial_leverage) if settings.initial_leverage is not None else None
        ),
        "margin_type": settings.margin_type,
        "poll_seconds": config.runtime.poll_seconds,
        "bot_api_port": config.runtime.bot_api_port,
        "quote_amount": str(settings.quote_amount),
        "timeframe": settings.timeframe,
        "ema_fast_period": settings.ema_fast_period,
        "ema_slow_period": settings.ema_slow_period,
        "breakout_lookback": settings.breakout_lookback,
        "adx_period": settings.adx_period,
        "min_adx": str(settings.min_adx),
        "atr_period": settings.atr_period,
        "min_atr_percent": str(settings.min_atr_percent),
        "stop_atr_multiple": str(settings.stop_atr_multiple),
        "trailing_atr_multiple": str(settings.trailing_atr_multiple),
        "use_trend_failure_exit": settings.use_trend_failure_exit,
        "take_profit_percent": (
            str(settings.take_profit_percent) if settings.take_profit_percent is not None else None
        ),
        "telegram_enabled": config.telegram.enabled,
        "completed_cycles": state.completed_cycles,
        "max_cycles": settings.max_cycles,
        "active_position": (
            serialize_momentum_position(active_position) if active_position is not None else None
        ),
        "thresholds": {
            "initial_stop_price": (
                str(active_position.initial_stop_price)
                if active_position is not None and active_position.initial_stop_price is not None
                else None
            ),
            "trailing_stop_price": (
                str(active_position.trailing_stop_price)
                if active_position is not None and active_position.trailing_stop_price is not None
                else None
            ),
            "fixed_take_profit_price": (
                str(fixed_take_profit_price(active_position, settings))
                if active_position is not None and fixed_take_profit_price(active_position, settings) is not None
                else None
            ),
        },
        "last_closed_position": (
            {
                "closed_at": state.last_closed_position.closed_at,
                "exit_reason": state.last_closed_position.exit_reason,
                "exit_price": str(state.last_closed_position.exit_price),
                "realized_pnl_estimate": str(state.last_closed_position.realized_pnl_estimate),
            }
            if state.last_closed_position is not None
            else None
        ),
        "runtime_status": {
            "started_at": runtime.started_at,
            "last_iteration_started_at": runtime.last_iteration_started_at,
            "last_iteration_completed_at": runtime.last_iteration_completed_at,
            "last_iteration_succeeded_at": runtime.last_iteration_succeeded_at,
            "last_iteration_error": runtime.last_iteration_error,
            "last_iteration_error_at": runtime.last_iteration_error_at,
            "risk_reduce_only": runtime.risk_reduce_only,
            "risk_reduce_only_reason": runtime.risk_reduce_only_reason,
            "risk_reduce_only_at": runtime.risk_reduce_only_at,
            "strategy_status": runtime.strategy_status,
        },
    }


def _build_grid_status_snapshot(
    config: AppConfig,
    state: GridBotState,
    runtime: RuntimeStatus,
) -> dict[str, Any]:
    settings = config.grid
    if settings is None:
        raise ValueError("Grid config is required for grid status snapshots")

    active_buy_orders = sum(1 for level in state.levels if level.status == "buy_open")
    active_inventory_levels = sum(
        1 for level in state.levels if level.status in {"filled_inventory", "sell_open"}
    )
    lifecycle_state = "idle"
    if active_buy_orders > 0 or active_inventory_levels > 0:
        lifecycle_state = "active"

    active_grid = None
    if state.grid is not None and (active_buy_orders > 0 or active_inventory_levels > 0):
        active_grid = {
            "started_at": state.started_at,
            "active_buy_orders": active_buy_orders,
            "active_inventory_levels": active_inventory_levels,
            "completed_round_trips": state.completed_round_trips,
            "last_reconciled_at": state.last_reconciled_at,
        }

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "symbol": settings.symbol,
        "environment": config.credentials.environment,
        "strategy_type": "grid",
        "order_type": settings.order_type,
        "dry_run": config.runtime.dry_run,
        "state_file": str(settings.state_file),
        "lifecycle_state": lifecycle_state,
        "initial_leverage": (
            str(settings.initial_leverage) if settings.initial_leverage is not None else None
        ),
        "margin_type": settings.margin_type,
        "poll_seconds": config.runtime.poll_seconds,
        "bot_api_port": config.runtime.bot_api_port,
        "price_band_low": str(settings.price_band_low),
        "price_band_high": str(settings.price_band_high),
        "grid_levels": settings.grid_levels,
        "spacing_mode": settings.spacing_mode,
        "quote_amount_per_level": str(settings.quote_amount_per_level),
        "max_active_buy_orders": settings.max_active_buy_orders,
        "max_inventory_levels": settings.max_inventory_levels,
        "seed_enabled": settings.seed_enabled,
        "reseed_when_flat": settings.reseed_when_flat,
        "telegram_enabled": config.telegram.enabled,
        "completed_cycles": state.completed_round_trips,
        "completed_round_trips": state.completed_round_trips,
        "max_cycles": None,
        "active_grid": active_grid,
        "levels": [serialize_grid_level(level) for level in state.levels],
        "thresholds": {
            "take_profit_price": None,
            "stop_loss_price": None,
            "next_safety_trigger_price": None,
            "initial_stop_price": None,
            "trailing_stop_price": None,
            "fixed_take_profit_price": None,
        },
        "last_closed_position": None,
        "runtime_status": {
            "started_at": runtime.started_at,
            "last_iteration_started_at": runtime.last_iteration_started_at,
            "last_iteration_completed_at": runtime.last_iteration_completed_at,
            "last_iteration_succeeded_at": runtime.last_iteration_succeeded_at,
            "last_iteration_error": runtime.last_iteration_error,
            "last_iteration_error_at": runtime.last_iteration_error_at,
            "risk_reduce_only": runtime.risk_reduce_only,
            "risk_reduce_only_reason": runtime.risk_reduce_only_reason,
            "risk_reduce_only_at": runtime.risk_reduce_only_at,
            "strategy_status": runtime.strategy_status,
        },
    }
