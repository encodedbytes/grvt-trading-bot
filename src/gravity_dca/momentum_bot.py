from __future__ import annotations

from datetime import datetime, timezone
import logging
import time

from .bot_api import BotApiServer, build_shared_status
from .config import AppConfig
from .exchange import FillReport, GrvtExchange, PositionConfig, TransientExchangeError
from .momentum_recovery import reconcile_momentum_state
from .momentum_state import MomentumBotState, load_momentum_state, save_momentum_state
from .momentum_strategy import (
    build_indicator_snapshot,
    evaluate_entry,
    evaluate_exit,
)
from .status_snapshot import serialize_momentum_indicator_snapshot
from .strategy import (
    OrderPlan,
    compute_amount_from_quote,
    entry_price,
    exit_price,
    limit_price_from_reference,
    new_client_order_id,
    opposite_side,
    validate_order_type,
)
from .telegram import (
    Notifier,
    build_notifier,
    format_fill_message,
    format_iteration_failure,
    format_limit_timeout_message,
    format_position_config_change,
    format_recovery_message,
    format_startup_message,
)


UTC = timezone.utc


class MomentumBot:
    def __init__(self, config: AppConfig, logger: logging.Logger, notifier: Notifier | None = None) -> None:
        if config.momentum is None:
            raise ValueError("Momentum config is required for MomentumBot")
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

    @property
    def _settings(self):
        if self._config.momentum is None:
            raise ValueError("Momentum config is required for MomentumBot")
        return self._config.momentum

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
        self._notify(format_iteration_failure(self._settings.symbol, error))

    def _maybe_notify_startup(self) -> None:
        if self._startup_notified:
            return
        self._notify(format_startup_message(self._config))
        self._startup_notified = True

    def _persist_state(self, state: MomentumBotState) -> None:
        save_momentum_state(self._settings.state_file, state)

    def _reconcile_state_with_exchange(
        self,
        *,
        state: MomentumBotState,
        now: datetime,
        candles,
    ) -> MomentumBotState:
        try:
            exchange_position = self._exchange.get_open_position(self._settings.symbol)
            exchange_fills = (
                self._exchange.get_recent_fills(self._settings.symbol)
                if exchange_position is not None
                else None
            )
        except TransientExchangeError as exc:
            if state.active_position is not None:
                self._logger.warning(
                    "Transient exchange error during momentum recovery. "
                    "Keeping local active position for this iteration. error=%s",
                    exc,
                )
                return state
            raise
        decision = reconcile_momentum_state(
            state=state,
            settings=self._settings,
            symbol=self._settings.symbol,
            exchange_position=exchange_position,
            exchange_fills=exchange_fills,
            candles=candles,
            when=now,
        )
        self._logger.info(decision.message)
        if decision.reconstruction_message is not None:
            self._logger.info(
                "Momentum recovery reconstruction attempted=%s succeeded=%s details=%s",
                decision.reconstruction_attempted,
                decision.reconstruction_succeeded,
                decision.reconstruction_message,
            )
        if not self._recovery_notified:
            self._notify(format_recovery_message(self._settings.symbol, decision))
            self._recovery_notified = True
        if decision.action == "keep-local":
            if decision.recovered_position is not None:
                state.replace_active_position(decision.recovered_position)
                self._persist_state(state)
            return state
        if decision.action in {"rebuild-from-exchange", "rebuild-from-exchange-history"}:
            state.replace_active_position(decision.recovered_position)
            self._persist_state(state)
            return state
        if decision.action == "clear-stale-local":
            state.replace_active_position(None)
            self._persist_state(state)
            return state
        return state

    def _submit_order(self, plan: OrderPlan) -> str | None:
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

    def _require_order_id(self, plan: OrderPlan, order_id: str | None) -> str:
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

    def _submit_and_fill(self, plan: OrderPlan) -> FillReport | None:
        self._require_order_id(plan, self._submit_order(plan))
        return self._wait_for_fill(plan)

    def _current_position_config(self, symbol: str) -> PositionConfig:
        return self._exchange.get_effective_position_config(symbol)

    def _build_entry_plan(self, *, instrument, snapshot) -> OrderPlan:
        reference_price = entry_price(snapshot, self._settings.side)
        amount = compute_amount_from_quote(
            quote_amount=self._settings.quote_amount,
            reference_price=reference_price,
            instrument=instrument,
            exchange=self._exchange,
        )
        order_type = validate_order_type(self._settings.order_type)
        price = None
        if order_type == "limit":
            price = limit_price_from_reference(
                side=self._settings.side,
                reference_price=reference_price,
                offset_percent=self._settings.limit_price_offset_percent,
                instrument=instrument,
                exchange=self._exchange,
            )
        return OrderPlan(
            client_order_id=new_client_order_id(),
            symbol=self._settings.symbol,
            side=self._settings.side,
            order_type=order_type,
            amount=amount,
            price=price,
            reduce_only=False,
            reason="momentum-entry",
        )

    def _build_exit_plan(self, *, state: MomentumBotState, instrument, snapshot, reason: str) -> OrderPlan:
        position = state.active_position
        if position is None:
            raise ValueError("Active momentum position is required for exit planning")
        side = opposite_side(position.side)
        order_type = validate_order_type(self._settings.order_type)
        price = None
        if order_type == "limit":
            price = limit_price_from_reference(
                side=side,
                reference_price=exit_price(snapshot, position.side),
                offset_percent=self._settings.limit_price_offset_percent,
                instrument=instrument,
                exchange=self._exchange,
            )
        return OrderPlan(
            client_order_id=new_client_order_id(),
            symbol=position.symbol,
            side=side,
            order_type=order_type,
            amount=position.total_quantity,
            price=price,
            reduce_only=True,
            reason=reason,
        )

    def _fetch_candles(self):
        # Fetch a modest buffer above the minimum required count so indicators remain stable.
        return self._exchange.get_candles(
            self._settings.symbol,
            timeframe=self._settings.timeframe,
            limit=max(
                100,
                self._settings.ema_slow_period + self._settings.breakout_lookback + 5,
                (self._settings.adx_period * 2) + 5,
            ),
        )

    def _set_entry_strategy_status(
        self,
        decision,
        *,
        decision_override: str | None = None,
        reason_override: str | None = None,
    ) -> None:
        self._shared_status.set_strategy_status(
            {
                "strategy_type": "momentum",
                "mode": "entry",
                "entry_decision": (
                    decision_override
                    if decision_override is not None
                    else ("enter" if decision.should_enter else "skip")
                ),
                "entry_reason": reason_override if reason_override is not None else decision.reason,
                "indicator_snapshot": serialize_momentum_indicator_snapshot(
                    decision.indicator_snapshot
                ),
                "initial_stop_price": (
                    str(decision.initial_stop_price)
                    if decision.initial_stop_price is not None
                    else None
                ),
                "trailing_stop_price": (
                    str(decision.trailing_stop_price)
                    if decision.trailing_stop_price is not None
                    else None
                ),
            }
        )

    def _set_exit_strategy_status(
        self,
        decision,
        *,
        decision_override: str | None = None,
        reason_override: str | None = None,
    ) -> None:
        self._shared_status.set_strategy_status(
            {
                "strategy_type": "momentum",
                "mode": "position",
                "exit_decision": (
                    decision_override
                    if decision_override is not None
                    else ("exit" if decision.should_exit else "hold")
                ),
                "exit_reason": reason_override if reason_override is not None else decision.reason,
                "indicator_snapshot": serialize_momentum_indicator_snapshot(
                    decision.indicator_snapshot
                ),
                "stop_price": str(decision.stop_price) if decision.stop_price is not None else None,
                "trailing_stop_price": (
                    str(decision.trailing_stop_price)
                    if decision.trailing_stop_price is not None
                    else None
                ),
                "highest_price_since_entry": (
                    str(decision.highest_price_since_entry)
                    if decision.highest_price_since_entry is not None
                    else None
                ),
            }
        )

    def _set_live_position_status(
        self,
        state: MomentumBotState,
        *,
        indicator_snapshot=None,
        decision: str = "hold",
        reason: str = "active-position",
    ) -> None:
        position = state.active_position
        if position is None:
            self._shared_status.set_strategy_status(None)
            return
        self._shared_status.set_strategy_status(
            {
                "strategy_type": "momentum",
                "mode": "position",
                "exit_decision": decision,
                "exit_reason": reason,
                "indicator_snapshot": serialize_momentum_indicator_snapshot(indicator_snapshot),
                "stop_price": (
                    str(position.trailing_stop_price)
                    if position.trailing_stop_price is not None
                    else (
                        str(position.initial_stop_price)
                        if position.initial_stop_price is not None
                        else None
                    )
                ),
                "trailing_stop_price": (
                    str(position.trailing_stop_price)
                    if position.trailing_stop_price is not None
                    else None
                ),
                "highest_price_since_entry": (
                    str(position.highest_price_since_entry)
                    if position.highest_price_since_entry is not None
                    else None
                ),
            }
        )

    def run_once(self) -> bool:
        started_at = datetime.now(tz=UTC).isoformat()
        self._shared_status.mark_iteration_started(started_at)
        state = load_momentum_state(self._settings.state_file)
        now = datetime.now(tz=UTC)
        self._maybe_notify_startup()
        changes = self._exchange.ensure_position_config(
            symbol=self._settings.symbol,
            leverage=self._settings.initial_leverage,
            margin_type=self._settings.margin_type,
            dry_run=self._config.runtime.dry_run,
        )
        if self._config.telegram.notify_position_config_changes:
            for change in changes:
                self._notify(format_position_config_change(self._settings.symbol, change))
        instrument = self._exchange.get_instrument(self._settings.symbol)
        snapshot = self._exchange.get_market_snapshot(self._settings.symbol)
        candles = self._fetch_candles()
        state = self._reconcile_state_with_exchange(state=state, now=now, candles=candles)

        if state.active_position is None:
            decision = evaluate_entry(candles, self._settings, state)
            self._set_entry_strategy_status(decision)
            self._logger.info("Momentum entry decision=%s should_enter=%s", decision.reason, decision.should_enter)
            if not decision.should_enter:
                self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
                return False
            plan = self._build_entry_plan(instrument=instrument, snapshot=snapshot)
            if self._config.runtime.dry_run:
                self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
                return True
            report = self._submit_and_fill(plan)
            if report is None:
                self._set_entry_strategy_status(
                    decision,
                    decision_override="skip",
                    reason_override="limit-timeout",
                )
                self._notify(format_limit_timeout_message(plan.symbol, plan.reason, plan.client_order_id))
                self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
                return False
            position_config = self._current_position_config(plan.symbol)
            state.open_position(
                symbol=plan.symbol,
                side=plan.side,
                when=now,
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_id=report.order_id,
                client_order_id=plan.client_order_id,
                leverage=position_config.leverage,
                margin_type=position_config.margin_type,
                highest_price_since_entry=(
                    decision.indicator_snapshot.close_price
                    if decision.indicator_snapshot is not None
                    else report.avg_fill_price
                ),
                initial_stop_price=decision.initial_stop_price,
                trailing_stop_price=decision.trailing_stop_price,
                breakout_level=decision.breakout_level,
                timeframe=self._settings.timeframe,
            )
            self._persist_state(state)
            self._set_live_position_status(
                state,
                indicator_snapshot=decision.indicator_snapshot,
                decision="hold",
                reason="entry-filled",
            )
            self._notify(
                format_fill_message(
                    symbol=plan.symbol,
                    label="momentum entry filled",
                    side=plan.side,
                    quantity=report.traded_size,
                    price=report.avg_fill_price,
                    order_type=plan.order_type,
                    extra_lines=[
                        f"breakout_level={decision.breakout_level}",
                        f"initial_stop_price={decision.initial_stop_price}",
                        f"trailing_stop_price={decision.trailing_stop_price}",
                    ],
                )
            )
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return True

        decision = evaluate_exit(candles, self._settings, state)
        self._set_exit_strategy_status(decision)
        self._logger.info("Momentum exit decision=%s should_exit=%s", decision.reason, decision.should_exit)
        position = state.active_position
        metadata_changed = False
        if position is not None and (
            decision.highest_price_since_entry != position.highest_price_since_entry
            or decision.trailing_stop_price != position.trailing_stop_price
        ):
            state.update_active_position(
                highest_price_since_entry=decision.highest_price_since_entry,
                trailing_stop_price=decision.trailing_stop_price,
            )
            self._persist_state(state)
            metadata_changed = True

        if not decision.should_exit:
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return metadata_changed

        plan = self._build_exit_plan(
            state=state,
            instrument=instrument,
            snapshot=snapshot,
            reason=decision.reason or "momentum-exit",
        )
        if self._config.runtime.dry_run:
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return True
        report = self._submit_and_fill(plan)
        if report is None:
            self._set_exit_strategy_status(
                decision,
                decision_override="deferred",
                reason_override="limit-timeout",
            )
            self._notify(format_limit_timeout_message(plan.symbol, plan.reason, plan.client_order_id))
            self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
            return metadata_changed
        state.close_position(
            when=now,
            exit_reason=plan.reason,
            exit_price=report.avg_fill_price,
        )
        self._persist_state(state)
        self._notify(
            format_fill_message(
                symbol=plan.symbol,
                label=f"{plan.reason} filled",
                side=plan.side,
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_type=plan.order_type,
                extra_lines=[
                    f"highest_price_since_entry={decision.highest_price_since_entry}",
                    f"trailing_stop_price={decision.trailing_stop_price}",
                ],
            )
        )
        self._shared_status.set_strategy_status(None)
        self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
        return True

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
                    self._logger.exception("Momentum iteration failed")
                    self._notify_iteration_failure(exc)
                time.sleep(self._config.runtime.poll_seconds)
