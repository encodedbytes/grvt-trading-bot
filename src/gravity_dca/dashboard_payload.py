from __future__ import annotations

from typing import Any


def empty_thresholds() -> dict[str, str | None]:
    return {
        "take_profit_price": None,
        "stop_loss_price": None,
        "next_safety_trigger_price": None,
        "initial_stop_price": None,
        "trailing_stop_price": None,
        "fixed_take_profit_price": None,
    }


def normalize_status_payload(status_payload: dict[str, Any]) -> dict[str, Any]:
    strategy_type = status_payload.get("strategy_type", "dca")
    thresholds = dict(empty_thresholds())
    thresholds.update(status_payload.get("thresholds", {}))
    runtime_status = status_payload.get("runtime_status", {})
    if strategy_type == "momentum":
        thresholds["take_profit_price"] = (
            thresholds.get("take_profit_price") or thresholds.get("fixed_take_profit_price")
        )
        thresholds["stop_loss_price"] = (
            thresholds.get("stop_loss_price")
            or thresholds.get("trailing_stop_price")
            or thresholds.get("initial_stop_price")
        )
        return {
            "strategy_type": "momentum",
            "state_file": status_payload["state_file"],
            "symbol": status_payload["symbol"],
            "environment": status_payload["environment"],
            "order_type": status_payload["order_type"],
            "dry_run": status_payload["dry_run"],
            "initial_leverage": status_payload["initial_leverage"],
            "margin_type": status_payload["margin_type"],
            "poll_seconds": status_payload["poll_seconds"],
            "bot_api_port": status_payload["bot_api_port"],
            "initial_quote_amount": status_payload.get("quote_amount"),
            "safety_order_quote_amount": None,
            "max_safety_orders": None,
            "price_deviation_percent": None,
            "take_profit_percent": status_payload.get("take_profit_percent"),
            "stop_loss_percent": None,
            "safety_order_step_scale": None,
            "safety_order_volume_scale": None,
            "telegram_enabled": status_payload["telegram_enabled"],
            "completed_cycles": status_payload["completed_cycles"],
            "max_cycles": status_payload["max_cycles"],
            "active_cycle": status_payload.get("active_position"),
            "thresholds": thresholds,
            "last_closed_cycle": status_payload.get("last_closed_position"),
            "timeframe": status_payload.get("timeframe"),
            "ema_fast_period": status_payload.get("ema_fast_period"),
            "ema_slow_period": status_payload.get("ema_slow_period"),
            "breakout_lookback": status_payload.get("breakout_lookback"),
            "adx_period": status_payload.get("adx_period"),
            "min_adx": status_payload.get("min_adx"),
            "atr_period": status_payload.get("atr_period"),
            "min_atr_percent": status_payload.get("min_atr_percent"),
            "stop_atr_multiple": status_payload.get("stop_atr_multiple"),
            "trailing_atr_multiple": status_payload.get("trailing_atr_multiple"),
            "use_trend_failure_exit": status_payload.get("use_trend_failure_exit"),
            "strategy_status": runtime_status.get("strategy_status"),
        }
    return {
        "strategy_type": "dca",
        "state_file": status_payload["state_file"],
        "symbol": status_payload["symbol"],
        "environment": status_payload["environment"],
        "order_type": status_payload["order_type"],
        "dry_run": status_payload["dry_run"],
        "initial_leverage": status_payload["initial_leverage"],
        "margin_type": status_payload["margin_type"],
        "poll_seconds": status_payload["poll_seconds"],
        "bot_api_port": status_payload["bot_api_port"],
        "initial_quote_amount": status_payload["initial_quote_amount"],
        "safety_order_quote_amount": status_payload["safety_order_quote_amount"],
        "max_safety_orders": status_payload["max_safety_orders"],
        "price_deviation_percent": status_payload["price_deviation_percent"],
        "take_profit_percent": status_payload["take_profit_percent"],
        "stop_loss_percent": status_payload["stop_loss_percent"],
        "safety_order_step_scale": status_payload["safety_order_step_scale"],
        "safety_order_volume_scale": status_payload["safety_order_volume_scale"],
        "telegram_enabled": status_payload["telegram_enabled"],
        "completed_cycles": status_payload["completed_cycles"],
        "max_cycles": status_payload["max_cycles"],
        "active_cycle": status_payload["active_cycle"],
        "thresholds": thresholds,
        "last_closed_cycle": status_payload["last_closed_cycle"],
        "strategy_status": runtime_status.get("strategy_status"),
    }


def build_container_summary(
    *,
    container_name: str,
    container_id: str,
    container_state: str,
    lifecycle_state: str,
    image: str,
    config_file: str,
    normalized_status: dict[str, Any],
    risk_reduce_only: bool,
    risk_reduce_only_reason: str | None,
    recent_error: str | None,
    last_log_line: str | None,
) -> dict[str, Any]:
    return {
        "container_name": container_name,
        "container_id": container_id,
        "container_state": container_state,
        "lifecycle_state": lifecycle_state,
        "image": image,
        "config_file": config_file,
        **normalized_status,
        "risk_reduce_only": risk_reduce_only,
        "risk_reduce_only_reason": risk_reduce_only_reason,
        "recent_error": recent_error,
        "last_log_line": last_log_line,
    }


def build_error_summary(
    *,
    container_name: str,
    container_state: str,
    image: str,
    config_file: str,
    state_file: str,
    recent_error: str | None,
    last_log_line: str | None,
) -> dict[str, Any]:
    return {
        "container_name": container_name,
        "container_state": container_state,
        "lifecycle_state": "error",
        "image": image,
        "config_file": config_file,
        "state_file": state_file,
        "symbol": container_name,
        "environment": "",
        "order_type": "",
        "dry_run": False,
        "initial_leverage": None,
        "margin_type": None,
        "poll_seconds": None,
        "bot_api_port": None,
        "strategy_type": "unknown",
        "strategy_status": None,
        "completed_cycles": 0,
        "max_cycles": None,
        "active_cycle": None,
        "thresholds": empty_thresholds(),
        "last_closed_cycle": None,
        "risk_reduce_only": False,
        "risk_reduce_only_reason": None,
        "recent_error": recent_error,
        "last_log_line": last_log_line,
    }
