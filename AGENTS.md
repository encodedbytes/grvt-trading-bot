# Gravity Agent Notes

## Purpose

This repository contains a Python DCA futures bot for GRVT perpetual markets.

The bot currently supports:
- Production and testnet GRVT environments through `grvt-pysdk`
- Initial market entry for a long or short DCA cycle
- Safety-order ladder entries when price moves against the position
- Take-profit exits
- Optional stop-loss exits
- Local persistent cycle state in `.gravity-dca-state.json`
- Instrument inspection from the CLI for exchange constraints and live prices

## Core Commands

All commands should run through the repo virtual environment.

Setup:
```bash
make install
```

Run one bot iteration:
```bash
make once CONFIG=config.toml
```

Run continuously:
```bash
make run CONFIG=config.toml
```

Inspect a symbol:
```bash
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
```

Run tests:
```bash
make test
```

## Current Architecture

Key files:
- `src/gravity_dca/bot.py`: main runtime loop and state transitions
- `src/gravity_dca/strategy.py`: DCA sizing, trigger, and exit logic
- `src/gravity_dca/exchange.py`: GRVT API integration, auth checks, order polling, fill parsing
- `src/gravity_dca/state.py`: persisted local bot state
- `src/gravity_dca/config.py`: TOML config loading
- `src/gravity_dca/cli.py`: CLI entrypoints

## Important Runtime Behavior

- The bot only persists a new or updated cycle after GRVT confirms an actual fill.
- Order submission alone is not enough to mutate cycle state.
- The bot polls order status by `client_order_id` and records actual `traded_size`, `avg_fill_price`, and real `order_id`.
- Size is aligned to market constraints before submission.

## GRVT-Specific Constraints Learned

- `min_notional` alone is not enough to validate an order.
- `min_size` can still reject a quote budget that passes `min_notional`.
- ETH on prod accepted `min_notional = 20.0`, `min_size = 0.01` during testing.
- BTC on prod/testnet exposed much larger notional requirements.
- HYPE on prod had `min_notional = 5.0` but `min_size = 1.0`, which made a `5 USDT` budget invalid.
- GRVT can acknowledge a new order before final fill state is visible; polling is required.
- Initial order create responses may show a placeholder order id like `0x00`, while the order lookup endpoint returns the actual order id.

## Minimal Context Needed In A New Session

If resuming later, the minimum information needed is:
- Which environment is being used: `prod` or `testnet`
- Which symbol is being traded
- Whether `dry_run` is enabled
- Current contents of `config.toml`
- Current contents of `.gravity-dca-state.json`
- Whether the last submitted order was already filled on GRVT

## Current Known Good State

During the last verified production test:
- Environment: `prod`
- Symbol: `ETH_USDT_Perp`
- A live market buy order was accepted and later confirmed filled
- Local state was updated to use the actual GRVT order id
- Test suite status: `10 passed`

## Safe Working Rules

- Prefer `make instrument` before changing symbols or quote budgets.
- Do not trust quote budget alone; always compare against both `min_notional` and `min_size`.
- Keep `dry_run = true` when changing symbol, environment, or sizing assumptions.
- Clear or inspect `.gravity-dca-state.json` before retesting entry logic if prior runs failed mid-flow.
