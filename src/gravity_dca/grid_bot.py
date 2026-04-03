from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .bot_api import BotApiServer, build_shared_status
from .config import AppConfig
from .exchange import GrvtExchange
from .grid_recovery import GridOpenOrderSnapshot, normalize_grid_open_orders, reconcile_grid_state
from .grid_state import GridBotState, load_grid_state, save_grid_state
from .grid_strategy import plan_grid_orders, seed_level_index
from .strategy import OrderPlan, compute_amount_from_quote, entry_price, new_client_order_id
from .telegram import (
    Notifier,
    build_notifier,
    format_fill_message,
    format_iteration_failure,
    format_position_config_change,
    format_startup_message,
)

UTC = timezone.utc


class GridBot:
    def __init__(self, config: AppConfig, logger: logging.Logger, notifier: Notifier | None = None) -> None:
        if config.grid is None:
            raise ValueError("Grid config is required for GridBot")
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
        self._last_iteration_error_key: str | None = None
        self._last_iteration_error_at: float = 0.0

    @property
    def _settings(self):
        if self._config.grid is None:
            raise ValueError("Grid config is required for GridBot")
        return self._config.grid

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

    def _persist_state(self, state: GridBotState) -> None:
        save_grid_state(self._settings.state_file, state)

    def _is_retryable_recovery_error(self, error: Exception) -> bool:
        message = str(error)
        return any(
            fragment in message
            for fragment in (
                "Grid inventory quantity does not match exchange position",
                "Grid local inventory exists but no exchange position is open",
                "Open sell order has no matching inventory for level",
            )
        )

    def _reconcile_state_with_exchange(
        self,
        *,
        state: GridBotState,
        now: datetime,
    ) -> tuple[GridBotState, str, list[GridOpenOrderSnapshot], object | None]:
        attempts = max(1, self._config.runtime.private_auth_retry_attempts)
        backoff_seconds = max(0, self._config.runtime.private_auth_retry_backoff_seconds)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            instrument = self._exchange.get_instrument(self._settings.symbol)
            open_orders = normalize_grid_open_orders(
                self._exchange.fetch_open_orders(symbol=self._settings.symbol),
                symbol=self._settings.symbol,
                tick_size=instrument.tick_size,
                round_price=self._exchange.round_price,
            )
            exchange_position = self._exchange.get_open_position(self._settings.symbol)
            fills = self._exchange.get_recent_fills(self._settings.symbol, limit=100)
            try:
                recovery = reconcile_grid_state(
                    state=state,
                    settings=self._settings,
                    open_orders=open_orders,
                    exchange_position=exchange_position,
                    fills=fills,
                    when=now,
                )
                if recovery.action != "keep-local" and not self._config.runtime.dry_run:
                    self._persist_state(recovery.recovered_state)
                return recovery.recovered_state, recovery.action, open_orders, exchange_position
            except ValueError as exc:
                last_error = exc
                if attempt >= attempts or not self._is_retryable_recovery_error(exc):
                    raise
                self._logger.warning(
                    "Grid recovery snapshot mismatch. Retrying exchange snapshot. "
                    "attempt=%s/%s error=%s",
                    attempt,
                    attempts,
                    exc,
                )
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Grid recovery failed without a captured exception")

    def _build_order_plan(self, *, state: GridBotState, instrument, order) -> OrderPlan:
        order_price = self._exchange.round_price(order.price, instrument.tick_size)
        if order_price <= 0:
            raise ValueError(
                f"Computed grid order price must be positive for level {order.level_index}: {order.price}"
            )
        if order.side == "sell":
            level = state.level(order.level_index)
            if level.entry_quantity is None:
                raise ValueError(
                    f"Cannot build grid sell plan without entry quantity for level {order.level_index}"
                )
            amount = level.entry_quantity
        else:
            amount = compute_amount_from_quote(
                quote_amount=self._settings.quote_amount_per_level,
                reference_price=order_price,
                instrument=instrument,
                exchange=self._exchange,
            )
        return OrderPlan(
            client_order_id=new_client_order_id(),
            symbol=self._settings.symbol,
            side=order.side,
            order_type="limit",
            amount=amount,
            price=order_price,
            reduce_only=(order.side == "sell"),
            reason=f"grid-{order.side}-level-{order.level_index}",
        )

    def _build_seed_order_plan(self, *, instrument, snapshot, level_index: int) -> OrderPlan:
        reference_price = entry_price(snapshot, self._settings.side)
        amount = compute_amount_from_quote(
            quote_amount=self._settings.quote_amount_per_level,
            reference_price=reference_price,
            instrument=instrument,
            exchange=self._exchange,
        )
        return OrderPlan(
            client_order_id=new_client_order_id(),
            symbol=self._settings.symbol,
            side=self._settings.side,
            order_type="market",
            amount=amount,
            price=None,
            reduce_only=False,
            reason=f"grid-seed-level-{level_index}",
        )

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

    def _should_seed_on_start(
        self,
        *,
        recovery_action: str,
        state: GridBotState,
        open_orders: list[GridOpenOrderSnapshot],
        exchange_position,
    ) -> bool:
        if not self._settings.seed_enabled:
            return False
        if recovery_action != "initialize-from-config":
            return False
        if open_orders or exchange_position is not None:
            return False
        return not any(
            level.status in {"buy_open", "filled_inventory", "sell_open"}
            for level in state.levels
        )

    def _should_reseed_when_flat(
        self,
        *,
        recovery_action: str,
        state: GridBotState,
        exchange_position,
    ) -> bool:
        if not self._settings.reseed_when_flat:
            return False
        if recovery_action == "initialize-from-config":
            return False
        if exchange_position is not None:
            return False
        if state.completed_round_trips < 1:
            return False
        return not any(
            level.status in {"filled_inventory", "sell_open"}
            for level in state.levels
        )

    def _clear_open_buy_level(
        self,
        *,
        state: GridBotState,
        level_index: int,
        now: datetime,
    ) -> bool:
        level = state.level(level_index)
        if level.status != "buy_open":
            return False
        if self._config.runtime.dry_run:
            self._logger.info("Dry run: would cancel grid buy order at reseed level %s", level_index)
        else:
            self._exchange.cancel_order(
                symbol=self._settings.symbol,
                order_id=level.entry_order_id,
                client_order_id=level.entry_client_order_id,
            )
        level.status = "idle"
        level.entry_order_id = None
        level.entry_client_order_id = None
        level.entry_fill_price = None
        level.entry_quantity = None
        level.exit_order_id = None
        level.exit_client_order_id = None
        level.exit_fill_price = None
        level.realized_pnl_estimate = None
        level.updated_at = now.astimezone(UTC).isoformat()
        return True

    def _apply_seed_order(
        self,
        *,
        state: GridBotState,
        instrument,
        snapshot,
        now: datetime,
    ) -> bool:
        level_index = seed_level_index(settings=self._settings, market_price=snapshot.last)
        if level_index is None:
            self._logger.info(
                "Skipping grid seed order because no buyable grid level exists below market. "
                "market_price=%s",
                snapshot.last,
            )
            return False
        cleared_existing_buy = self._clear_open_buy_level(
            state=state,
            level_index=level_index,
            now=now,
        )
        plan = self._build_seed_order_plan(
            instrument=instrument,
            snapshot=snapshot,
            level_index=level_index,
        )
        if self._config.runtime.dry_run:
            self._logger.info("Dry run: would place %s", plan.reason)
            return True or cleared_existing_buy
        order_id = self._submit_order(plan)
        if order_id is None:
            raise ValueError(
                f"GRVT did not acknowledge grid order submission for {plan.reason} "
                f"{plan.symbol} {plan.side} amount={plan.amount}"
            )
        fill = self._exchange.wait_for_fill(
            symbol=plan.symbol,
            order_type=plan.order_type,
            client_order_id=plan.client_order_id,
            timeout_seconds=self._config.runtime.order_fill_timeout_seconds,
            poll_seconds=self._config.runtime.order_fill_poll_seconds,
        )
        if fill is None or fill.traded_size <= 0 or fill.avg_fill_price <= 0:
            raise ValueError(f"Grid seed order did not fill cleanly for {plan.symbol}")
        state.mark_buy_filled(
            level_index=level_index,
            when=now,
            fill_price=fill.avg_fill_price,
            quantity=fill.traded_size,
            order_id=fill.order_id or order_id,
            client_order_id=fill.client_order_id or plan.client_order_id,
        )
        self._notify(
            format_fill_message(
                symbol=plan.symbol,
                label="grid seed order filled",
                side=plan.side,
                quantity=fill.traded_size,
                price=fill.avg_fill_price,
                order_type=plan.order_type,
                extra_lines=[f"level_index={level_index}"],
            )
        )
        return True or cleared_existing_buy

    def _warn_unacknowledged_grid_order(self, *, plan: OrderPlan) -> None:
        self._logger.warning(
            "GRVT did not acknowledge grid order submission; leaving state unchanged and retrying "
            "on the next poll. reason=%s symbol=%s side=%s amount=%s client_order_id=%s",
            plan.reason,
            plan.symbol,
            plan.side,
            plan.amount,
            plan.client_order_id,
        )

    def _place_desired_orders(self, *, state: GridBotState, instrument, decision, now: datetime) -> bool:
        changed = False
        for level_index in decision.cancel_buy_level_indices:
            level = state.level(level_index)
            if self._config.runtime.dry_run:
                self._logger.info("Dry run: would cancel grid buy order at level %s", level_index)
                changed = True
                continue
            self._exchange.cancel_order(
                symbol=self._settings.symbol,
                order_id=level.entry_order_id,
                client_order_id=level.entry_client_order_id,
            )
            level.status = "idle"
            level.entry_order_id = None
            level.entry_client_order_id = None
            level.updated_at = now.astimezone(UTC).isoformat()
            changed = True

        for desired in decision.desired_buy_orders:
            plan = self._build_order_plan(state=state, instrument=instrument, order=desired)
            if self._config.runtime.dry_run:
                self._logger.info("Dry run: would place %s at %s", plan.reason, plan.price)
                changed = True
                continue
            order_id = self._submit_order(plan)
            if order_id is None:
                self._warn_unacknowledged_grid_order(plan=plan)
                continue
            state.open_buy_order(
                level_index=desired.level_index,
                when=now,
                order_id=order_id,
                client_order_id=plan.client_order_id,
            )
            self._notify(
                format_fill_message(
                    symbol=plan.symbol,
                    label="grid buy order placed",
                    side=plan.side,
                    quantity=plan.amount,
                    price=plan.price,
                    order_type=plan.order_type,
                    extra_lines=[f"level_index={desired.level_index}"],
                )
            )
            changed = True

        for desired in decision.desired_sell_orders:
            plan = self._build_order_plan(state=state, instrument=instrument, order=desired)
            if self._config.runtime.dry_run:
                self._logger.info("Dry run: would place %s at %s", plan.reason, plan.price)
                changed = True
                continue
            order_id = self._submit_order(plan)
            if order_id is None:
                self._warn_unacknowledged_grid_order(plan=plan)
                continue
            state.open_sell_order(
                level_index=desired.level_index,
                when=now,
                order_id=order_id,
                client_order_id=plan.client_order_id,
            )
            self._notify(
                format_fill_message(
                    symbol=plan.symbol,
                    label="grid sell order placed",
                    side=plan.side,
                    quantity=plan.amount,
                    price=plan.price,
                    order_type=plan.order_type,
                    extra_lines=[
                        f"level_index={desired.level_index}",
                        f"paired_level_index={desired.paired_level_index}",
                    ],
                )
            )
            changed = True
        return changed

    def run_once(self) -> bool:
        started_at = datetime.now(tz=UTC).isoformat()
        self._shared_status.mark_iteration_started(started_at)
        state = load_grid_state(self._settings.state_file)
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
        state, recovery_action, open_orders, exchange_position = self._reconcile_state_with_exchange(
            state=state,
            now=now,
        )

        changed = False
        if self._should_seed_on_start(
            recovery_action=recovery_action,
            state=state,
            open_orders=open_orders,
            exchange_position=exchange_position,
        ):
            changed = self._apply_seed_order(
                state=state,
                instrument=instrument,
                snapshot=snapshot,
                now=now,
            )
            if changed and not self._config.runtime.dry_run:
                self._persist_state(state)
        elif self._should_reseed_when_flat(
            recovery_action=recovery_action,
            state=state,
            exchange_position=exchange_position,
        ):
            changed = self._apply_seed_order(
                state=state,
                instrument=instrument,
                snapshot=snapshot,
                now=now,
            )
            if changed and not self._config.runtime.dry_run:
                self._persist_state(state)

        decision = plan_grid_orders(
            state=state,
            settings=self._settings,
            market_price=snapshot.last,
        )
        changed = self._place_desired_orders(
            state=state,
            instrument=instrument,
            decision=decision,
            now=now,
        ) or changed
        if changed and not self._config.runtime.dry_run:
            self._persist_state(state)
        self._shared_status.mark_iteration_succeeded(datetime.now(tz=UTC).isoformat())
        return changed

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
                    self._logger.exception("Grid iteration failed")
                    self._notify_iteration_failure(exc)
                time.sleep(self._config.runtime.poll_seconds)
