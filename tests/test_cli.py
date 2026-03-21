from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from gravity_dca import cli
from gravity_dca.config import load_config_text
from gravity_dca.momentum_state import MomentumBotState
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

    def get_candles(self, symbol: str, *, timeframe: str, limit: int):
        from gravity_dca.grvt_models import Candle

        return [
            Candle(
                symbol=symbol,
                open_time=0,
                close_time=299,
                open=Decimal("10"),
                high=Decimal("10.6"),
                low=Decimal("9.9"),
                close=Decimal("10.5"),
                volume=Decimal("1"),
                quote_volume=Decimal("1000"),
                trades=1,
            ),
            Candle(
                symbol=symbol,
                open_time=300,
                close_time=599,
                open=Decimal("10.5"),
                high=Decimal("11.2"),
                low=Decimal("10.4"),
                close=Decimal("11.0"),
                volume=Decimal("1"),
                quote_volume=Decimal("1000"),
                trades=1,
            ),
            Candle(
                symbol=symbol,
                open_time=600,
                close_time=899,
                open=Decimal("11.0"),
                high=Decimal("11.8"),
                low=Decimal("10.9"),
                close=Decimal("11.6"),
                volume=Decimal("1"),
                quote_volume=Decimal("1000"),
                trades=1,
            ),
            Candle(
                symbol=symbol,
                open_time=900,
                close_time=1199,
                open=Decimal("11.6"),
                high=Decimal("12.4"),
                low=Decimal("11.5"),
                close=Decimal("12.1"),
                volume=Decimal("1"),
                quote_volume=Decimal("1000"),
                trades=1,
            ),
            Candle(
                symbol=symbol,
                open_time=1200,
                close_time=1499,
                open=Decimal("12.1"),
                high=Decimal("12.9"),
                low=Decimal("12.0"),
                close=Decimal("12.7"),
                volume=Decimal("1"),
                quote_volume=Decimal("1000"),
                trades=1,
            ),
            Candle(
                symbol=symbol,
                open_time=1500,
                close_time=1799,
                open=Decimal("12.7"),
                high=Decimal("13.8"),
                low=Decimal("12.6"),
                close=Decimal("13.6"),
                volume=Decimal("1"),
                quote_volume=Decimal("1000"),
                trades=1,
            ),
        ]


def momentum_config():
    return load_config_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 3
ema_slow_period = 5
breakout_lookback = 3
adx_period = 3
min_adx = "20"
atr_period = 3
min_atr_percent = "0.1"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
state_file = "/state/momentum.json"

[runtime]
dry_run = true
""",
        resolve_state_paths=False,
    )


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


def test_momentum_status_command_prints_position_and_indicator_summary(monkeypatch, capsys) -> None:
    config = momentum_config()
    state = MomentumBotState()
    state.open_position(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=__import__("datetime").datetime(2026, 3, 20, tzinfo=__import__("datetime").timezone.utc),
        quantity=Decimal("1"),
        price=Decimal("12.0"),
        order_id="0x01",
        client_order_id="123",
        highest_price_since_entry=Decimal("13.6"),
        initial_stop_price=Decimal("11.0"),
        trailing_stop_price=Decimal("11.5"),
        breakout_level=Decimal("12.1"),
        timeframe="5m",
    )

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_exchange", lambda config, logger: DummyExchange())
    monkeypatch.setattr(cli, "load_momentum_state", lambda path: state)
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

    assert "active_position=true" in output
    assert "trailing_stop_price=11.5" in output
    assert "ema_fast=" in output
    assert "recovery_decision=clear-stale-local" in output


def test_momentum_recovery_status_command_prints_recovery_decision(monkeypatch, capsys) -> None:
    config = momentum_config()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_exchange", lambda config, logger: DummyExchange())
    monkeypatch.setattr(cli, "load_momentum_state", lambda path: MomentumBotState())
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
                        "status": False,
                        "thresholds": False,
                        "recovery_status": True,
                        "notify_test": False,
                    },
                )()
            },
        )(),
    )

    cli.main()
    output = capsys.readouterr().out

    assert "decision=no-op" in output
    assert "local_active_position=false" in output


def test_momentum_status_command_prints_entry_diagnostics_when_flat(monkeypatch, capsys) -> None:
    config = momentum_config()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "build_exchange", lambda config, logger: DummyExchange())
    monkeypatch.setattr(cli, "load_momentum_state", lambda path: MomentumBotState())
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

    assert "active_position=false" in output
    assert "entry_decision=enter" in output
    assert "entry_reason=enter" in output
    assert "latest_close=" in output
    assert "breakout_level=" in output
    assert "adx=" in output
