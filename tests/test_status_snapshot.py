from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from gravity_dca.config import load_config_text
from gravity_dca.grid_state import GridBotState
from gravity_dca.momentum_state import MomentumBotState
from gravity_dca.state import ActiveCycleState, BotState
from gravity_dca.status_snapshot import (
    RuntimeStatus,
    build_status_snapshot,
    detect_risk_reduce_only_reason,
)


def test_build_status_snapshot_includes_runtime_and_thresholds() -> None:
    config = load_config_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "BTC_USDT_Perp"
side = "buy"
initial_quote_amount = "1000"
safety_order_quote_amount = "1250"
max_safety_orders = 3
price_deviation_percent = "2.0"
take_profit_percent = "1.4"
stop_loss_percent = "7.5"
state_file = "/state/btc.json"

[runtime]
dry_run = false
poll_seconds = 30
""",
        config_path=Path("/app/config.toml"),
        resolve_state_paths=False,
    )
    state = BotState(
        active_cycle=ActiveCycleState(
            symbol="BTC_USDT_Perp",
            side="buy",
            started_at="2026-03-16T00:00:00+00:00",
            total_quantity=Decimal("0.016"),
            total_cost=Decimal("1197.36"),
            average_entry_price=Decimal("74835"),
            completed_safety_orders=1,
            last_order_id="0x01",
            last_client_order_id="cid-1",
        ),
        completed_cycles=2,
    )
    runtime = RuntimeStatus(
        started_at="2026-03-16T00:00:00+00:00",
        last_iteration_started_at="2026-03-16T00:05:00+00:00",
        last_iteration_completed_at="2026-03-16T00:05:02+00:00",
        last_iteration_succeeded_at="2026-03-16T00:05:02+00:00",
    )

    snapshot = build_status_snapshot(config, state, runtime)

    assert snapshot["symbol"] == "BTC_USDT_Perp"
    assert snapshot["lifecycle_state"] == "active"
    assert snapshot["bot_api_port"] == 8787
    assert snapshot["active_cycle"]["completed_safety_orders"] == 1
    assert snapshot["thresholds"]["take_profit_price"] is not None
    assert snapshot["runtime_status"]["last_iteration_succeeded_at"] == "2026-03-16T00:05:02+00:00"


def test_build_status_snapshot_includes_risk_reduce_only_runtime_state() -> None:
    config = load_config_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "BTC_USDT_Perp"
side = "buy"
initial_quote_amount = "1000"
safety_order_quote_amount = "1250"
max_safety_orders = 3
price_deviation_percent = "2.0"
take_profit_percent = "1.4"
state_file = "/state/btc.json"

[runtime]
dry_run = false
poll_seconds = 30
""",
        config_path=Path("/app/config.toml"),
        resolve_state_paths=False,
    )

    snapshot = build_status_snapshot(
        config,
        BotState(),
        RuntimeStatus(
            started_at="2026-03-16T00:00:00+00:00",
            last_iteration_error="ValueError: only risk reducing orders are allowed",
            last_iteration_error_at="2026-03-16T00:06:00+00:00",
            risk_reduce_only=True,
            risk_reduce_only_reason="ValueError: only risk reducing orders are allowed",
            risk_reduce_only_at="2026-03-16T00:06:00+00:00",
        ),
    )

    assert snapshot["runtime_status"]["risk_reduce_only"] is True
    assert (
        snapshot["runtime_status"]["risk_reduce_only_reason"]
        == "ValueError: only risk reducing orders are allowed"
    )
    assert snapshot["runtime_status"]["risk_reduce_only_at"] == "2026-03-16T00:06:00+00:00"


def test_detect_risk_reduce_only_reason_matches_grvt_message() -> None:
    reason = detect_risk_reduce_only_reason(
        "GRVT order was not fillable: status=REJECTED reject_reason=Only risk-reducing orders are permitted"
    )

    assert reason is not None
    assert "risk-reducing orders are permitted" in reason


def test_build_status_snapshot_supports_momentum_runtime_state() -> None:
    config = load_config_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
state_file = "/state/eth-momentum.json"

[runtime]
dry_run = false
poll_seconds = 30
""",
        config_path=Path("/app/config.toml"),
        resolve_state_paths=False,
    )
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=__import__("datetime").datetime(2026, 3, 16, tzinfo=__import__("datetime").timezone.utc),
        quantity=Decimal("1.25"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="cid-1",
        highest_price_since_entry=Decimal("2050"),
        initial_stop_price=Decimal("1970"),
        trailing_stop_price=Decimal("2010"),
        breakout_level=Decimal("1995"),
        timeframe="5m",
    )

    snapshot = build_status_snapshot(
        config,
        state,
        RuntimeStatus(started_at="2026-03-16T00:00:00+00:00"),
    )

    assert snapshot["strategy_type"] == "momentum"
    assert snapshot["symbol"] == "ETH_USDT_Perp"
    assert snapshot["lifecycle_state"] == "active"
    assert snapshot["active_position"]["highest_price_since_entry"] == "2050"
    assert snapshot["thresholds"]["initial_stop_price"] == "1970"


def test_build_status_snapshot_preserves_momentum_strategy_status() -> None:
    config = load_config_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
state_file = "/state/eth-momentum.json"

[runtime]
dry_run = false
poll_seconds = 30
""",
        config_path=Path("/app/config.toml"),
        resolve_state_paths=False,
    )

    snapshot = build_status_snapshot(
        config,
        MomentumBotState(),
        RuntimeStatus(
            started_at="2026-03-16T00:00:00+00:00",
            strategy_status={
                "strategy_type": "momentum",
                "mode": "entry",
                "entry_decision": "skip",
                "entry_reason": "breakout-not-confirmed",
                "indicator_snapshot": {
                    "latest_close": "2152.74",
                    "breakout_level": "2159.72",
                    "ema_fast": "2145.10",
                    "ema_slow": "2141.32",
                    "adx": "21.48",
                    "atr": "7.52",
                    "atr_percent": "0.34",
                },
                "initial_stop_price": None,
                "trailing_stop_price": None,
            },
        ),
    )

    assert snapshot["runtime_status"]["strategy_status"]["entry_reason"] == "breakout-not-confirmed"
    assert snapshot["runtime_status"]["strategy_status"]["indicator_snapshot"]["atr_percent"] == "0.34"


def test_build_status_snapshot_supports_grid_runtime_state() -> None:
    config = load_config_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[strategy]
type = "grid"

[grid]
symbol = "ETH_USDT_Perp"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 5
quote_amount_per_level = "100"
max_active_buy_orders = 2
max_inventory_levels = 2
seed_enabled = true
state_file = "/state/grid.json"

[runtime]
dry_run = false
poll_seconds = 30
""",
        config_path=Path("/app/config.toml"),
        resolve_state_paths=False,
    )
    state = GridBotState()
    state.initialize_grid(
        symbol="ETH_USDT_Perp",
        side="buy",
        price_band_low=Decimal("1800"),
        price_band_high=Decimal("2200"),
        grid_levels=5,
        spacing_mode="arithmetic",
        quote_amount_per_level=Decimal("100"),
        prices=[
            Decimal("1800"),
            Decimal("1900"),
            Decimal("2000"),
            Decimal("2100"),
            Decimal("2200"),
        ],
        when=__import__("datetime").datetime(2026, 3, 20, tzinfo=__import__("datetime").timezone.utc),
    )
    state.mark_buy_filled(
        level_index=1,
        when=__import__("datetime").datetime(2026, 3, 20, tzinfo=__import__("datetime").timezone.utc),
        fill_price=Decimal("1900"),
        quantity=Decimal("0.05"),
    )

    snapshot = build_status_snapshot(
        config,
        state,
        RuntimeStatus(started_at="2026-03-20T00:00:00+00:00"),
    )

    assert snapshot["strategy_type"] == "grid"
    assert snapshot["lifecycle_state"] == "active"
    assert snapshot["price_band_low"] == "1800"
    assert snapshot["seed_enabled"] is True
    assert snapshot["active_grid"]["active_inventory_levels"] == 1
    assert snapshot["levels"][1]["status"] == "filled_inventory"
