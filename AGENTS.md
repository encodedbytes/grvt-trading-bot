# Session Continuity

Use this file only to resume work safely in a new session.

## What This Repo Is

Python GRVT futures DCA bot with:
- initial entry
- safety-order ladder
- take-profit exit
- optional stop-loss exit
- local cycle state
- Docker and local `.venv` workflows

## Resume Checklist

Before making changes or running the bot again, check:
- [config.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.toml)
- current state file referenced by `dca.state_file`
- whether a live container is running
- whether the exchange already has an open position for the configured symbol
- [TASKS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/TASKS.md) if resuming limit-order work

## Current Operational Facts

- The bot uses market orders for entries and exits.
- Take profit is price-based, not ROE-based.
- State is local-file driven; the bot does not reconstruct a cycle from exchange history if the state file is missing.
- Each bot must use a unique `state_file`.
- Multiple bots on the same symbol and sub-account are unsafe.
- `margin_type` changes are blocked when a live position exists for that symbol.

## Commands

Local:
```bash
make install
make test
make once CONFIG=config.toml
make run CONFIG=config.toml
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
```

Docker:
```bash
make docker-build
make docker-up CONFIG=config.toml CONTAINER=grvt-dca-eth
make docker-logs CONTAINER=grvt-dca-eth
make docker-down CONTAINER=grvt-dca-eth
```

## Files That Matter Most

- [config.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.toml)
- [src/gravity_dca/bot.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/bot.py)
- [src/gravity_dca/exchange.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/exchange.py)
- [src/gravity_dca/strategy.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/strategy.py)
- [src/gravity_dca/state.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/state.py)

## Safe Defaults

- Inspect instrument constraints before changing symbol or budget.
- Keep `dry_run = true` while changing environment, sizing, leverage, or margin settings.
- If behavior looks wrong, compare exchange position data against the local state file before rerunning.
