from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from gravity_dca.config import load_config_text
from gravity_dca.state import ActiveCycleState, BotState
from gravity_dca.status_snapshot import RuntimeStatus, build_status_snapshot


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
