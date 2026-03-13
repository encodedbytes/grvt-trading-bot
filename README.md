# GRVT DCA Bot

Python futures DCA bot for GRVT perpetual markets.

## Overview

The bot:
- opens an initial long or short position
- adds safety orders as price moves against the position
- recalculates average entry after each fill
- closes the full position at take profit or stop loss
- stores cycle state in a local JSON file
- can sync GRVT leverage and `margin_type` before trading

Important behavior:
- entries and exits can use `market` or aggressive `limit` orders
- take profit is price-based, not ROE-based
- on startup, the bot can rebuild a missing active cycle from the live GRVT position for the configured symbol

## Quick Start

Create the virtual environment and install:

```bash
make install
```

Create your config:

```bash
cp config.example.toml config.toml
```

Inspect the market before trading:

```bash
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
```

Inspect the current active cycle thresholds:

```bash
make thresholds CONFIG=config.toml
```

Inspect how local state compares to the live exchange position:

```bash
make recovery-status CONFIG=config.toml
```

Run one safe iteration:

```bash
make once CONFIG=config.toml
```

Run continuously:

```bash
make run CONFIG=config.toml
```

Run tests:

```bash
make test
```

## Configuration

Start from [config.example.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.example.toml).

The most important settings are:
- `environment`
- `api_key`
- `private_key`
- `trading_account_id`
- `symbol`
- `side`
- `initial_quote_amount`
- `safety_order_quote_amount`
- `order_type`
- `limit_price_offset_percent`
- `initial_leverage`
- `margin_type`
- `take_profit_percent`
- `stop_loss_percent`
- `dry_run`
- `state_file`

Notes:
- `initial_quote_amount` and `safety_order_quote_amount` are quote-currency budgets, not base size.
- `order_type` can be `market` or `limit`.
- `limit_price_offset_percent` is used only for `order_type = "limit"`.
- `take_profit_percent` is based on price move from average entry, not leveraged ROE.
- `initial_leverage` and `margin_type` are optional.
- Production credentials require `environment = "prod"`.

## How It Trades

If there is no active cycle in the state file, the bot opens an initial position.

If a cycle is active, it checks on each polling iteration whether to:
- sell the full position at take profit
- sell the full position at stop loss
- add the next safety order
- do nothing

For long positions:
- entries use the ask side
- exits use the bid side

The bot only updates local state after GRVT confirms a real fill.

For `order_type = "limit"`:
- entry buys use an aggressive limit derived from the ask side
- exit sells use an aggressive limit derived from the bid side
- if the order is not filled within `runtime.limit_ttl_seconds`, the bot cancels it and leaves state unchanged

## State

The bot stores cycle state in the path configured by `dca.state_file`.

State includes:
- symbol and side
- average entry
- total quantity and cost
- completed safety orders
- leverage and margin type
- last client order id
- last GRVT order id

Use a unique `state_file` per bot instance.

On startup, the bot reconciles local state against the live GRVT position for the configured symbol:
- if local state is missing and a live position exists, it rebuilds the active cycle from the exchange position
- if local state exists but the exchange has no position, it clears the stale local active cycle
- if both exist and materially disagree, it refuses to continue

The current recovery is position-level, not full history reconstruction. It restores the active cycle from size, side, average entry, leverage, and margin type. It does not reconstruct exact safety-order count from exchange fills.

## Multi-Bot Use

Running multiple bots is supported if:
- each bot has its own config file
- each bot has its own `state_file`
- preferably each bot trades a different symbol

Avoid running multiple bots on the same symbol and sub-account.

## Docker

Build the image:

```bash
make docker-build
```

For Docker, mount a writable `state/` directory and point `state_file` to `/state/...`, for example:

```toml
[dca]
state_file = "/state/eth-bot.json"
```

Run one iteration:

```bash
mkdir -p state
make docker-once CONFIG=config.toml
```

Run in the background:

```bash
mkdir -p state
make docker-up CONFIG=config.toml CONTAINER=grvt-dca-eth
make docker-logs CONTAINER=grvt-dca-eth
```

Stop it:

```bash
make docker-down CONTAINER=grvt-dca-eth
```

## Commands

Local:
- `make once CONFIG=config.toml`
- `make run CONFIG=config.toml`
- `make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp`
- `make thresholds CONFIG=config.toml`
- `make recovery-status CONFIG=config.toml`
- `make test`

Docker:
- `make docker-build`
- `make docker-once CONFIG=config.toml`
- `make docker-up CONFIG=config.toml CONTAINER=grvt-dca-eth`
- `make docker-logs CONTAINER=grvt-dca-eth`
- `make docker-down CONTAINER=grvt-dca-eth`

## Docker Hub CI

The GitHub Actions workflow can publish the container image to Docker Hub on pushes to `main` and on version tags like `v0.2.0`.

Configure these in GitHub before enabling releases:
- repository variable `DOCKERHUB_IMAGE`
  - example: `encodedbytes/grvt-trading-bot`
- repository secret `DOCKERHUB_USERNAME`
- repository secret `DOCKERHUB_TOKEN`

Published tags:
- short git SHA on `main` and tag builds
- `latest` on the default branch
- the git tag itself on version tags, for example `v0.2.0`

## Operating Notes

- Use `make instrument` before changing symbols or budgets.
- A quote budget must satisfy both `min_notional` and `min_size`.
- Keep `dry_run = true` while changing environment, sizing, leverage, or margin settings.
- Do not change `margin_type` while a live position is open for that symbol.
- Current implementation tasks for limit-order support are tracked in [TASKS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/TASKS.md).
- Current agent continuity notes are in [AGENTS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/AGENTS.md).
- GRVT-specific AI skill notes are in [SKILLS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/SKILLS.md).
