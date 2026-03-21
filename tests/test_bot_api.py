from __future__ import annotations

import logging
from pathlib import Path

from gravity_dca.bot_api import build_shared_status
from gravity_dca.config import load_config_text


def config():
    return load_config_text(
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


def test_shared_status_marks_and_clears_risk_reduce_only() -> None:
    shared = build_shared_status(config(), logging.getLogger("gravity_dca"))

    shared.mark_iteration_failed(
        "2026-03-19T00:00:00+00:00",
        ValueError("Only risk-reducing orders are permitted"),
    )

    snapshot = shared.snapshot()
    assert snapshot["runtime_status"]["risk_reduce_only"] is True
    assert (
        snapshot["runtime_status"]["risk_reduce_only_reason"]
        == "Only risk-reducing orders are permitted"
    )

    shared.mark_iteration_succeeded("2026-03-19T00:01:00+00:00")

    snapshot = shared.snapshot()
    assert snapshot["runtime_status"]["risk_reduce_only"] is False
    assert snapshot["runtime_status"]["risk_reduce_only_reason"] is None


def test_shared_status_preserves_strategy_status() -> None:
    shared = build_shared_status(config(), logging.getLogger("gravity_dca"))

    shared.set_strategy_status(
        {
            "strategy_type": "momentum",
            "mode": "entry",
            "entry_decision": "skip",
            "entry_reason": "breakout-not-confirmed",
        }
    )

    snapshot = shared.snapshot()

    assert snapshot["runtime_status"]["strategy_status"]["entry_reason"] == "breakout-not-confirmed"
