from __future__ import annotations

from datetime import datetime, timezone
import logging
from decimal import Decimal
import time

from .config import AppConfig
from .exchange import GrvtExchange
from .grid_recovery import GridOpenOrderSnapshot, reconcile_grid_state
from .grid_state import GridBotState, load_grid_state, save_grid_state
from .grid_strategy import plan_grid_orders
from .strategy import OrderPlan, compute_amount_from_quote, new_client_order_id
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

    def _normalize_open_orders(self, payloads: list[dict]) -> list[GridOpenOrderSnapshot]:
        normalized: list[GridOpenOrderSnapshot] = []
        instrument = self._exchange.get_instrument(self._settings.symbol)
        for payload in payloads:
            symbol = str(payload.get("symbol") or payload.get("instrument") or "")
            side = str(payload.get("side", "")).strip().lower()
            if symbol != self._settings.symbol or side not in {"buy", "sell"}:
                continue
            price_value = payload.get("price")
            size_value = (
                payload.get("remaining")
                if payload.get("remaining") not in (None, "", "0", 0)
                else payload.get("amount", payload.get("size"))
            )
            if price_value in (None, "", "0", 0) or size_value in (None, "", "0", 0):
                continue
            normalized.append(
                GridOpenOrderSnapshot(
                    symbol=symbol,
                    side=side,
                    price=self._exchange.round_price(
                        Decimal(str(price_value)),
                        instrument.tick_size,
                    ),
                    size=Decimal(str(size_value)),
                    order_id=str(payload["id"]) if payload.get("id") else None,
                    client_order_id=(
                        str(payload.get("clientOrderId") or payload.get("client_order_id"))
                        if payload.get("clientOrderId") or payload.get("client_order_id")
                        else None
                    ),
                    reduce_only=bool(
                        payload.get("reduceOnly")
                        if payload.get("reduceOnly") is not None
                        else payload.get("reduce_only", False)
                    ),
                )
            )
        return normalized

    def _build_order_plan(self, *, state: GridBotState, instrument, order) -> OrderPlan:
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
                reference_price=order.price,
                instrument=instrument,
                exchange=self._exchange,
            )
        return OrderPlan(
            client_order_id=new_client_order_id(),
            symbol=self._settings.symbol,
            side=order.side,
            order_type="limit",
            amount=amount,
            price=order.price,
            reduce_only=(order.side == "sell"),
            reason=f"grid-{order.side}-level-{order.level_index}",
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
        if isinstance(result, dict) and result.get("order_id") is not None:
            return str(result["order_id"])
        return None

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
                raise ValueError(
                    f"GRVT did not acknowledge grid order submission for {plan.reason} "
                    f"{plan.symbol} {plan.side} amount={plan.amount}"
                )
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
                raise ValueError(
                    f"GRVT did not acknowledge grid order submission for {plan.reason} "
                    f"{plan.symbol} {plan.side} amount={plan.amount}"
                )
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
        open_orders = self._normalize_open_orders(
            self._exchange.fetch_open_orders(symbol=self._settings.symbol)
        )
        exchange_position = self._exchange.get_open_position(self._settings.symbol)
        fills = self._exchange.get_recent_fills(self._settings.symbol, limit=100)

        recovery = reconcile_grid_state(
            state=state,
            settings=self._settings,
            open_orders=open_orders,
            exchange_position=exchange_position,
            fills=fills,
            when=now,
        )
        state = recovery.recovered_state
        if recovery.action != "keep-local" and not self._config.runtime.dry_run:
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
        )
        if changed and not self._config.runtime.dry_run:
            self._persist_state(state)
        return changed

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception as exc:
                self._logger.exception("Grid iteration failed")
                self._notify_iteration_failure(exc)
            time.sleep(self._config.runtime.poll_seconds)
