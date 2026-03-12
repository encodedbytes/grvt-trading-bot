from __future__ import annotations

from datetime import datetime, timezone
import logging
import time

from .config import AppConfig
from .exchange import GrvtExchange
from .state import BotState, load_state, save_state
from .strategy import (
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


UTC = timezone.utc


class DcaBot:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._exchange = GrvtExchange(config.credentials, logger)

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
        if isinstance(result, dict) and result.get("order_id") is not None:
            return str(result["order_id"])
        return None

    def _require_order_id(self, plan, order_id: str | None) -> str:
        if order_id is None:
            raise ValueError(
                f"GRVT did not acknowledge order submission for {plan.reason} "
                f"{plan.symbol} {plan.side} amount={plan.amount}"
            )
        return order_id

    def _wait_for_fill(self, plan, order_id: str) -> tuple[str, object]:
        report = self._exchange.wait_for_fill(
            client_order_id=plan.client_order_id,
            timeout_seconds=self._config.runtime.order_fill_timeout_seconds,
            poll_seconds=self._config.runtime.order_fill_poll_seconds,
        )
        return order_id, report

    def run_once(self) -> bool:
        state = load_state(self._config.dca.state_file)
        now = datetime.now(tz=UTC)
        instrument = self._exchange.get_instrument(self._config.dca.symbol)
        snapshot = self._exchange.get_market_snapshot(self._config.dca.symbol)

        if state.active_cycle is None:
            if not should_start_new_cycle(state, self._config.dca):
                self._logger.info(
                    "No active cycle and max_cycles reached. completed_cycles=%s",
                    state.completed_cycles,
                )
                return False

            plan = build_entry_order_plan(
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
                "Prepared initial entry side=%s amount=%s fill_price=%s dry_run=%s",
                plan.side,
                plan.amount,
                fill_price,
                self._config.runtime.dry_run,
            )
            if self._config.runtime.dry_run:
                return True

            order_id = self._require_order_id(plan, self._submit_order(plan))
            _, report = self._wait_for_fill(plan, order_id)
            state.start_cycle(
                symbol=plan.symbol,
                side=plan.side,
                when=now,
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_id=report.order_id,
                client_order_id=plan.client_order_id,
            )
            save_state(self._config.dca.state_file, state)
            return True

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
            plan = build_exit_order_plan(cycle=cycle, reason="take-profit")
            close_price = exit_price(snapshot, cycle.side)
            self._logger.info(
                "Take profit hit. exit_side=%s amount=%s close_price=%s dry_run=%s",
                plan.side,
                plan.amount,
                close_price,
                self._config.runtime.dry_run,
            )
            if self._config.runtime.dry_run:
                return True
            order_id = self._require_order_id(plan, self._submit_order(plan))
            _, report = self._wait_for_fill(plan, order_id)
            state.close_cycle(when=now, exit_reason=plan.reason, exit_price=close_price)
            save_state(self._config.dca.state_file, state)
            return True

        if should_stop_loss(cycle, snapshot, self._config.dca):
            plan = build_exit_order_plan(cycle=cycle, reason="stop-loss")
            close_price = exit_price(snapshot, cycle.side)
            self._logger.info(
                "Stop loss hit. exit_side=%s amount=%s close_price=%s dry_run=%s",
                plan.side,
                plan.amount,
                close_price,
                self._config.runtime.dry_run,
            )
            if self._config.runtime.dry_run:
                return True
            order_id = self._require_order_id(plan, self._submit_order(plan))
            _, report = self._wait_for_fill(plan, order_id)
            state.close_cycle(when=now, exit_reason=plan.reason, exit_price=close_price)
            save_state(self._config.dca.state_file, state)
            return True

        if should_place_safety_order(cycle, snapshot, self._config.dca):
            next_index = cycle.completed_safety_orders + 1
            quote_amount = current_quote_amount(self._config.dca, next_index)
            plan = build_entry_order_plan(
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
                "Safety trigger hit. index=%s amount=%s fill_price=%s dry_run=%s",
                next_index,
                plan.amount,
                fill_price,
                self._config.runtime.dry_run,
            )
            if self._config.runtime.dry_run:
                return True
            order_id = self._require_order_id(plan, self._submit_order(plan))
            _, report = self._wait_for_fill(plan, order_id)
            state.add_safety_fill(
                quantity=report.traded_size,
                price=report.avg_fill_price,
                order_id=report.order_id,
                client_order_id=plan.client_order_id,
            )
            save_state(self._config.dca.state_file, state)
            return True

        self._logger.info("No action taken this iteration.")
        return False

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                self._logger.exception("DCA iteration failed")
            time.sleep(self._config.runtime.poll_seconds)
