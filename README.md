# GRVT DCA Bot

Futures DCA bot for GRVT perpetual markets.

## What it does

- Loads a GRVT market through `grvt-pysdk`
- Can sync GRVT leverage and position `margin_type` from `config.toml` before trading
- Opens an initial long or short perpetual position using a fixed quote budget
- Adds safety orders when price moves against the position by configured percentages
- Recalculates average entry after each additional fill
- Closes the full position when take profit is reached
- Optionally closes the full position on stop loss
- Persists the active cycle in a local state file
- Polls GRVT after order submission and only updates cycle state after a real fill is confirmed
- Includes a CLI instrument inspector for live exchange constraints and current prices
- Supports `dry_run` mode for safe validation

## Setup

1. Create a local virtual environment:

```bash
python3 -m venv .venv
```

2. Activate it:

```bash
source .venv/bin/activate
```

3. Upgrade packaging tools and install the project:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Or use the repo targets:

```bash
make install
```

4. Create your runtime config from [config.example.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.example.toml):

```bash
cp config.example.toml config.toml
```

5. Edit `config.toml` and fill in:

- `api_key`
- `private_key`
- `trading_account_id`
- `symbol`
- `side`
- `initial_quote_amount`
- `safety_order_quote_amount`
- `initial_leverage`
- `margin_type`
- `max_safety_orders`
- `price_deviation_percent`
- `take_profit_percent`

## Run

Preferred workflow:

```bash
make install
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
make once CONFIG=config.toml
```

Single iteration:

```bash
source .venv/bin/activate
gravity-dca --config config.toml --once
```

Inspect an instrument:

```bash
source .venv/bin/activate
gravity-dca --config config.toml --instrument ETH_USDT_Perp
```

Or:

```bash
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
```

Daemon mode:

```bash
source .venv/bin/activate
gravity-dca --config config.toml
```

Run tests:

```bash
source .venv/bin/activate
pytest
```

Or:

```bash
make test
```

Make targets:

- `make install` creates `.venv` and installs the project with dev dependencies.
- `make once CONFIG=config.toml` runs one DCA decision loop.
- `make run CONFIG=config.toml` runs the polling bot.
- `make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp` prints market constraints and live prices for a symbol.
- `make docker-build IMAGE=gravity-dca-bot:local` builds the container image.
- `make docker-run CONFIG=config.toml IMAGE=gravity-dca-bot:local` runs the bot in Docker.
- `make docker-once CONFIG=config.toml IMAGE=gravity-dca-bot:local` runs a single iteration in Docker.
- `make docker-up CONFIG=config.toml IMAGE=gravity-dca-bot:local CONTAINER=gravity-dca` runs the container in the background.
- `make docker-logs CONTAINER=gravity-dca` tails container logs.
- `make docker-down CONTAINER=gravity-dca` stops and removes the background container.
- `make test` runs the test suite inside `.venv`.
- `make clean` removes `.venv` and `.pytest_cache`.

## Container

Build the image:

```bash
make docker-build
```

Run the bot in Docker:

```bash
mkdir -p state
make docker-run CONFIG=config.toml
```

Run the bot in the background and inspect logs with Docker:

```bash
mkdir -p state
make docker-up CONFIG=config.toml
make docker-logs
```

Stop the background container:

```bash
make docker-down
```

Run one iteration in Docker:

```bash
mkdir -p state
make docker-once CONFIG=config.toml
```

The image expects:
- a config file mounted at `/app/config.toml`
- a writable state directory mounted at `/state`

When running in containers, set `state_file` in your config to an absolute path under `/state`, for example:

```toml
[dca]
state_file = "/state/eth-bot.json"
```

You can also use Docker Compose:

```bash
mkdir -p state
docker compose up --build
```

To run more than one bot at the same time, duplicate the service in [compose.yaml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/compose.yaml), mount a different config file for each service, and make sure each config uses a unique `state_file`.

## Instrument Checks

Before changing symbols or quote budgets, inspect the instrument live:

```bash
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
```

This prints:
- `tick_size`
- `min_size`
- `min_notional`
- `base_decimals`
- live `best_bid`
- live `best_ask`
- live `mid_price`

Practical rule:
- A quote budget must satisfy both `min_notional` and `min_size`
- Passing `min_notional` alone is not enough

Examples seen live on GRVT prod during development:
- `BTC_USDT_Perp`: much higher notional floor than ETH
- `ETH_USDT_Perp`: `min_notional = 20.0`, `min_size = 0.01`
- `HYPE_USDT_Perp`: `min_notional = 5.0`, `min_size = 1.0`

## Strategy model

- If there is no active cycle, the bot opens an initial market position.
- If there is an active cycle and price reaches take profit, the bot sends a reduce-only market order to close it.
- If stop loss is configured and price reaches it first, the bot closes the cycle.
- If price moves against the position enough to hit the next safety-order trigger, the bot adds to the position.
- After each additional entry, the bot updates average entry and computes the next trigger from that averaged price.

## Order Lifecycle

- The bot signs and submits a GRVT market order.
- It does not trust submission acknowledgment alone.
- After submission, it polls GRVT order status by `client_order_id`.
- It only persists a new or updated cycle after GRVT reports:
  - non-zero `traded_size`
  - non-zero `avg_fill_price`
- The bot stores the real order id returned by the order-status endpoint, not the placeholder id sometimes returned in the initial submit ack.

This matters because GRVT may acknowledge an order before the final fill status is visible.

## State

The bot stores local state in [.gravity-dca-state.json](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/.gravity-dca-state.json).

State includes:
- active cycle side and symbol
- average entry
- total quantity
- leverage used for the cycle
- margin type used for the cycle
- completed safety orders
- last client order id
- last real GRVT order id

If local state becomes inconsistent with exchange state, inspect or clear it before rerunning entry logic.

Current continuity notes are in [AGENTS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/AGENTS.md).
Exchange-specific lessons learned are in [SKILLS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/SKILLS.md).

## Notes

- `environment` must match the credentials you are using. Production credentials require `environment = "prod"`.
- `initial_quote_amount` and `safety_order_quote_amount` are quote-currency budgets, not base-asset sizes.
- `initial_leverage` and `margin_type` are optional. When set, the bot compares current GRVT config and applies changes before trading if `dry_run = false`.
- In `dry_run = true`, leverage and margin config differences are logged but not applied.
- `margin_type` is intended for GRVT position config values such as `CROSS` or `ISOLATED`.
- This implementation uses market orders for entries and exits.
- Safety-order spacing is controlled by `price_deviation_percent` and `safety_order_step_scale`.
- Safety-order size scaling is controlled by `safety_order_volume_scale`.
- Exit orders are submitted as `reduce_only` so they are intended to close, not expand, the position.
- Keep `.venv` local to the repo so the CLI and dependency versions stay isolated from your system Python.
- The bot tracks the DCA cycle locally; it does not reconstruct a cycle from exchange fill history if the state file is lost.
- If you change `symbol`, inspect the new market first with `make instrument`.
- Keep `dry_run = true` while changing environment, symbol, or sizing assumptions.
- Do not change `margin_type` while a live position is open. The bot will refuse that change for the active symbol.
