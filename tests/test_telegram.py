from __future__ import annotations

from dataclasses import replace
import logging
from datetime import datetime, timezone
from decimal import Decimal

from gravity_dca.bot import DcaBot
from gravity_dca.bot_api import build_shared_status
from gravity_dca.config import AppConfig, DcaSettings, GrvtCredentials, RuntimeSettings, TelegramSettings
from gravity_dca.exchange import InstrumentMeta, MarketSnapshot, TransientExchangeError
from gravity_dca.state import BotState


UTC = timezone.utc
from gravity_dca.telegram import (
    NullNotifier,
    TelegramNotifier,
    build_notifier,
    format_bot_inactive_message,
    format_fill_message,
    format_limit_timeout_message,
    format_recovery_message,
    format_startup_message,
)


def config(telegram: TelegramSettings | None = None) -> AppConfig:
    return AppConfig(
        credentials=GrvtCredentials(
            api_key="key",
            private_key="pk",
            trading_account_id="123",
            environment="prod",
        ),
        dca=DcaSettings(
            symbol="ETH_USDT_Perp",
            side="buy",
            initial_quote_amount=Decimal("25"),
            safety_order_quote_amount=Decimal("25"),
            max_safety_orders=2,
            price_deviation_percent=Decimal("2.0"),
            take_profit_percent=Decimal("1.0"),
        ),
        runtime=RuntimeSettings(dry_run=True),
        telegram=telegram or TelegramSettings(),
    )


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str):
        self.messages.append(text)
        return type("Result", (), {"delivered": True, "detail": "sent"})()

    def send_test_message(self, config: AppConfig):
        self.messages.append("test")
        return type("Result", (), {"delivered": True, "detail": "sent"})()


class FakeExchange:
    def round_amount(self, amount: Decimal, base_decimals: int) -> Decimal:
        quantum = Decimal("1").scaleb(-base_decimals)
        return amount.quantize(quantum)

    def align_amount_to_market(self, amount: Decimal, instrument: InstrumentMeta) -> Decimal:
        rounded = self.round_amount(amount, instrument.base_decimals)
        return (rounded // instrument.min_size) * instrument.min_size

    def round_price(self, price: Decimal, tick_size: Decimal) -> Decimal:
        return (price // tick_size) * tick_size

    def get_open_position(self, symbol: str):
        return None

    def get_recent_fills(self, symbol: str):
        return []

    def ensure_position_config(self, **kwargs):
        return []

    def get_instrument(self, symbol: str) -> InstrumentMeta:
        return InstrumentMeta(
            symbol=symbol,
            tick_size=Decimal("0.01"),
            min_size=Decimal("0.01"),
            min_notional=Decimal("20"),
            base_decimals=9,
        )

    def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=symbol,
            bid=Decimal("2000.00"),
            ask=Decimal("2000.10"),
            mid=Decimal("2000.05"),
            last=Decimal("2000.08"),
        )


class TransientRecoveryExchange(FakeExchange):
    def get_open_position(self, symbol: str):
        raise TransientExchangeError("temporary ssl failure")


def test_build_notifier_returns_null_when_disabled() -> None:
    notifier = build_notifier(config(), logging.getLogger("gravity_dca"))
    assert isinstance(notifier, NullNotifier)


def test_telegram_notifier_test_message_reports_http_errors(monkeypatch) -> None:
    class FakeResponse:
        ok = False
        status_code = 401
        text = "unauthorized"

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("gravity_dca.telegram.requests.post", fake_post)
    notifier = TelegramNotifier(
        TelegramSettings(enabled=True, bot_token="token", chat_id="chat"),
        logging.getLogger("gravity_dca"),
    )

    result = notifier.send_test_message(config(TelegramSettings(enabled=True, bot_token="token", chat_id="chat")))

    assert result.delivered is False
    assert result.detail == "http-401"


def test_message_formatters_include_key_fields() -> None:
    startup = format_startup_message(config())
    recovery = format_recovery_message(
        "ETH_USDT_Perp",
        type(
            "Decision",
            (),
            {
                "action": "keep-local",
                "message": "Local and exchange state match.",
                "reconstruction_message": None,
                "recovered_cycle": None,
            },
        )(),
    )
    fill = format_fill_message(
        symbol="ETH_USDT_Perp",
        label="initial entry filled",
        side="buy",
        quantity=Decimal("0.5"),
        price=Decimal("2000"),
        order_type="market",
    )
    timeout = format_limit_timeout_message("ETH_USDT_Perp", "initial-entry", "123")
    inactive = format_bot_inactive_message(
        symbol="ETH_USDT_Perp",
        reason="max-cycles-reached",
        completed_cycles=5,
        max_cycles=5,
    )

    assert "GRVT bot started" in startup
    assert "decision=keep-local" in recovery
    assert "qty=0.5" in fill
    assert "client_order_id=123" in timeout
    assert "action=no-new-cycles" in inactive


def test_bot_sends_startup_and_recovery_notifications_in_dry_run() -> None:
    fake_notifier = FakeNotifier()
    bot = DcaBot.__new__(DcaBot)
    bot._config = config()
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange()
    bot._notifier = fake_notifier
    bot._shared_status = build_shared_status(bot._config, bot._logger)
    bot._startup_notified = False
    bot._recovery_notified = False

    result = bot.run_once()

    assert result is True
    assert any("GRVT bot started" in message for message in fake_notifier.messages)
    assert any("recovery" in message for message in fake_notifier.messages)


def test_bot_uses_local_state_when_recovery_has_transient_exchange_error(monkeypatch) -> None:
    fake_notifier = FakeNotifier()
    bot = DcaBot.__new__(DcaBot)
    bot._config = config(
        TelegramSettings(
            enabled=True,
            bot_token="token",
            chat_id="chat",
        )
    )
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = TransientRecoveryExchange()
    bot._notifier = fake_notifier
    bot._shared_status = build_shared_status(bot._config, bot._logger)
    bot._startup_notified = False
    bot._recovery_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    state = BotState()
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=datetime(2026, 3, 14, 12, 0, tzinfo=UTC),
        quantity=Decimal("0.50"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="123",
    )

    monkeypatch.setattr("gravity_dca.bot.load_state", lambda path: state)
    monkeypatch.setattr("gravity_dca.bot.save_state", lambda path, state: None)

    result = bot.run_once()

    assert result is False
    assert any("GRVT bot started" in message for message in fake_notifier.messages)
    assert not any("bot error" in message for message in fake_notifier.messages)


def test_bot_notifies_when_max_cycles_reached_inactive() -> None:
    fake_notifier = FakeNotifier()
    cfg = replace(config(), dca=replace(config().dca, max_cycles=2))
    bot = DcaBot.__new__(DcaBot)
    bot._config = cfg
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange()
    bot._notifier = fake_notifier
    bot._startup_notified = False
    bot._recovery_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0
    bot._inactive_reason_notified = None

    state = BotState(active_cycle=None, completed_cycles=2, last_closed_cycle=None)

    bot._maybe_notify_inactive_state(state)
    bot._maybe_notify_inactive_state(state)

    inactive_messages = [
        message for message in fake_notifier.messages if "bot inactive" in message
    ]
    assert len(inactive_messages) == 1
    assert "reason=max-cycles-reached" in inactive_messages[0]


def test_iteration_failure_notifications_are_deduplicated_within_cooldown() -> None:
    fake_notifier = FakeNotifier()
    bot = DcaBot.__new__(DcaBot)
    bot._config = config(
        TelegramSettings(
            enabled=True,
            bot_token="token",
            chat_id="chat",
            error_notification_cooldown_seconds=300,
        )
    )
    bot._logger = logging.getLogger("gravity_dca")
    bot._exchange = FakeExchange()
    bot._notifier = fake_notifier
    bot._startup_notified = False
    bot._recovery_notified = False
    bot._last_iteration_error_key = None
    bot._last_iteration_error_at = 0.0

    error = RuntimeError("temporary ssl failure")
    bot._notify_iteration_failure(error)
    bot._notify_iteration_failure(error)

    assert len(fake_notifier.messages) == 1
    assert "bot error" in fake_notifier.messages[0]
