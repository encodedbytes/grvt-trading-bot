from __future__ import annotations

from dataclasses import dataclass
import logging

import requests

from .config import AppConfig, TelegramSettings
from .recovery import RecoveryDecision
from .state import ActiveCycleState


@dataclass(frozen=True)
class NotificationResult:
    delivered: bool
    detail: str


class Notifier:
    def send(self, text: str) -> NotificationResult:
        raise NotImplementedError

    def send_test_message(self, config: AppConfig) -> NotificationResult:
        raise NotImplementedError


class NullNotifier(Notifier):
    def send(self, text: str) -> NotificationResult:
        return NotificationResult(delivered=False, detail="telegram-disabled")

    def send_test_message(self, config: AppConfig) -> NotificationResult:
        return NotificationResult(delivered=False, detail="telegram-disabled")


class TelegramNotifier(Notifier):
    def __init__(self, settings: TelegramSettings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

    def _api_url(self) -> str:
        if not self._settings.bot_token:
            raise ValueError("Telegram bot_token is required when telegram is enabled")
        return f"https://api.telegram.org/bot{self._settings.bot_token}/sendMessage"

    def send(self, text: str) -> NotificationResult:
        try:
            response = requests.post(
                self._api_url(),
                json={
                    "chat_id": self._settings.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if not response.ok:
                detail = f"http-{response.status_code}"
                self._logger.warning("Telegram notification failed: %s body=%s", detail, response.text[:300])
                return NotificationResult(delivered=False, detail=detail)
            payload = response.json()
            if payload.get("ok") is not True:
                detail = f"api-error-{payload!r}"
                self._logger.warning("Telegram notification failed: %s", detail)
                return NotificationResult(delivered=False, detail=detail)
            return NotificationResult(delivered=True, detail="sent")
        except Exception as exc:
            self._logger.warning("Telegram notification failed: %s", exc)
            return NotificationResult(delivered=False, detail=str(exc))

    def send_test_message(self, config: AppConfig) -> NotificationResult:
        return self.send(
            "\n".join(
                [
                    "GRVT bot Telegram test",
                    f"symbol={config.dca.symbol}",
                    f"environment={config.credentials.environment}",
                    f"dry_run={config.runtime.dry_run}",
                ]
            )
        )


def build_notifier(config: AppConfig, logger: logging.Logger) -> Notifier:
    if not config.telegram.enabled:
        return NullNotifier()
    if not config.telegram.bot_token or not config.telegram.chat_id:
        raise ValueError("telegram.bot_token and telegram.chat_id are required when enabled=true")
    return TelegramNotifier(config.telegram, logger)


def format_startup_message(config: AppConfig) -> str:
    return "\n".join(
        [
            "GRVT bot started",
            f"symbol={config.dca.symbol}",
            f"side={config.dca.side}",
            f"environment={config.credentials.environment}",
            f"dry_run={config.runtime.dry_run}",
            f"order_type={config.dca.order_type}",
        ]
    )


def format_recovery_message(symbol: str, decision: RecoveryDecision) -> str:
    lines = [
        f"{symbol} recovery",
        f"decision={decision.action}",
        f"message={decision.message}",
    ]
    if decision.reconstruction_message is not None:
        lines.append(f"reconstruction={decision.reconstruction_message}")
    if decision.recovered_cycle is not None:
        lines.append(
            "completed_safety_orders="
            f"{decision.recovered_cycle.completed_safety_orders}"
        )
    return "\n".join(lines)


def format_cycle_summary(prefix: str, cycle: ActiveCycleState) -> str:
    return "\n".join(
        [
            prefix,
            f"symbol={cycle.symbol}",
            f"side={cycle.side}",
            f"qty={cycle.total_quantity}",
            f"avg_entry={cycle.average_entry_price}",
            f"completed_safety_orders={cycle.completed_safety_orders}",
        ]
    )


def format_fill_message(
    *,
    symbol: str,
    label: str,
    side: str,
    quantity,
    price,
    order_type: str,
    extra_lines: list[str] | None = None,
) -> str:
    lines = [
        f"{symbol} {label}",
        f"side={side}",
        f"qty={quantity}",
        f"price={price}",
        f"order_type={order_type}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines)


def format_limit_timeout_message(symbol: str, reason: str, client_order_id: str) -> str:
    return "\n".join(
        [
            f"{symbol} limit order timeout",
            f"reason={reason}",
            f"client_order_id={client_order_id}",
            "action=canceled",
        ]
    )


def format_position_config_change(symbol: str, change: str) -> str:
    return "\n".join([f"{symbol} position config updated", change])


def format_iteration_failure(symbol: str, error: Exception) -> str:
    return "\n".join([f"{symbol} bot error", f"error={type(error).__name__}", str(error)])


def format_bot_inactive_message(
    *,
    symbol: str,
    reason: str,
    completed_cycles: int,
    max_cycles: int | None,
) -> str:
    lines = [
        f"{symbol} bot inactive",
        f"reason={reason}",
        f"completed_cycles={completed_cycles}",
    ]
    if max_cycles is not None:
        lines.append(f"max_cycles={max_cycles}")
    lines.append("action=no-new-cycles")
    return "\n".join(lines)
