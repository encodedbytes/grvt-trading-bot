from __future__ import annotations

import argparse
import logging

from .bot import DcaBot
from .config import load_config
from .exchange import GrvtExchange
from .state import load_state
from .strategy import next_safety_trigger_price, stop_loss_price, take_profit_price


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
        "--thresholds",
        action="store_true",
        help="Print the current active cycle thresholds from the configured state file.",
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
        exchange = GrvtExchange(config.credentials, logging.getLogger("gravity_dca"))
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

    if args.thresholds:
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

    bot = DcaBot(config, logging.getLogger("gravity_dca"))
    if args.once:
        bot.run_once()
        return
    bot.run_forever()
