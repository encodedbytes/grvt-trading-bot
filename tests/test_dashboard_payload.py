from __future__ import annotations

from gravity_dca.dashboard_payload import (
    build_container_summary,
    build_error_summary,
    empty_thresholds,
    normalize_status_payload,
)


def test_normalize_status_payload_maps_momentum_fields() -> None:
    normalized = normalize_status_payload(
        {
            "strategy_type": "momentum",
            "state_file": "/state/momentum.json",
            "symbol": "ETH_USDT_Perp",
            "environment": "prod",
            "order_type": "market",
            "dry_run": False,
            "initial_leverage": "3",
            "margin_type": "CROSS",
            "poll_seconds": 30,
            "bot_api_port": 8788,
            "quote_amount": "150",
            "take_profit_percent": None,
            "telegram_enabled": True,
            "completed_cycles": 0,
            "max_cycles": 1,
            "active_position": {"side": "buy"},
            "last_closed_position": None,
            "timeframe": "5m",
            "ema_fast_period": 12,
            "ema_slow_period": 26,
            "breakout_lookback": 10,
            "adx_period": 14,
            "min_adx": "18",
            "atr_period": 14,
            "min_atr_percent": "0.25",
            "stop_atr_multiple": "1.3",
            "trailing_atr_multiple": "2.0",
            "use_trend_failure_exit": True,
            "thresholds": {
                "initial_stop_price": "2138",
                "trailing_stop_price": "2147",
                "fixed_take_profit_price": None,
            },
            "runtime_status": {
                "strategy_status": {"mode": "entry", "entry_reason": "breakout-not-confirmed"}
            },
        }
    )

    assert normalized["strategy_type"] == "momentum"
    assert normalized["initial_quote_amount"] == "150"
    assert normalized["active_trade_kind"] == "position"
    assert normalized["last_closed_trade_kind"] == "position"
    assert normalized["active_trade"] == {"side": "buy"}
    assert normalized["active_cycle"] == {"side": "buy"}
    assert normalized["thresholds"]["stop_loss_price"] == "2147"
    assert normalized["strategy_status"]["entry_reason"] == "breakout-not-confirmed"


def test_build_error_summary_uses_empty_thresholds() -> None:
    summary = build_error_summary(
        container_name="grvt-momentum-eth",
        container_state="running",
        image="gravity-dca-bot:local",
        config_file="/app/config.toml",
        state_file="/state/momentum.json",
        recent_error="boom",
        last_log_line="last line",
    )

    assert summary["lifecycle_state"] == "error"
    assert summary["thresholds"] == empty_thresholds()
    assert summary["recent_error"] == "boom"


def test_build_container_summary_attaches_runtime_fields() -> None:
    summary = build_container_summary(
        container_name="grvt-dca-btc",
        container_id="abc123",
        container_state="running",
        lifecycle_state="active",
        image="gravity-dca-bot:local",
        config_file="/app/config.toml",
        normalized_status={
            "symbol": "BTC_USDT_Perp",
            "active_trade_kind": "cycle",
            "last_closed_trade_kind": "cycle",
            "active_trade": None,
            "active_cycle": None,
            "last_closed_trade": None,
            "last_closed_cycle": None,
        },
        risk_reduce_only=True,
        risk_reduce_only_reason="Only risk-reducing orders are permitted",
        recent_error="ValueError: boom",
        last_log_line="line",
        detail_source="bot-api",
        signal_source=None,
        signal_status="unavailable",
        signal_note="No live signals.",
    )

    assert summary["container_id"] == "abc123"
    assert summary["symbol"] == "BTC_USDT_Perp"
    assert summary["active_trade_kind"] == "cycle"
    assert summary["detail_source"] == "bot-api"
    assert summary["signal_status"] == "unavailable"
    assert summary["risk_reduce_only"] is True
    assert summary["recent_error"] == "ValueError: boom"


def test_normalize_status_payload_maps_grid_fields() -> None:
    normalized = normalize_status_payload(
        {
            "strategy_type": "grid",
            "state_file": "/state/grid.json",
            "symbol": "ETH_USDT_Perp",
            "environment": "prod",
            "order_type": "limit",
            "dry_run": False,
            "initial_leverage": "3",
            "margin_type": "CROSS",
            "poll_seconds": 30,
            "bot_api_port": 8789,
            "price_band_low": "1800",
            "price_band_high": "2200",
            "grid_levels": 5,
            "spacing_mode": "arithmetic",
            "quote_amount_per_level": "100",
            "max_active_buy_orders": 2,
            "max_inventory_levels": 2,
            "seed_enabled": True,
            "telegram_enabled": True,
            "completed_cycles": 1,
            "completed_round_trips": 1,
            "max_cycles": None,
            "active_grid": {"active_buy_orders": 1, "active_inventory_levels": 1},
            "levels": [{"level_index": 1, "price": "1900", "status": "buy_open"}],
            "runtime_status": {"strategy_status": None},
        }
    )

    assert normalized["strategy_type"] == "grid"
    assert normalized["active_trade_kind"] == "grid"
    assert normalized["active_trade"]["active_buy_orders"] == 1
    assert normalized["price_band_low"] == "1800"
    assert normalized["seed_enabled"] is True
    assert normalized["levels"][0]["status"] == "buy_open"
