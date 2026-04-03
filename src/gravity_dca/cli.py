from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from .bot import DcaBot
from .config import load_config
from .exchange import GrvtExchange, TransientExchangeError
from .grid_bot import GridBot
from .grid_recovery import normalize_grid_open_orders, reconcile_grid_state
from .grid_state import load_grid_state
from .momentum_bot import MomentumBot
from .momentum_recovery import reconcile_momentum_state
from .momentum_state import load_momentum_state
from .momentum_strategy import build_indicator_snapshot, evaluate_entry, fixed_take_profit_price
from .recovery import reconcile_state
from .state import load_state
from .strategy import next_safety_trigger_price, stop_loss_price, take_profit_price
from .telegram import build_notifier, configured_symbol

UTC = timezone.utc


def _require_dca_settings(config):
    if config.dca is None:
        raise ValueError("DCA config is required")
    return config.dca


def _require_momentum_settings(config):
    if config.momentum is None:
        raise ValueError("Momentum config is required")
    return config.momentum


def _require_grid_settings(config):
    if config.grid is None:
        raise ValueError("Grid config is required")
    return config.grid


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
            momentum_settings = _require_momentum_settings(config)
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            momentum_state = load_momentum_state(momentum_settings.state_file)
            print(f"state_file={momentum_settings.state_file}")
            print(f"symbol={momentum_settings.symbol}")
            print(f"configured_side={momentum_settings.side}")
            print(f"order_type={momentum_settings.order_type}")
            print(f"dry_run={'true' if config.runtime.dry_run else 'false'}")
            details = exchange.get_initial_position_details(momentum_settings.symbol)
            print(f"initial_leverage={details.leverage if details.leverage is not None else ''}")
            print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
            print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
            print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
            try:
                candles = exchange.get_candles(
                    momentum_settings.symbol,
                    timeframe=momentum_settings.timeframe,
                    limit=momentum_candle_limit(momentum_settings),
                )
                momentum_exchange_position = exchange.get_open_position(momentum_settings.symbol)
                momentum_exchange_fills = (
                    exchange.get_recent_fills(momentum_settings.symbol)
                    if momentum_exchange_position is not None
                    else None
                )
                momentum_decision = reconcile_momentum_state(
                    state=momentum_state,
                    settings=momentum_settings,
                    symbol=momentum_settings.symbol,
                    exchange_position=momentum_exchange_position,
                    exchange_fills=momentum_exchange_fills,
                    candles=candles,
                    when=datetime.now(tz=UTC),
                )
                print(f"recovery_decision={momentum_decision.action}")
                print(f"recovery_message={momentum_decision.message}")
                print(
                    "reconstruction_attempted="
                    f"{'true' if momentum_decision.reconstruction_attempted else 'false'}"
                )
                print(
                    "reconstruction_succeeded="
                    f"{'true' if momentum_decision.reconstruction_succeeded else 'false'}"
                )
                momentum_indicator_snapshot = build_indicator_snapshot(candles, momentum_settings)
            except TransientExchangeError as exc:
                print("recovery_decision=recovery-unavailable")
                print(f"recovery_message={exc}")
                momentum_exchange_position = None
                momentum_indicator_snapshot = None
            print(
                f"exchange_position={'true' if momentum_exchange_position is not None else 'false'}"
            )
            if momentum_state.active_position is None:
                print("active_position=false")
                entry_decision = evaluate_entry(candles, momentum_settings, momentum_state)
                print(f"entry_decision={'enter' if entry_decision.should_enter else 'skip'}")
                print(f"entry_reason={entry_decision.reason}")
                entry_snapshot = entry_decision.indicator_snapshot or momentum_indicator_snapshot
                if entry_snapshot is not None:
                    print(f"latest_close={entry_snapshot.close_price}")
                    print(f"breakout_level={entry_snapshot.breakout_level}")
                    print(f"ema_fast={entry_snapshot.ema_fast}")
                    print(f"ema_slow={entry_snapshot.ema_slow}")
                    print(f"adx={entry_snapshot.adx}")
                    print(f"atr={entry_snapshot.atr}")
                    print(f"atr_percent={entry_snapshot.atr_percent}")
                if entry_decision.initial_stop_price is not None:
                    print(f"initial_stop_price={entry_decision.initial_stop_price}")
                if entry_decision.trailing_stop_price is not None:
                    print(f"trailing_stop_price={entry_decision.trailing_stop_price}")
                print(f"completed_cycles={momentum_state.completed_cycles}")
                if momentum_state.last_closed_position is not None:
                    print(f"last_exit_reason={momentum_state.last_closed_position.exit_reason}")
                    print(f"last_exit_price={momentum_state.last_closed_position.exit_price}")
                    print(
                        "last_realized_pnl_estimate="
                        f"{momentum_state.last_closed_position.realized_pnl_estimate}"
                    )
                return
            position = momentum_state.active_position
            assert position is not None
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
                f"{fixed_take_profit_price(position, momentum_settings) if fixed_take_profit_price(position, momentum_settings) is not None else ''}"
            )
            if momentum_indicator_snapshot is not None:
                print(f"latest_close={momentum_indicator_snapshot.close_price}")
                print(f"ema_fast={momentum_indicator_snapshot.ema_fast}")
                print(f"ema_slow={momentum_indicator_snapshot.ema_slow}")
                print(f"adx={momentum_indicator_snapshot.adx}")
                print(f"atr={momentum_indicator_snapshot.atr}")
                print(f"atr_percent={momentum_indicator_snapshot.atr_percent}")
            print(f"completed_cycles={momentum_state.completed_cycles}")
            if momentum_state.last_closed_position is not None:
                print(f"last_exit_reason={momentum_state.last_closed_position.exit_reason}")
                print(f"last_exit_price={momentum_state.last_closed_position.exit_price}")
                print(
                    "last_realized_pnl_estimate="
                    f"{momentum_state.last_closed_position.realized_pnl_estimate}"
                )
            return
        if configured_strategy_type(config) == "grid":
            grid_settings = _require_grid_settings(config)
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            grid_state = load_grid_state(grid_settings.state_file)
            print(f"state_file={grid_settings.state_file}")
            print(f"symbol={grid_settings.symbol}")
            print(f"configured_side={grid_settings.side}")
            print(f"order_type={grid_settings.order_type}")
            print(f"dry_run={'true' if config.runtime.dry_run else 'false'}")
            details = exchange.get_initial_position_details(grid_settings.symbol)
            print(f"initial_leverage={details.leverage if details.leverage is not None else ''}")
            print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
            print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
            print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
            try:
                instrument = exchange.get_instrument(grid_settings.symbol)
                open_orders = normalize_grid_open_orders(
                    exchange.fetch_open_orders(symbol=grid_settings.symbol),
                    symbol=grid_settings.symbol,
                    tick_size=instrument.tick_size,
                    round_price=exchange.round_price,
                )
                grid_exchange_position = exchange.get_open_position(grid_settings.symbol)
                grid_fills = (
                    exchange.get_recent_fills(grid_settings.symbol)
                    if grid_exchange_position is not None or open_orders
                    else []
                )
                grid_decision = reconcile_grid_state(
                    state=grid_state,
                    settings=grid_settings,
                    open_orders=open_orders,
                    exchange_position=grid_exchange_position,
                    fills=grid_fills,
                    when=datetime.now(tz=UTC),
                )
                print(f"recovery_decision={grid_decision.action}")
                print(f"recovery_message={grid_decision.message}")
                grid_state = grid_decision.recovered_state
            except TransientExchangeError as exc:
                print("recovery_decision=recovery-unavailable")
                print(f"recovery_message={exc}")
                open_orders = []
                grid_exchange_position = None
            active_buy_orders = sum(1 for level in grid_state.levels if level.status == "buy_open")
            active_inventory_levels = sum(
                1 for level in grid_state.levels if level.status in {"filled_inventory", "sell_open"}
            )
            print(f"exchange_position={'true' if grid_exchange_position is not None else 'false'}")
            print(f"open_buy_orders={active_buy_orders}")
            print(f"inventory_levels={active_inventory_levels}")
            print(f"completed_round_trips={grid_state.completed_round_trips}")
            print(f"price_band_low={grid_settings.price_band_low}")
            print(f"price_band_high={grid_settings.price_band_high}")
            print(f"grid_levels={grid_settings.grid_levels}")
            print(f"spacing_mode={grid_settings.spacing_mode}")
            print(f"seed_enabled={'true' if grid_settings.seed_enabled else 'false'}")
            print(f"reseed_when_flat={'true' if grid_settings.reseed_when_flat else 'false'}")
            print(f"max_active_buy_orders={grid_settings.max_active_buy_orders}")
            print(f"max_inventory_levels={grid_settings.max_inventory_levels}")
            return
        dca_settings = _require_dca_settings(config)
        exchange = build_exchange(config, logging.getLogger("gravity_dca"))
        dca_state = load_state(dca_settings.state_file)
        print(f"state_file={dca_settings.state_file}")
        print(f"symbol={dca_settings.symbol}")
        print(f"configured_side={dca_settings.side}")
        print(f"order_type={dca_settings.order_type}")
        print(f"dry_run={'true' if config.runtime.dry_run else 'false'}")
        details = exchange.get_initial_position_details(dca_settings.symbol)
        print(f"initial_leverage={details.leverage if details.leverage is not None else ''}")
        print(f"min_leverage={details.min_leverage if details.min_leverage is not None else ''}")
        print(f"max_leverage={details.max_leverage if details.max_leverage is not None else ''}")
        print(f"margin_type={details.margin_type if details.margin_type is not None else ''}")
        try:
            dca_exchange_position = exchange.get_open_position(dca_settings.symbol)
            exchange_fills = (
                exchange.get_recent_fills(dca_settings.symbol)
                if dca_exchange_position is not None
                else None
            )
            dca_decision = reconcile_state(
                state=dca_state,
                settings=dca_settings,
                symbol=dca_settings.symbol,
                exchange_position=dca_exchange_position,
                exchange_fills=exchange_fills,
                when=datetime.now(tz=UTC),
            )
            print(f"recovery_decision={dca_decision.action}")
            print(f"recovery_message={dca_decision.message}")
            print(
                f"reconstruction_attempted={'true' if dca_decision.reconstruction_attempted else 'false'}"
            )
            print(
                f"reconstruction_succeeded={'true' if dca_decision.reconstruction_succeeded else 'false'}"
            )
        except TransientExchangeError as exc:
            print("recovery_decision=recovery-unavailable")
            print(f"recovery_message={exc}")
            dca_exchange_position = None
        print(f"exchange_position={'true' if dca_exchange_position is not None else 'false'}")
        if dca_state.active_cycle is None:
            print("active_cycle=false")
            print(f"completed_cycles={dca_state.completed_cycles}")
            if dca_state.last_closed_cycle is not None:
                print(f"last_exit_reason={dca_state.last_closed_cycle.exit_reason}")
                print(f"last_exit_price={dca_state.last_closed_cycle.exit_price}")
                print(f"last_realized_pnl_estimate={dca_state.last_closed_cycle.realized_pnl_estimate}")
            return
        cycle = dca_state.active_cycle
        assert cycle is not None
        print("active_cycle=true")
        print(f"cycle_side={cycle.side}")
        print(f"average_entry_price={cycle.average_entry_price}")
        print(f"total_quantity={cycle.total_quantity}")
        print(f"completed_safety_orders={cycle.completed_safety_orders}")
        print(f"take_profit_price={take_profit_price(cycle, dca_settings)}")
        stop_price = stop_loss_price(cycle, dca_settings)
        print(f"stop_loss_price={stop_price if stop_price is not None else ''}")
        next_trigger = next_safety_trigger_price(cycle, dca_settings)
        print(f"next_safety_trigger_price={next_trigger if next_trigger is not None else ''}")
        print(f"completed_cycles={dca_state.completed_cycles}")
        if dca_state.last_closed_cycle is not None:
            print(f"last_exit_reason={dca_state.last_closed_cycle.exit_reason}")
            print(f"last_exit_price={dca_state.last_closed_cycle.exit_price}")
            print(f"last_realized_pnl_estimate={dca_state.last_closed_cycle.realized_pnl_estimate}")
        return

    if args.thresholds:
        if configured_strategy_type(config) == "momentum":
            momentum_settings = _require_momentum_settings(config)
            momentum_state = load_momentum_state(momentum_settings.state_file)
            if momentum_state.active_position is None:
                print("active_position=false")
                print(f"state_file={momentum_settings.state_file}")
                return
            position = momentum_state.active_position
            assert position is not None
            print("active_position=true")
            print(f"state_file={momentum_settings.state_file}")
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
                f"{fixed_take_profit_price(position, momentum_settings) if fixed_take_profit_price(position, momentum_settings) is not None else ''}"
            )
            return
        if configured_strategy_type(config) == "grid":
            grid_settings = _require_grid_settings(config)
            grid_state = load_grid_state(grid_settings.state_file)
            print(f"state_file={grid_settings.state_file}")
            print(f"symbol={grid_settings.symbol}")
            print(f"side={grid_settings.side}")
            print(f"price_band_low={grid_settings.price_band_low}")
            print(f"price_band_high={grid_settings.price_band_high}")
            print(f"grid_levels={grid_settings.grid_levels}")
            print(f"spacing_mode={grid_settings.spacing_mode}")
            print(f"seed_enabled={'true' if grid_settings.seed_enabled else 'false'}")
            print(f"reseed_when_flat={'true' if grid_settings.reseed_when_flat else 'false'}")
            print(
                "active_buy_levels="
                + ",".join(
                    str(level.level_index) for level in grid_state.levels if level.status == "buy_open"
                )
            )
            print(
                "inventory_levels="
                + ",".join(
                    str(level.level_index)
                    for level in grid_state.levels
                    if level.status in {"filled_inventory", "sell_open"}
                )
            )
            return
        dca_settings = _require_dca_settings(config)
        dca_state = load_state(dca_settings.state_file)
        if dca_state.active_cycle is None:
            print("active_cycle=false")
            print(f"state_file={dca_settings.state_file}")
            return
        cycle = dca_state.active_cycle
        assert cycle is not None
        print("active_cycle=true")
        print(f"state_file={dca_settings.state_file}")
        print(f"symbol={cycle.symbol}")
        print(f"side={cycle.side}")
        print(f"average_entry_price={cycle.average_entry_price}")
        print(f"total_quantity={cycle.total_quantity}")
        print(f"completed_safety_orders={cycle.completed_safety_orders}")
        print(f"take_profit_price={take_profit_price(cycle, dca_settings)}")
        stop_price = stop_loss_price(cycle, dca_settings)
        print(f"stop_loss_price={stop_price if stop_price is not None else ''}")
        next_trigger = next_safety_trigger_price(cycle, dca_settings)
        print(f"next_safety_trigger_price={next_trigger if next_trigger is not None else ''}")
        return

    if args.recovery_status:
        if configured_strategy_type(config) == "momentum":
            momentum_settings = _require_momentum_settings(config)
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            momentum_state = load_momentum_state(momentum_settings.state_file)
            try:
                candles = exchange.get_candles(
                    momentum_settings.symbol,
                    timeframe=momentum_settings.timeframe,
                    limit=momentum_candle_limit(momentum_settings),
                )
                momentum_exchange_position = exchange.get_open_position(momentum_settings.symbol)
                momentum_exchange_fills = (
                    exchange.get_recent_fills(momentum_settings.symbol)
                    if momentum_exchange_position is not None
                    else None
                )
            except TransientExchangeError as exc:
                print(f"state_file={momentum_settings.state_file}")
                print(f"symbol={momentum_settings.symbol}")
                print(
                    "local_active_position="
                    f"{'true' if momentum_state.active_position is not None else 'false'}"
                )
                print("exchange_position=unknown")
                print("decision=recovery-unavailable")
                print(f"message={exc}")
                return
            momentum_decision = reconcile_momentum_state(
                state=momentum_state,
                settings=momentum_settings,
                symbol=momentum_settings.symbol,
                exchange_position=momentum_exchange_position,
                exchange_fills=momentum_exchange_fills,
                candles=candles,
                when=datetime.now(tz=UTC),
            )
            print(f"state_file={momentum_settings.state_file}")
            print(f"symbol={momentum_settings.symbol}")
            print(
                f"local_active_position={'true' if momentum_state.active_position is not None else 'false'}"
            )
            print(
                f"exchange_position={'true' if momentum_exchange_position is not None else 'false'}"
            )
            print(f"decision={momentum_decision.action}")
            print(f"message={momentum_decision.message}")
            print(
                f"reconstruction_attempted={'true' if momentum_decision.reconstruction_attempted else 'false'}"
            )
            print(
                f"reconstruction_succeeded={'true' if momentum_decision.reconstruction_succeeded else 'false'}"
            )
            if momentum_decision.reconstruction_message is not None:
                print(f"reconstruction_message={momentum_decision.reconstruction_message}")
            if momentum_decision.recovered_position is not None:
                print(
                    "reconstructed_trailing_stop_price="
                    f"{momentum_decision.recovered_position.trailing_stop_price}"
                )
                print(
                    "reconstructed_highest_price_since_entry="
                    f"{momentum_decision.recovered_position.highest_price_since_entry}"
                )
            return
        if configured_strategy_type(config) == "grid":
            grid_settings = _require_grid_settings(config)
            exchange = build_exchange(config, logging.getLogger("gravity_dca"))
            grid_state = load_grid_state(grid_settings.state_file)
            try:
                instrument = exchange.get_instrument(grid_settings.symbol)
                open_orders = normalize_grid_open_orders(
                    exchange.fetch_open_orders(symbol=grid_settings.symbol),
                    symbol=grid_settings.symbol,
                    tick_size=instrument.tick_size,
                    round_price=exchange.round_price,
                )
                grid_exchange_position = exchange.get_open_position(grid_settings.symbol)
                grid_fills = (
                    exchange.get_recent_fills(grid_settings.symbol)
                    if grid_exchange_position is not None or open_orders
                    else []
                )
            except TransientExchangeError as exc:
                print(f"state_file={grid_settings.state_file}")
                print(f"symbol={grid_settings.symbol}")
                print(f"local_grid_initialized={'true' if grid_state.grid is not None else 'false'}")
                print("exchange_position=unknown")
                print("decision=recovery-unavailable")
                print(f"message={exc}")
                return
            grid_decision = reconcile_grid_state(
                state=grid_state,
                settings=grid_settings,
                open_orders=open_orders,
                exchange_position=grid_exchange_position,
                fills=grid_fills,
                when=datetime.now(tz=UTC),
            )
            recovered = grid_decision.recovered_state
            print(f"state_file={grid_settings.state_file}")
            print(f"symbol={grid_settings.symbol}")
            print(f"local_grid_initialized={'true' if grid_state.grid is not None else 'false'}")
            print(f"exchange_position={'true' if grid_exchange_position is not None else 'false'}")
            print(f"open_orders={len(open_orders)}")
            print(f"decision={grid_decision.action}")
            print(f"message={grid_decision.message}")
            print(
                "recovered_active_buy_orders="
                f"{sum(1 for level in recovered.levels if level.status == 'buy_open')}"
            )
            print(
                "recovered_inventory_levels="
                f"{sum(1 for level in recovered.levels if level.status in {'filled_inventory', 'sell_open'})}"
            )
            return
        dca_settings = _require_dca_settings(config)
        exchange = build_exchange(config, logging.getLogger("gravity_dca"))
        dca_state = load_state(dca_settings.state_file)
        try:
            dca_exchange_position = exchange.get_open_position(dca_settings.symbol)
            exchange_fills = (
                exchange.get_recent_fills(dca_settings.symbol)
                if dca_exchange_position is not None
                else None
            )
        except TransientExchangeError as exc:
            print(f"state_file={dca_settings.state_file}")
            print(f"symbol={dca_settings.symbol}")
            print(f"local_active_cycle={'true' if dca_state.active_cycle is not None else 'false'}")
            print("exchange_position=unknown")
            print("decision=recovery-unavailable")
            print(f"message={exc}")
            return
        dca_decision = reconcile_state(
            state=dca_state,
            settings=dca_settings,
            symbol=dca_settings.symbol,
            exchange_position=dca_exchange_position,
            exchange_fills=exchange_fills,
            when=datetime.now(tz=UTC),
        )
        print(f"state_file={dca_settings.state_file}")
        print(f"symbol={dca_settings.symbol}")
        print(f"local_active_cycle={'true' if dca_state.active_cycle is not None else 'false'}")
        print(f"exchange_position={'true' if dca_exchange_position is not None else 'false'}")
        print(f"decision={dca_decision.action}")
        print(f"message={dca_decision.message}")
        print(f"reconstruction_attempted={'true' if dca_decision.reconstruction_attempted else 'false'}")
        print(f"reconstruction_succeeded={'true' if dca_decision.reconstruction_succeeded else 'false'}")
        if dca_decision.reconstruction_message is not None:
            print(f"reconstruction_message={dca_decision.reconstruction_message}")
        if dca_decision.recovered_cycle is not None:
            print(
                "reconstructed_completed_safety_orders="
                f"{dca_decision.recovered_cycle.completed_safety_orders}"
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
        bot: DcaBot | MomentumBot | GridBot = MomentumBot(config, logging.getLogger("gravity_dca"))
    elif configured_strategy_type(config) == "grid":
        bot = GridBot(config, logging.getLogger("gravity_dca"))
    else:
        bot = DcaBot(config, logging.getLogger("gravity_dca"))
    if args.once:
        bot.run_once()
        return
    bot.run_forever()
