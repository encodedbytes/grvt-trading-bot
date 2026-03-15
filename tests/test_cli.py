from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from gravity_dca import cli
from gravity_dca.state import ActiveCycleState, BotState


@dataclass
class FakeConfig:
    credentials: object
    dca: object
    runtime: object
    telegram: object


class DummyExchange:
    def get_initial_position_details(self, symbol: str):
        return type(
            "Details",
            (),
            {
                "symbol": symbol,
                "leverage": Decimal("10"),
                "min_leverage": Decimal("1"),
                "max_leverage": Decimal("20"),
                "margin_type": "CROSS",
            },
        )()

    def get_open_position(self, symbol: str):
        return None

    def get_recent_fills(self, symbol: str):
        return []


def test_status_command_prints_compact_summary(monkeypatch, capsys) -> None:
    config = FakeConfig(
        credentials=object(),
        dca=type(
            "Dca",
            (),
                {
                    "symbol": "ETH_USDT_Perp",
                    "side": "buy",
                    "order_type": "market",
                    "state_file": "state.json",
                    "max_safety_orders": 3,
                    "take_profit_percent": Decimal("2"),
                    "stop_loss_percent": Decimal("10"),
                    "price_deviation_percent": Decimal("2.5"),
                "safety_order_step_scale": Decimal("1.2"),
            },
        )(),
        runtime=type("Runtime", (), {"dry_run": True, "log_level": "INFO"})(),
        telegram=object(),
    )
    state = BotState(
        active_cycle=ActiveCycleState(
            symbol="ETH_USDT_Perp",
            side="buy",
            started_at="2026-03-15T00:00:00+00:00",
            total_quantity=Decimal("2.11"),
            total_cost=Decimal("4483.877"),
            average_entry_price=Decimal("2125.060189573459715639810427"),
            leverage=Decimal("10"),
            margin_type="CROSS",
            completed_safety_orders=2,
            last_order_id="0x01",
            last_client_order_id="123",
        ),
        completed_cycles=2,
        last_closed_cycle=None,
    )

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_exchange", lambda config, logger: DummyExchange())
    monkeypatch.setattr(cli, "load_state", lambda path: state)
    monkeypatch.setattr(
        cli,
        "reconcile_state",
        lambda **kwargs: type(
            "Decision",
            (),
            {
                "action": "keep-local",
                "message": "Local and exchange state match.",
                "reconstruction_attempted": False,
                "reconstruction_succeeded": False,
            },
        )(),
    )
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda: type(
            "Parser",
            (),
            {
                "parse_args": lambda self: type(
                    "Args",
                    (),
                    {
                        "config": "config.toml",
                        "once": False,
                        "instrument": None,
                        "position_config": False,
                        "status": True,
                        "thresholds": False,
                        "recovery_status": False,
                        "notify_test": False,
                    },
                )()
            },
        )(),
    )

    cli.main()
    output = capsys.readouterr().out

    assert "symbol=ETH_USDT_Perp" in output
    assert "initial_leverage=10" in output
    assert "active_cycle=true" in output
    assert "take_profit_price=" in output
    assert "recovery_decision=keep-local" in output
