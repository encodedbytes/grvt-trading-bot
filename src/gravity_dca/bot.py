from __future__ import annotations

from datetime import datetime, timezone
import logging
import time

from .bot_api import BotApiServer, build_shared_status
from .config import AppConfig
from .exchange import (
    FillReport,
    GrvtExchange,
    PositionConfig,
    TransientExchangeError,
)
from .recovery import reconcile_state
from .state import BotState, load_state, save_state
from .strategy import (
    OrderPlan,
    build_entry_order_plan,
    build_exit_order_plan,
    current_quote_amount,
    entry_price,
    exit_price,
    next_safety_trigger_price,
    should_place_safety_order,
    should_start_new_cycle,
    should_stop_loss,
    should_take_profit,
)
from .telegram import (
    Notifier,
    build_notifier,
    format_bot_inactive_message,
    format_cycle_summary,
    format_fill_message,
    format_iteration_failure,
    format_limit_timeout_message,
    format_position_config_change,
    format_recovery_message,
    format_startup_message,
)


UTC = timezone.utc


class DcaBot:
    def __init__(self, config: AppConfig, logger: logging.Logger, notifier: Notifier | None = None) -> None:
        self._config = config
        self._logger = logger
        self._shared_status = build_shared_status(config, logger)
        self._exchange = GrvtExchange(
            config.credentials,
            logger,
            private_auth_retry_attempts=config.runtime.private_auth_retry_attempts,
            private_auth_retry_backoff_seconds=config.runtime.private_auth_retry_backoff_seconds,
        )
        self._notifier = notifier or build_notifier(config, logger)
        self._startup_notified = False
        self._recovery_notified = False
        self._last_iteration_error_key: str | None = None
        self._last_iteration_error_at: float = 0.0
        self._inactive_reason_notified: str | None = None

    def _notify(self, text: str) -> None:
        result = self._notifier.send(text)
        if not result.delivered and result.detail != "telegram-disabled":
            self._logger.info("Telegram notification not delivered: %s", result.detail)

    def _notify_iteration_failure(self, error: Exception) -> None:
        now = time.time()
        error_key = f"{type(error).__name__}:{error}"
        cooldown = self._config.telegram.error_notification_cooldown_seconds
        if (
            self._last_iteration_error_key == error_key
            and now - self._last_iteration_error_at < cooldown
        ):
            self._logger.info(
                "Suppressing duplicate Telegram error notification within cooldown window. "
                "cooldown_seconds=%s error=%s",
                cooldown,
                error_key,
            )
            return
        self._last_iteration_error_key = error_key
        self._last_iteration_error_at = now
        self._notify(format_iteration_failure(self._config.dca.symbol, error))

    def _maybe_notify_startup(self, state: BotState) -> None:
        if self._startup_notified:
            return
        self._notify(format_startup_message(self._config))
        if self._config.telegram.send_startup_summary and state.active_cycle is not None:
            self._notify(format_cycle_summary("Active cycle on startup", state.active_cycle))
        self._startup_notified = True

    def _inactive_reason(self, state: BotState) -> str | None:
        if (
            state.active_cycle is None
            and self._config.dca.max_cycles is not None
            and state.completed_cycles >= self._config.dca.max_cycles
        ):
            return "max-cycles-reached"
        return None

    def _maybe_notify_inactive_state(self, state: BotState) -> None:
        reason = self._inactive_reason(state)
        if reason is None:
            self._inactive_reason_notified = None
            return
        if self._inactive_reason_notified == reason:
            return
        self._notify(
            format_bot_inactive_message(
                symbol=self._config.dca.symbol,
                reason=reason,
                completed_cycles=state.completed_cycles,
                max_cycles=self._config.dca.max_cycles,
            )
        )
        self._inactive_reason_notified = reason

    def _submit_order(self, plan) -> str | None:
        response = self._exchange.place_order(
            symbol=plan.symbol,
            side=plan.side,
            order_type=plan.order_type,
            amount=plan.amount,
            price=plan.price,
            client_order_id=plan.client_order_id,
            reduce_only=plan.reduce_only,
        )
        result = response.get("result", response)
        if isinstance(result, dict):
            order_id = result.get("order_id") or result.get("id")
            if order_id is not None:
                return str(order_id)
        return None

    def _require_order_id(self, plan, order_id: str | None) -> str:
        if order_id is None:
            raise ValueError(
                f"GRVT did not acknowledge order submission for {plan.reason} "
                f"{plan.symbol} {plan.side} amount={plan.amount}"
            )
        return order_id

    def _wait_for_fill(self, plan: OrderPlan) -> FillReport | None:
        timeout_seconds = (
            self._config.runtime.limit_ttl_seconds
            if plan.order_type == "limit"
            else self._config.runtime.order_fill_timeout_seconds
        )
        return self._exchange.wait_for_fill(
            symbol=plan.symbol,
            order_type=plan.order_type,
            client_order_id=plan.client_order_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=self._config.runtime.order_fill_poll_seconds,
        )

    def _current_cycle_position_config(self, symbol: str) -> PositionConfig:
        return self._exchange.get_effective_position_config(symbol)

    def _submit_and_fill(self, plan: OrderPlan) -> FillReport | None:
        self._require_order_id(plan, self._submit_order(plan))
        return self._wait_for_fill(plan)

    def _persist_state(self, state: BotState) -> None:
        save_state(self._config.dca.state_file, state)

    def _reconcile_state_with_exchange(self, *, state: BotState, now: datetime) -> BotState:
        try:
            exchange_position = self._exchange.get_open_position(self._config.dca.symbol)
            exchange_fills = (
                self._exchange.get_recent_fills(self._config.dca.symbol)
                if exchange_position is not None
                else None
            )
        except TransientExchangeError as exc:
            if state.active_cycle is not None:
                self._logger.warning(
                    "Transient exchange error during recovery. "
                    "Keeping local active cycle for this iteration. error=%s",
                    exc,
                )
                return state
            raise
        decision = reconcile_state(
            state=state,
            settings=self._config.dca,
            symbol=self._config.dca.symbol,
            exchange_position=exchange_position,
            exchange_fills=exchange_fills,
            when=now,
        )
        self._logger.info(decision.message)
        if decision.reconstruction_message is not None:
            self._logger.info(
                "Recovery reconstruction attempted=%s succeeded=%s details=%s",
                decision.reconstruction_attempted,
                decision.reconstruction_succeeded,
                decision.reconstruction_message,
            )
        if not self._recovery_notified:
            self._notify(format_recovery_message(self._config.dca.symbol, decision))
            self._recovery_notified = True
        if decision.action == "keep-local":
            if decision.recovered_cycle is not None:
                state.replace_active_cycle(decision.recovered_cycle)
                self._persist_state(state)
            return state
        if decision.action in {"rebuild-from-exchange", "rebuild-from-exchange-history"}:
            state.replace_active_cycle(decision.recovered_cycle)
            self._persist_state(state)
            return state
        if decision.action == "clear-stale-local":
            state.replace_active_cycle(None)
            self._persist_state(state)
            return state
        return state

    def _handle_initial_entry(self, *, state: BotState, now, instrument, snapshot) -> bool:
        if not should_start_new_cycle(state, self._config.dca):
            self._logger.info(
                "No active cycle and max_cycles reached. completed_cycles=%s",
                state.completed_cycles,
            )
            self._maybe_notify_inactive_state(state)
            return False

        plan = build_entry_order_plan(
            settings=self._config.dca,
            symbol=self._config.dca.symbol,
            side=self._config.dca.side,
            quote_amount=self._config.dca.initial_quote_amount,
            instrument=instrument,
            snapshot=snapshot,
            exchange=self._exchange,
            reason="initial-entry",
        )
        fill_price = entry_price(snapshot, self._config.dca.side)
        self._logger.info(
            "Prepared initial entry side=%s order_type=%s amount=%s price=%s fill_price=%s dry_run=%s",
            plan.side,
            plan.order_type,
            plan.amount,
            plan.price,
            fill_price,
            self._config.runtime.dry_run,
        )
        if self._config.runtime.dry_run:
            return True

        report = self._submit_and_fill(plan)
        if report is None:
            self._logger.info("Initial entry limit order was not filled before timeout.")
            self._notify(
                format_limit_timeout_message(plan.symbol, plan.reason, plan.client_order_id)
            )
            return False
        position_config = self._current_cycle_position_config(plan.symbol)
        state.start_cycle(
            symbol=plan.symbol,
            side=plan.side,
            when=now,
            quantity=report.traded_size,
            price=report.avg_fill_price,
            order_id=report.order_id,
            client_order_id=plan.client_order_id,
            leverage=position_config.leverage,
            margin_type=position_config.margin_type,
        )
        self._persist_state(state)
        self._inactive_reason_notified = None
        self._notify(
            format_fill_message(
                symbol=plan.symbol,
                label="initial entry filled",
                side=plan.side,
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_type=plan.order_type,
                extra_lines=[
                    f"leverage={position_config.leverage}",
                    f"margin_type={position_config.margin_type}",
                ],
            )
        )
        return True

    def _handle_exit(self, *, state: BotState, cycle, snapshot, now, reason: str) -> bool:
        instrument = self._exchange.get_instrument(cycle.symbol)
        plan = build_exit_order_plan(
            cycle=cycle,
            settings=self._config.dca,
            instrument=instrument,
            snapshot=snapshot,
            exchange=self._exchange,
            reason=reason,
        )
        close_price = exit_price(snapshot, cycle.side)
        self._logger.info(
            "%s hit. exit_side=%s order_type=%s amount=%s price=%s close_price=%s dry_run=%s",
            "Take profit" if reason == "take-profit" else "Stop loss",
            plan.side,
            plan.order_type,
            plan.amount,
            plan.price,
            close_price,
            self._config.runtime.dry_run,
        )
        if self._config.runtime.dry_run:
            return True
        report = self._submit_and_fill(plan)
        if report is None:
            self._logger.info("%s limit order was not filled before timeout.", reason)
            self._notify(
                format_limit_timeout_message(plan.symbol, plan.reason, plan.client_order_id)
            )
            return False
        state.close_cycle(when=now, exit_reason=plan.reason, exit_price=close_price)
        self._persist_state(state)
        self._notify(
            format_fill_message(
                symbol=plan.symbol,
                label=f"{reason} filled",
                side=plan.side,
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_type=plan.order_type,
                extra_lines=[f"exit_price_reference={close_price}"],
            )
        )
        self._maybe_notify_inactive_state(state)
        return True

    def _handle_safety_order(self, *, state: BotState, cycle, instrument, snapshot) -> bool:
        next_index = cycle.completed_safety_orders + 1
        quote_amount = current_quote_amount(self._config.dca, next_index)
        plan = build_entry_order_plan(
            settings=self._config.dca,
            symbol=self._config.dca.symbol,
            side=cycle.side,
            quote_amount=quote_amount,
            instrument=instrument,
            snapshot=snapshot,
            exchange=self._exchange,
            reason=f"safety-order-{next_index}",
        )
        fill_price = entry_price(snapshot, cycle.side)
        self._logger.info(
            "Safety trigger hit. index=%s order_type=%s amount=%s price=%s fill_price=%s dry_run=%s",
            next_index,
            plan.order_type,
            plan.amount,
            plan.price,
            fill_price,
            self._config.runtime.dry_run,
        )
        if self._config.runtime.dry_run:
            return True
        report = self._submit_and_fill(plan)
        if report is None:
            self._logger.info("Safety limit order index=%s was not filled before timeout.", next_index)
            self._notify(
                format_limit_timeout_message(plan.symbol, plan.reason, plan.client_order_id)
            )
            return False
        position_config = self._current_cycle_position_config(plan.symbol)
        state.add_safety_fill(
            quantity=report.traded_size,
            price=report.avg_fill_price,
            order_id=report.order_id,
            client_order_id=plan.client_order_id,
            leverage=position_config.leverage,
            margin_type=position_config.margin_type,
        )
        self._persist_state(state)
        cycle = state.active_cycle
        extra_lines = []
        if cycle is not None:
            extra_lines.extend(
                [
                    f"new_avg_entry={cycle.average_entry_price}",
                    f"completed_safety_orders={cycle.completed_safety_orders}",
                ]
            )
        self._notify(
            format_fill_message(
                symbol=plan.symbol,
                label=f"safety order {next_index} filled",
                side=plan.side,
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_type=plan.order_type,
                extra_lines=extra_lines,
            )
        )
        return True

    def run_once(self) -> bool:
        started_at = datetime.now(tz=UTC).isoformat()
        self._shared_status.mark_iteration_started(started_at)
        state = load_state(self._config.dca.state_file)
        now = datetime.now(tz=UTC)
        state = self._reconcile_state_with_exchange(state=state, now=now)
        self._maybe_notify_startup(state)
        self._maybe_notify_inactive_state(state)
        changes = self._exchange.ensure_position_config(
            symbol=self._config.dca.symbol,
            leverage=self._config.dca.initial_leverage,
            margin_type=self._config.dca.margin_type,
            dry_run=self._config.runtime.dry_run,
        )
        if self._config.telegram.notify_position_config_changes:
            for change in changes:
                self._notify(format_position_config_change(self._config.dca.symbol, change))
        instrument = self._exchange.get_instrument(self._config.dca.symbol)
        snapshot = self._exchange.get_market_snapshot(self._config.dca.symbol)

        if state.active_cycle is None:
            changed = self._handle_initial_entry(
                state=state,
                now=now,
                instrument=instrument,
                snapshot=snapshot,
            )
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return changed

        cycle = state.active_cycle
        self._logger.info(
            "Active cycle side=%s avg_entry=%s qty=%s completed_safety_orders=%s next_trigger=%s",
            cycle.side,
            cycle.average_entry_price,
            cycle.total_quantity,
            cycle.completed_safety_orders,
            next_safety_trigger_price(cycle, self._config.dca),
        )

        if should_take_profit(cycle, snapshot, self._config.dca):
            changed = self._handle_exit(
                state=state,
                cycle=cycle,
                snapshot=snapshot,
                now=now,
                reason="take-profit",
            )
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return changed

        if should_stop_loss(cycle, snapshot, self._config.dca):
            changed = self._handle_exit(
                state=state,
                cycle=cycle,
                snapshot=snapshot,
                now=now,
                reason="stop-loss",
            )
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return changed

        if should_place_safety_order(cycle, snapshot, self._config.dca):
            changed = self._handle_safety_order(
                state=state,
                cycle=cycle,
                instrument=instrument,
                snapshot=snapshot,
            )
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return changed

        self._logger.info("No action taken this iteration.")
        self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
        return False

    def run_forever(self) -> None:
        with BotApiServer(self._shared_status, port=self._config.runtime.bot_api_port):
            while True:
                try:
                    self.run_once()
                except Exception as exc:
                    self._shared_status.mark_iteration_failed(
                        datetime.now(tz=UTC).isoformat(),
                        exc,
                    )
                    self._logger.exception("DCA iteration failed")
                    self._notify_iteration_failure(exc)
                time.sleep(self._config.runtime.poll_seconds)
