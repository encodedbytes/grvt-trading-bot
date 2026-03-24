from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
from decimal import Decimal

from .bot import DcaBot
from .momentum_bot import MomentumBot
from .grid_bot import GridBot
from .grid_recovery import GridOpenOrderSnapshot, reconcile_grid_state
from .grid_state import load_grid_state
from .grid_strategy import build_grid_levels
from .momentum_recovery import reconcile_momentum_state
from .momentum_state import load_momentum_state
from .momentum_strategy import build_indicator_snapshot, evaluate_entry, fixed_take_profit_price
from .config import load_config
from .exchange import GrvtExchange, TransientExchangeError
from .telegram import build_notifier, configured_symbol
from .recovery import reconcile_state
from .state import load_state
from .strategy import next_safety_trigger_price, stop_loss_price, take_profit_price


UTC = timezone.utc


def configured_strategy_type(config) -> str:
    return getattr(config, "strategy_type", "dca")


def build_exchange(config, logger: logging.Logger) -> GrvtExchange:
    return GrvtExchange(
        config.credentials,
        logger,
        private_auth_retry_attempts=config.runtime.private_auth_retry_attempts,
        private_auth_retry_backoff_seconds=config.runtime.private_auth_retry_backoff_seconds,
    )


def momentum_candle_limit(settings) -> int:
    return max(
        100,
        settings.ema_slow_period + settings.breakout_lookback + 5,
        (settings.adx_period * 2) + 5,
    )


def _normalize_grid_open_orders(exchange, settings) -> list[GridOpenOrderSnapshot]:
    instrument = exchange.get_instrument(settings.symbol)
    normalized: list[GridOpenOrderSnapshot] = []
    for payload in exchange.fetch_open_orders(symbol=settings.symbol):
        legs = payload.get("legs") or []
        leg = legs[0] if isinstance(legs, list) and legs else None
        if isinstance(leg, dict):
            symbol = str(
                leg.get("instrument") or payload.get("symbol") or payload.get("instrument") or ""
            )
            side = "buy" if leg.get("is_buying_asset") else "sell"
            price_value = leg.get("limit_price", payload.get("price"))
            state = payload.get("state") or {}
            book_size = state.get("book_size") if isinstance(state, dict) else None
            size_value = book_size[0] if isinstance(book_size, list) and book_size else book_size
            if size_value in (None, "", "0", 0):
                size_value = leg.get("size", payload.get("amount", payload.get("size")))
            client_order_id = (
                payload.get("metadata", {}).get("client_order_id")
                if isinstance(payload.get("metadata"), dict)
                else None
            )
            reduce_only = bool(payload.get("reduce_only", False))
        else:
            symbol = str(payload.get("symbol") or payload.get("instrument") or "")
            side = str(payload.get("side", "")).strip().lower()
            price_value = payload.get("price")
            size_value = (
                payload.get("remaining")
                if payload.get("remaining") not in (None, "", "0", 0)
                else payload.get("amount", payload.get("size"))
            )
            client_order_id = (
                str(payload.get("clientOrderId") or payload.get("client_order_id"))
                if payload.get("clientOrderId") or payload.get("client_order_id")
                else None
            )
            reduce_only = bool(
                payload.get("reduceOnly")
                if payload.get("reduceOnly") is not None
                else payload.get("reduce_only", False)
            )
        if symbol != settings.symbol or side not in {"buy", "sell"}:
            continue
        if price_value in (None, "", "0", 0) or size_value in (None, "", "0", 0):
            continue
        normalized.append(
            GridOpenOrderSnapshot(
                symbol=symbol,
                side=side,
                price=exchange.round_price(Decimal(str(price_value)), instrument.tick_size),
                size=Decimal(str(size_value)),
                order_id=str(payload["id"]) if payload.get("id") else None,
                client_order_id=str(client_order_id) if client_order_id else None,
                reduce_only=reduce_only,
            )
        )
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a GRVT DCA bot.")
    parser.add_argument("--config", required=True, help="Path to a TOML config file.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single DCA iteration instead of polling forever.",
    )
    parser.add_argument(
        "--instrument",
        help="Fetch and print market constraints for a GRVT instrument, for example ETH_USDT_Perp.",
    )
    parser.add_argument(
        "--position-config",
        action="store_true",
        help="Print the current symbol's GRVT initial leverage bounds and margin type.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print a compact status summary for the configured symbol and state file.",
    )
    parser.add_argument(
        "--thresholds",
        action="store_true",
        help="Print the current active cycle thresholds from the configured state file.",
    )
    parser.add_argument(
        "--recovery-status",
        action="store_true",
        help="Compare local state against the live exchange position and print the recovery decision.",
    )
    parser.add_argument(
        "--notify-test",
        action="store_true",
        help="Send a Telegram test notification using the configured notifier.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, config.runtime.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.instrument:
        exchange = build_exchange(config, logging.getLogger("gravity_dca"))
        instrument = exchange.get_instrument(args.instrument)
        snapshot = exchange.get_market_snapshot(args.instrument)
        print(f"symbol={instrument.symbol}")
        print(f"tick_size={instrument.tick_size}")
        print(f"min_size={instrument.min_size}")
        print(f"min_notional={instrument.min_notional}")
        print(f"base_decimals={instrument.base_decimals}")
        print(f"best_bid={snapshot.bid}")
        print(f"best_ask={snapshot.ask}")
        print(f"mid_price={snapshot.mid}")
        return

    if args.position_config:
        exchange = build_exchange(config, logging.getLogger("gravity_dca"))
        details = exchange.get_initial_position_details(configured_symbol(config))
        print(f"symbol={details.symbol}")
        print(f"leverage={details.leverage if details.leverage is not None else ''}")
        print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
        print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
        print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
        return

    if args.status:
        if configured_strategy_type(config) == "momentum":
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            state = load_momentum_state(config.momentum.state_file)
            print(f"state_file={config.momentum.state_file}")
            print(f"symbol={config.momentum.symbol}")
            print(f"configured_side={config.momentum.side}")
            print(f"order_type={config.momentum.order_type}")
            print(f"dry_run={'true' if config.runtime.dry_run else 'false'}")
            details = exchange.get_initial_position_details(config.momentum.symbol)
            print(f"initial_leverage={details.leverage if details.leverage is not None else ''}")
            print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
            print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
            print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
            try:
                candles = exchange.get_candles(
                    config.momentum.symbol,
                    timeframe=config.momentum.timeframe,
                    limit=momentum_candle_limit(config.momentum),
                )
                exchange_position = exchange.get_open_position(config.momentum.symbol)
                exchange_fills = (
                    exchange.get_recent_fills(config.momentum.symbol)
                    if exchange_position is not None
                    else None
                )
                decision = reconcile_momentum_state(
                    state=state,
                    settings=config.momentum,
                    symbol=config.momentum.symbol,
                    exchange_position=exchange_position,
                    exchange_fills=exchange_fills,
                    candles=candles,
                    when=datetime.now(tz=UTC),
                )
                print(f"recovery_decision={decision.action}")
                print(f"recovery_message={decision.message}")
                print(
                    f"reconstruction_attempted={'true' if decision.reconstruction_attempted else 'false'}"
                )
                print(
                    f"reconstruction_succeeded={'true' if decision.reconstruction_succeeded else 'false'}"
                )
                indicator_snapshot = build_indicator_snapshot(candles, config.momentum)
            except TransientExchangeError as exc:
                print("recovery_decision=recovery-unavailable")
                print(f"recovery_message={exc}")
                exchange_position = None
                indicator_snapshot = None
            print(f"exchange_position={'true' if exchange_position is not None else 'false'}")
            if state.active_position is None:
                print("active_position=false")
                entry_decision = evaluate_entry(candles, config.momentum, state)
                print(f"entry_decision={'enter' if entry_decision.should_enter else 'skip'}")
                print(f"entry_reason={entry_decision.reason}")
                snapshot = entry_decision.indicator_snapshot or indicator_snapshot
                if snapshot is not None:
                    print(f"latest_close={snapshot.close_price}")
                    print(f"breakout_level={snapshot.breakout_level}")
                    print(f"ema_fast={snapshot.ema_fast}")
                    print(f"ema_slow={snapshot.ema_slow}")
                    print(f"adx={snapshot.adx}")
                    print(f"atr={snapshot.atr}")
                    print(f"atr_percent={snapshot.atr_percent}")
                if entry_decision.initial_stop_price is not None:
                    print(f"initial_stop_price={entry_decision.initial_stop_price}")
                if entry_decision.trailing_stop_price is not None:
                    print(f"trailing_stop_price={entry_decision.trailing_stop_price}")
                print(f"completed_cycles={state.completed_cycles}")
                if state.last_closed_position is not None:
                    print(f"last_exit_reason={state.last_closed_position.exit_reason}")
                    print(f"last_exit_price={state.last_closed_position.exit_price}")
                    print(
                        f"last_realized_pnl_estimate={state.last_closed_position.realized_pnl_estimate}"
                    )
                return
            position = state.active_position
            print("active_position=true")
            print(f"position_side={position.side}")
            print(f"average_entry_price={position.average_entry_price}")
            print(f"total_quantity={position.total_quantity}")
            print(
                "highest_price_since_entry="
                f"{position.highest_price_since_entry if position.highest_price_since_entry is not None else ''}"
            )
            print(f"initial_stop_price={position.initial_stop_price if position.initial_stop_price is not None else ''}")
            print(
                f"trailing_stop_price={position.trailing_stop_price if position.trailing_stop_price is not None else ''}"
            )
            print(f"breakout_level={position.breakout_level if position.breakout_level is not None else ''}")
            print(
                "fixed_take_profit_price="
                f"{fixed_take_profit_price(position, config.momentum) if fixed_take_profit_price(position, config.momentum) is not None else ''}"
            )
            if indicator_snapshot is not None:
                print(f"latest_close={indicator_snapshot.close_price}")
                print(f"ema_fast={indicator_snapshot.ema_fast}")
                print(f"ema_slow={indicator_snapshot.ema_slow}")
                print(f"adx={indicator_snapshot.adx}")
                print(f"atr={indicator_snapshot.atr}")
                print(f"atr_percent={indicator_snapshot.atr_percent}")
            print(f"completed_cycles={state.completed_cycles}")
            if state.last_closed_position is not None:
                print(f"last_exit_reason={state.last_closed_position.exit_reason}")
                print(f"last_exit_price={state.last_closed_position.exit_price}")
                print(
                    f"last_realized_pnl_estimate={state.last_closed_position.realized_pnl_estimate}"
                )
            return
        if configured_strategy_type(config) == "grid":
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            state = load_grid_state(config.grid.state_file)
            print(f"state_file={config.grid.state_file}")
            print(f"symbol={config.grid.symbol}")
            print(f"configured_side={config.grid.side}")
            print(f"order_type={config.grid.order_type}")
            print(f"dry_run={'true' if config.runtime.dry_run else 'false'}")
            details = exchange.get_initial_position_details(config.grid.symbol)
            print(f"initial_leverage={details.leverage if details.leverage is not None else ''}")
            print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
            print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
            print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
            try:
                open_orders = _normalize_grid_open_orders(exchange, config.grid)
                exchange_position = exchange.get_open_position(config.grid.symbol)
                fills = exchange.get_recent_fills(config.grid.symbol) if exchange_position is not None or open_orders else []
                decision = reconcile_grid_state(
                    state=state,
                    settings=config.grid,
                    open_orders=open_orders,
                    exchange_position=exchange_position,
                    fills=fills,
                    when=datetime.now(tz=UTC),
                )
                print(f"recovery_decision={decision.action}")
                print(f"recovery_message={decision.message}")
                state = decision.recovered_state
            except TransientExchangeError as exc:
                print("recovery_decision=recovery-unavailable")
                print(f"recovery_message={exc}")
                open_orders = []
                exchange_position = None
            active_buy_orders = sum(1 for level in state.levels if level.status == "buy_open")
            active_inventory_levels = sum(
                1 for level in state.levels if level.status in {"filled_inventory", "sell_open"}
            )
            print(f"exchange_position={'true' if exchange_position is not None else 'false'}")
            print(f"open_buy_orders={active_buy_orders}")
            print(f"inventory_levels={active_inventory_levels}")
            print(f"completed_round_trips={state.completed_round_trips}")
            print(f"price_band_low={config.grid.price_band_low}")
            print(f"price_band_high={config.grid.price_band_high}")
            print(f"grid_levels={config.grid.grid_levels}")
            print(f"spacing_mode={config.grid.spacing_mode}")
            print(f"seed_enabled={'true' if config.grid.seed_enabled else 'false'}")
            print(f"reseed_when_flat={'true' if config.grid.reseed_when_flat else 'false'}")
            print(f"max_active_buy_orders={config.grid.max_active_buy_orders}")
            print(f"max_inventory_levels={config.grid.max_inventory_levels}")
            return
        exchange = build_exchange(config, logging.getLogger("gravity_dca"))
        state = load_state(config.dca.state_file)
        print(f"state_file={config.dca.state_file}")
        print(f"symbol={config.dca.symbol}")
        print(f"configured_side={config.dca.side}")
        print(f"order_type={config.dca.order_type}")
        print(f"dry_run={'true' if config.runtime.dry_run else 'false'}")
        details = exchange.get_initial_position_details(config.dca.symbol)
        print(f"initial_leverage={details.leverage if details.leverage is not None else ''}")
        print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
        print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
        print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
        try:
            exchange_position = exchange.get_open_position(config.dca.symbol)
            exchange_fills = (
                exchange.get_recent_fills(config.dca.symbol) if exchange_position is not None else None
            )
            decision = reconcile_state(
                state=state,
                settings=config.dca,
                symbol=config.dca.symbol,
                exchange_position=exchange_position,
                exchange_fills=exchange_fills,
                when=datetime.now(tz=UTC),
            )
            print(f"recovery_decision={decision.action}")
            print(f"recovery_message={decision.message}")
            print(
                f"reconstruction_attempted={'true' if decision.reconstruction_attempted else 'false'}"
            )
            print(
                f"reconstruction_succeeded={'true' if decision.reconstruction_succeeded else 'false'}"
            )
        except TransientExchangeError as exc:
            print("recovery_decision=recovery-unavailable")
            print(f"recovery_message={exc}")
            exchange_position = None
        print(f"exchange_position={'true' if exchange_position is not None else 'false'}")
        if state.active_cycle is None:
            print("active_cycle=false")
            print(f"completed_cycles={state.completed_cycles}")
            if state.last_closed_cycle is not None:
                print(f"last_exit_reason={state.last_closed_cycle.exit_reason}")
                print(f"last_exit_price={state.last_closed_cycle.exit_price}")
                print(f"last_realized_pnl_estimate={state.last_closed_cycle.realized_pnl_estimate}")
            return
        cycle = state.active_cycle
        print("active_cycle=true")
        print(f"cycle_side={cycle.side}")
        print(f"average_entry_price={cycle.average_entry_price}")
        print(f"total_quantity={cycle.total_quantity}")
        print(f"completed_safety_orders={cycle.completed_safety_orders}")
        print(f"take_profit_price={take_profit_price(cycle, config.dca)}")
        stop_price = stop_loss_price(cycle, config.dca)
        print(f"stop_loss_price={stop_price if stop_price is not None else ''}")
        next_trigger = next_safety_trigger_price(cycle, config.dca)
        print(f"next_safety_trigger_price={next_trigger if next_trigger is not None else ''}")
        print(f"completed_cycles={state.completed_cycles}")
        if state.last_closed_cycle is not None:
            print(f"last_exit_reason={state.last_closed_cycle.exit_reason}")
            print(f"last_exit_price={state.last_closed_cycle.exit_price}")
            print(f"last_realized_pnl_estimate={state.last_closed_cycle.realized_pnl_estimate}")
        return

    if args.thresholds:
        if configured_strategy_type(config) == "momentum":
            state = load_momentum_state(config.momentum.state_file)
            if state.active_position is None:
                print("active_position=false")
                print(f"state_file={config.momentum.state_file}")
                return
            position = state.active_position
            print("active_position=true")
            print(f"state_file={config.momentum.state_file}")
            print(f"symbol={position.symbol}")
            print(f"side={position.side}")
            print(f"average_entry_price={position.average_entry_price}")
            print(f"total_quantity={position.total_quantity}")
            print(
                "highest_price_since_entry="
                f"{position.highest_price_since_entry if position.highest_price_since_entry is not None else ''}"
            )
            print(f"initial_stop_price={position.initial_stop_price if position.initial_stop_price is not None else ''}")
            print(
                f"trailing_stop_price={position.trailing_stop_price if position.trailing_stop_price is not None else ''}"
            )
            print(
                "fixed_take_profit_price="
                f"{fixed_take_profit_price(position, config.momentum) if fixed_take_profit_price(position, config.momentum) is not None else ''}"
            )
            return
        if configured_strategy_type(config) == "grid":
            state = load_grid_state(config.grid.state_file)
            print(f"state_file={config.grid.state_file}")
            print(f"symbol={config.grid.symbol}")
            print(f"side={config.grid.side}")
            print(f"price_band_low={config.grid.price_band_low}")
            print(f"price_band_high={config.grid.price_band_high}")
            print(f"grid_levels={config.grid.grid_levels}")
            print(f"spacing_mode={config.grid.spacing_mode}")
            print(f"seed_enabled={'true' if config.grid.seed_enabled else 'false'}")
            print(f"reseed_when_flat={'true' if config.grid.reseed_when_flat else 'false'}")
            print(
                "active_buy_levels="
                + ",".join(str(level.level_index) for level in state.levels if level.status == "buy_open")
            )
            print(
                "inventory_levels="
                + ",".join(
                    str(level.level_index)
                    for level in state.levels
                    if level.status in {"filled_inventory", "sell_open"}
                )
            )
            return
        state = load_state(config.dca.state_file)
        if state.active_cycle is None:
            print("active_cycle=false")
            print(f"state_file={config.dca.state_file}")
            return
        cycle = state.active_cycle
        print("active_cycle=true")
        print(f"state_file={config.dca.state_file}")
        print(f"symbol={cycle.symbol}")
        print(f"side={cycle.side}")
        print(f"average_entry_price={cycle.average_entry_price}")
        print(f"total_quantity={cycle.total_quantity}")
        print(f"completed_safety_orders={cycle.completed_safety_orders}")
        print(f"take_profit_price={take_profit_price(cycle, config.dca)}")
        stop_price = stop_loss_price(cycle, config.dca)
        print(f"stop_loss_price={stop_price if stop_price is not None else ''}")
        next_trigger = next_safety_trigger_price(cycle, config.dca)
        print(f"next_safety_trigger_price={next_trigger if next_trigger is not None else ''}")
        return

    if args.recovery_status:
        if configured_strategy_type(config) == "momentum":
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            state = load_momentum_state(config.momentum.state_file)
            try:
                candles = exchange.get_candles(
                    config.momentum.symbol,
                    timeframe=config.momentum.timeframe,
                    limit=momentum_candle_limit(config.momentum),
                )
                exchange_position = exchange.get_open_position(config.momentum.symbol)
                exchange_fills = (
                    exchange.get_recent_fills(config.momentum.symbol)
                    if exchange_position is not None
                    else None
                )
            except TransientExchangeError as exc:
                print(f"state_file={config.momentum.state_file}")
                print(f"symbol={config.momentum.symbol}")
                print(f"local_active_position={'true' if state.active_position is not None else 'false'}")
                print("exchange_position=unknown")
                print("decision=recovery-unavailable")
                print(f"message={exc}")
                return
            decision = reconcile_momentum_state(
                state=state,
                settings=config.momentum,
                symbol=config.momentum.symbol,
                exchange_position=exchange_position,
                exchange_fills=exchange_fills,
                candles=candles,
                when=datetime.now(tz=UTC),
            )
            print(f"state_file={config.momentum.state_file}")
            print(f"symbol={config.momentum.symbol}")
            print(f"local_active_position={'true' if state.active_position is not None else 'false'}")
            print(f"exchange_position={'true' if exchange_position is not None else 'false'}")
            print(f"decision={decision.action}")
            print(f"message={decision.message}")
            print(
                f"reconstruction_attempted={'true' if decision.reconstruction_attempted else 'false'}"
            )
            print(
                f"reconstruction_succeeded={'true' if decision.reconstruction_succeeded else 'false'}"
            )
            if decision.reconstruction_message is not None:
                print(f"reconstruction_message={decision.reconstruction_message}")
            if decision.recovered_position is not None:
                print(f"reconstructed_trailing_stop_price={decision.recovered_position.trailing_stop_price}")
                print(
                    "reconstructed_highest_price_since_entry="
                    f"{decision.recovered_position.highest_price_since_entry}"
                )
            return
        if configured_strategy_type(config) == "grid":
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            state = load_grid_state(config.grid.state_file)
            try:
                open_orders = _normalize_grid_open_orders(exchange, config.grid)
                exchange_position = exchange.get_open_position(config.grid.symbol)
                fills = exchange.get_recent_fills(config.grid.symbol) if exchange_position is not None or open_orders else []
            except TransientExchangeError as exc:
                print(f"state_file={config.grid.state_file}")
                print(f"symbol={config.grid.symbol}")
                print(f"local_grid_initialized={'true' if state.grid is not None else 'false'}")
                print("exchange_position=unknown")
                print("decision=recovery-unavailable")
                print(f"message={exc}")
                return
            decision = reconcile_grid_state(
                state=state,
                settings=config.grid,
                open_orders=open_orders,
                exchange_position=exchange_position,
                fills=fills,
                when=datetime.now(tz=UTC),
            )
            recovered = decision.recovered_state
            print(f"state_file={config.grid.state_file}")
            print(f"symbol={config.grid.symbol}")
            print(f"local_grid_initialized={'true' if state.grid is not None else 'false'}")
            print(f"exchange_position={'true' if exchange_position is not None else 'false'}")
            print(f"open_orders={len(open_orders)}")
            print(f"decision={decision.action}")
            print(f"message={decision.message}")
            print(
                "recovered_active_buy_orders="
                f"{sum(1 for level in recovered.levels if level.status == 'buy_open')}"
            )
            print(
                "recovered_inventory_levels="
                f"{sum(1 for level in recovered.levels if level.status in {'filled_inventory', 'sell_open'})}"
            )
            return
        exchange = build_exchange(config, logging.getLogger("gravity_dca"))
        state = load_state(config.dca.state_file)
        try:
            exchange_position = exchange.get_open_position(config.dca.symbol)
            exchange_fills = (
                exchange.get_recent_fills(config.dca.symbol) if exchange_position is not None else None
            )
        except TransientExchangeError as exc:
            print(f"state_file={config.dca.state_file}")
            print(f"symbol={config.dca.symbol}")
            print(f"local_active_cycle={'true' if state.active_cycle is not None else 'false'}")
            print("exchange_position=unknown")
            print("decision=recovery-unavailable")
            print(f"message={exc}")
            return
        decision = reconcile_state(
            state=state,
            settings=config.dca,
            symbol=config.dca.symbol,
            exchange_position=exchange_position,
            exchange_fills=exchange_fills,
            when=datetime.now(tz=UTC),
        )
        print(f"state_file={config.dca.state_file}")
        print(f"symbol={config.dca.symbol}")
        print(f"local_active_cycle={'true' if state.active_cycle is not None else 'false'}")
        print(f"exchange_position={'true' if exchange_position is not None else 'false'}")
        print(f"decision={decision.action}")
        print(f"message={decision.message}")
        print(f"reconstruction_attempted={'true' if decision.reconstruction_attempted else 'false'}")
        print(f"reconstruction_succeeded={'true' if decision.reconstruction_succeeded else 'false'}")
        if decision.reconstruction_message is not None:
            print(f"reconstruction_message={decision.reconstruction_message}")
        if decision.recovered_cycle is not None:
            print(
                "reconstructed_completed_safety_orders="
                f"{decision.recovered_cycle.completed_safety_orders}"
            )
        return

    if args.notify_test:
        notifier = build_notifier(config, logging.getLogger("gravity_dca"))
        result = notifier.send_test_message(config)
        print(f"telegram_enabled={'true' if config.telegram.enabled else 'false'}")
        print(f"notification_sent={'true' if result.delivered else 'false'}")
        print(f"detail={result.detail}")
        return

    if configured_strategy_type(config) == "momentum":
        bot = MomentumBot(config, logging.getLogger("gravity_dca"))
    elif configured_strategy_type(config) == "grid":
        bot = GridBot(config, logging.getLogger("gravity_dca"))
    else:
        bot = DcaBot(config, logging.getLogger("gravity_dca"))
    if args.once:
        bot.run_once()
        return
    bot.run_forever()
