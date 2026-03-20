from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import AppConfig
from .momentum_state import MomentumBotState
from .momentum_strategy import fixed_take_profit_price
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


def new_runtime_status() -> RuntimeStatus:
    return RuntimeStatus(started_at=datetime.now(tz=UTC).isoformat())


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


def build_status_snapshot(
    config: AppConfig,
    state: BotState | MomentumBotState,
    runtime: RuntimeStatus,
) -> dict[str, Any]:
    if config.strategy_type == "momentum":
        return _build_momentum_status_snapshot(config, state, runtime)
    return _build_dca_status_snapshot(config, state, runtime)


def _build_dca_status_snapshot(
    config: AppConfig,
    state: BotState,
    runtime: RuntimeStatus,
) -> dict[str, Any]:
    active_cycle = state.active_cycle
    lifecycle_state = "idle"
    if active_cycle is not None:
        lifecycle_state = "active"
    elif config.dca.max_cycles is not None and state.completed_cycles >= config.dca.max_cycles:
        lifecycle_state = "inactive-max-cycles"

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "symbol": config.dca.symbol,
        "environment": config.credentials.environment,
        "order_type": config.dca.order_type,
        "dry_run": config.runtime.dry_run,
        "state_file": str(config.dca.state_file),
        "lifecycle_state": lifecycle_state,
        "initial_leverage": (
            str(config.dca.initial_leverage) if config.dca.initial_leverage is not None else None
        ),
        "margin_type": config.dca.margin_type,
        "poll_seconds": config.runtime.poll_seconds,
        "bot_api_port": config.runtime.bot_api_port,
        "initial_quote_amount": str(config.dca.initial_quote_amount),
        "safety_order_quote_amount": str(config.dca.safety_order_quote_amount),
        "max_safety_orders": config.dca.max_safety_orders,
        "price_deviation_percent": str(config.dca.price_deviation_percent),
        "take_profit_percent": str(config.dca.take_profit_percent),
        "stop_loss_percent": (
            str(config.dca.stop_loss_percent) if config.dca.stop_loss_percent is not None else None
        ),
        "safety_order_step_scale": str(config.dca.safety_order_step_scale),
        "safety_order_volume_scale": str(config.dca.safety_order_volume_scale),
        "telegram_enabled": config.telegram.enabled,
        "completed_cycles": state.completed_cycles,
        "max_cycles": config.dca.max_cycles,
        "active_cycle": serialize_cycle(active_cycle) if active_cycle is not None else None,
        "thresholds": {
            "take_profit_price": (
                str(take_profit_price(active_cycle, config.dca)) if active_cycle is not None else None
            ),
            "stop_loss_price": (
                str(stop_loss_price(active_cycle, config.dca)) if active_cycle is not None else None
            ),
            "next_safety_trigger_price": (
                str(next_safety_trigger_price(active_cycle, config.dca))
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
        },
    }
