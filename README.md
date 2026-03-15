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
- on startup, the bot first tries to rebuild the active cycle from live GRVT fill history for the configured symbol
- if full reconstruction is not safe, it falls back to position-level recovery
- transient private-auth TLS/network failures are retried and can fall back to trusted local state for the current iteration
- GRVT private auth now refreshes and synchronizes the SDK session cookie before private POST calls, and retries once on unauthenticated `401` responses or payloads

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
- `runtime.private_auth_retry_attempts` and `runtime.private_auth_retry_backoff_seconds` control retry behavior for transient GRVT private-auth failures.
- private GRVT POST calls also refresh the SDK session cookie on unauthenticated `401` responses before retrying once.
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
- if local state is missing and a live position exists, it first tries to rebuild the full active cycle from exchange fills
- if full reconstruction is not safe, it falls back to rebuilding from the live position snapshot
- if local state exists but the exchange has no position, it clears the stale local active cycle
- if both exist and materially disagree, it refuses to continue
- if recovery hits a transient private-auth or network failure and local active state already exists, it keeps the local cycle for that iteration instead of aborting the poll
- if a private GRVT request returns an unauthenticated `401` response or payload, the bot refreshes the SDK session cookie and retries once before failing

Full reconstruction restores:
- side
- total quantity
- total cost
- average entry
- completed safety orders
- leverage and margin type
- last client order id
- last order id

Current limits:
- reconstruction only targets the currently open cycle
- it relies on recent GRVT fills being consistent with the configured DCA ladder
- if fills are ambiguous or inconsistent, the bot falls back to position-level recovery instead of guessing

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

Restart a specific background container:

```bash
make docker-restart CONFIG=config.toml CONTAINER=grvt-dca-eth
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
- `make notify-test CONFIG=config.toml`
- `make test`

Docker:
- `make docker-build`
- `make docker-once CONFIG=config.toml`
- `make docker-up CONFIG=config.toml CONTAINER=grvt-dca-eth`
- `make docker-restart CONFIG=config.toml CONTAINER=grvt-dca-eth`
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
- Telegram notification implementation notes are tracked in [TASKS_TELEGRAM.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/TASKS_TELEGRAM.md).
- Current agent continuity notes are in [AGENTS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/AGENTS.md).
- GRVT-specific AI skill notes are in [SKILLS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/SKILLS.md).

## Changing Config Mid-Cycle

The bot persists position facts in state, but it reads strategy behavior from the current config on every run. That means some config edits affect an already-open cycle immediately.

Safe to change for future visibility or housekeeping:
- `runtime.log_level`
- Docker or process-level settings that do not affect trading logic

Applies immediately to the current open cycle on the next poll:
- `take_profit_percent`
- `stop_loss_percent`
- `price_deviation_percent`
- `safety_order_step_scale`
- `safety_order_volume_scale`
- `safety_order_quote_amount`
- `max_safety_orders`
- `order_type`
- `limit_price_offset_percent`
- `runtime.limit_ttl_seconds`

Mostly applies only when a new cycle starts:
- `initial_quote_amount`
- `max_cycles`

High-risk changes to avoid mid-cycle:
- `symbol`
- `state_file`
- `side`
- switching between materially different sizing assumptions while a live cycle is open
- `margin_type`

Exchange-side notes:
- `initial_leverage` can affect the live instrument configuration before trading logic runs.
- `margin_type` changes are blocked while a live position exists for that symbol.

Recommended practice:
- treat TP/SL, safety sizing, ladder depth, and execution mode as fixed until the current cycle closes
- if you want a different strategy, use a new config file and a new `state_file`

## Telegram Notifications

Telegram support is optional and one-way only.

Supported first-pass notifications:
- bot startup
- recovery result on startup
- initial entry fill
- safety order fill
- take profit fill
- stop loss fill
- limit order timeout and cancel
- iteration failure
- leverage or margin config change

Add a Telegram section to your config:

```toml
[telegram]
enabled = true
bot_token = "123456:ABCDEF..."
chat_id = "123456789"
send_startup_summary = true
notify_position_config_changes = true
error_notification_cooldown_seconds = 300
```

How to get a Telegram bot token:
- Open Telegram and start a chat with `@BotFather`
- Send `/newbot`
- Follow the prompts for the bot name and username
- BotFather will return a token that looks like `123456:ABCDEF...`
- Put that value in `telegram.bot_token`

How to get your Telegram chat id:
- Start a chat with your new bot and send it any message, for example `hello`
- Then open this URL in your browser, replacing `<BOT_TOKEN>`:

```text
https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
```

- Find the `chat` object in the JSON response
- Use the numeric `id` field from that object as `telegram.chat_id`

Example response fragment:

```json
{
  "message": {
    "chat": {
      "id": 123456789
    }
  }
}
```

Notes:
- For a direct message, `chat_id` is usually a positive integer
- For a group, `chat_id` is usually a negative integer
- If `getUpdates` returns no messages, send another message to the bot first and retry
- If you want notifications in a group, add the bot to the group and send a message there first
- `error_notification_cooldown_seconds` suppresses repeated identical iteration-failure alerts for a cooldown window

After setting `bot_token` and `chat_id`, verify the integration with:

```bash
make notify-test CONFIG=config.toml
```

Test the notifier without waiting for a trade event:

```bash
make notify-test CONFIG=config.toml
```

Notes:
- Telegram notification failures are logged but do not stop trading.
- The first version does not support Telegram commands or bot control from chat.
- Repeated identical bot errors are rate-limited before sending to Telegram.
