from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging

from .bot import DcaBot
from .momentum_bot import MomentumBot
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
            raise SystemExit("Momentum status CLI is planned for Phase 8 and is not implemented yet.")
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
            raise SystemExit("Momentum thresholds CLI is planned for Phase 8 and is not implemented yet.")
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
            raise SystemExit("Momentum recovery CLI is planned for Phase 7 and is not implemented yet.")
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
    else:
        bot = DcaBot(config, logging.getLogger("gravity_dca"))
    if args.once:
        bot.run_once()
        return
    bot.run_forever()
