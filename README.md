# GRVT Futures Bots

Python futures trading bots for GRVT perpetual markets.

Planning documents:
- [TASKS.md](TASKS.md)
- [TASKS_TELEGRAM.md](TASKS_TELEGRAM.md)
- [TASKS_MOMENTUM.md](TASKS_MOMENTUM.md)
- [TASKS_DASHBOARD.md](TASKS_DASHBOARD.md)

Momentum strategy config example:
- [config.momentum.example.toml](config.momentum.example.toml)

## Overview

The repo currently includes:
- a DCA bot with initial entry, safety orders, take profit, and optional stop loss
- a momentum bot with trend-plus-breakout entry, ATR-based stops, and trend-failure exits
- local state persistence and restart recovery
- a local dashboard and bot-local read-only status API

Important behavior:
- entries and exits can use `market` or aggressive `limit` orders
- take profit is price-based, not ROE-based
- the momentum bot is long-only in this first version
- on startup, DCA recovery first tries to rebuild the active cycle from live GRVT fill history for the configured symbol
- momentum recovery reconciles local state with the live exchange position and recomputes ATR-backed stop metadata
- transient private-auth TLS/network failures are retried and can fall back to trusted local state for the current iteration
- GRVT private auth now refreshes and synchronizes the SDK session cookie before private POST calls, and retries once on unauthenticated `401` responses or payloads
- when a bot has no active cycle and has reached `max_cycles`, it sends a one-time inactive notification instead of silently going idle
- each long-running bot exposes a tiny read-only local API for health and status

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

Inspect the current GRVT leverage bounds and margin type for the configured symbol:

```bash
make position-config CONFIG=config.toml
```

Inspect the bot's current operator status in one view:

```bash
make status CONFIG=config.toml
```

For momentum configs, `make status` also prints flat-state entry diagnostics such as:
- `entry_decision`
- `entry_reason`
- `latest_close`
- `breakout_level`
- `ema_fast`
- `ema_slow`
- `adx`
- `atr_percent`

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

Run the local web dashboard for Docker-managed bots:

```bash
make dashboard
```

Run tests:

```bash
make test
```

Run the dashboard in Docker:

```bash
make dashboard-docker-build
make dashboard-docker-run
```

## Configuration

Start from [config.example.toml](config.example.toml).

Momentum configs can start from [config.momentum.example.toml](config.momentum.example.toml). Both DCA and momentum bot runs are supported.

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
- `runtime.bot_api_port`

Notes:
- `initial_quote_amount` and `safety_order_quote_amount` are quote-currency budgets, not base size.
- `order_type` can be `market` or `limit`.
- `limit_price_offset_percent` is used only for `order_type = "limit"`.
- `take_profit_percent` is based on price move from average entry, not leveraged ROE.
- `initial_leverage` and `margin_type` are optional.
- `runtime.private_auth_retry_attempts` and `runtime.private_auth_retry_backoff_seconds` control retry behavior for transient GRVT private-auth failures.
- `runtime.bot_api_port` controls the bot-local read-only API port and defaults to `8787`.
- optional config values should be omitted entirely when unused; TOML `null` is not valid and the loader now reports that explicitly.
- private GRVT POST calls also refresh the SDK session cookie on unauthenticated `401` responses before retrying once.
- Production credentials require `environment = "prod"`.
- For host-side CLI use, Docker-style `state_file = "/state/..."` paths are mapped to the nearest parent `state/` directory when `/state` does not exist locally. This allows configs under subdirectories like `local-configs/` to still use the repo-level `state/` directory.

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

Momentum state is stored separately in the path configured by `momentum.state_file`.

State includes:
- symbol and side
- average entry
- total quantity and cost
- completed safety orders
- leverage and margin type
- last client order id
- last GRVT order id

Use a unique `state_file` per bot instance.

When `completed_cycles >= max_cycles` and there is no active cycle:
- the bot keeps running and polling
- it does not open a new cycle
- it sends a one-time inactive notification with reason `max-cycles-reached`

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

By default, local Docker builds use the current git-derived tag from `git describe --tags --always --dirty`, so the image names look like `gravity-dca-bot:v0.3.0-2-gabcdef1` and `gravity-dca-dashboard:v0.3.0-2-gabcdef1`.

Inspect the computed local image names without building:

```bash
make docker-image-info
```

Override the tag manually when needed:

```bash
make docker-build IMAGE_TAG=v0.3.0
make dashboard-docker-build IMAGE_TAG=v0.3.0
```

Build the dashboard image:

```bash
make dashboard-docker-build
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

The default bot image exposes container port `8787` for the read-only bot API. If you change `runtime.bot_api_port`, the bot listens on that configured container port instead. The standard Make and Compose workflows keep the bot API internal to the Docker network and do not publish it to the host by default.

## Web Dashboard

The repo includes a local read-only monitoring dashboard for running bot containers.

Each long-running bot now also serves a tiny read-only local API inside its own process. The dashboard prefers this API for bot configuration and local state, and falls back to Docker-based inspection when the API is not reachable.

What it shows:
- running bot containers discovered from Docker
- mounted config and state file paths
- symbol, environment, order type, dry-run mode, and configured leverage
- active cycle summary with entry, quantity, TP, SL, and next safety trigger
- momentum signal diagnostics such as `entry_reason`, breakout, EMA, ADX, and ATR context
- completed cycle count and last closed cycle summary
- recent error line and most recent log line from each container
- explicit `risk-reduce-only` runtime state when GRVT cross margin blocks exposure-increasing orders
- clickable per-bot detail panel with live log tailing
- configurable card layout with `Vertical` and `Horizontal` views
- URL-synced view and selected bot state for reload/shareable dashboard context
- keyboard shortcut support for `Esc` to close the detail drawer

It does not:
- place trades
- call the exchange
- modify config or state

Bot-local API:
- endpoint: `GET /health`
- endpoint: `GET /status`
- bind: `0.0.0.0:<runtime.bot_api_port>` inside the bot container
- default port: `8787`
- purpose: expose the bot's already-loaded config, local state, thresholds, lifecycle, and recent iteration error state

`GET /status` response includes:
- symbol and environment
- order type, dry-run mode, state file, configured leverage, and margin type
- lifecycle state and completed/max cycles
- active cycle summary
- TP, SL, and next safety trigger thresholds
- last closed cycle summary when present
- runtime status timestamps, the most recent iteration error, and `risk-reduce-only` state when present

Notes:
- the bot API is read-only
- the default bot API port is `8787`
- set `runtime.bot_api_port` per bot when you need multiple host-side bot processes on the same machine
- the Make and Compose flows do not publish that port to the host by default
- the dashboard reads each bot's configured API port from its config and connects to that port on the container network when available
- the dashboard can reach the bot API when it runs on the same Docker network or bridge; otherwise it falls back to Docker-based inspection

Run it locally:

```bash
make dashboard
```

Run it in Docker:

```bash
make dashboard-docker-build
make dashboard-docker-run
```

Run it in Docker in the background:

```bash
make dashboard-docker-build
make dashboard-docker-up
make dashboard-docker-logs
```

Stop the dashboard container:

```bash
make dashboard-docker-down
```

The dashboard container needs access to the host Docker socket so it can inspect running bot containers and tail their logs:

```bash
-v /var/run/docker.sock:/var/run/docker.sock
```

By default the dashboard image listens on `0.0.0.0:8080`, and the Make targets publish that as `http://localhost:8080`.

Default address:
- `http://127.0.0.1:8080`

## Commands

Local:
- `make once CONFIG=config.toml`
- `make run CONFIG=config.toml`
- `make dashboard`
- `make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp`
- `make position-config CONFIG=config.toml`
- `make status CONFIG=config.toml`
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
- `make dashboard-docker-build`
- `make dashboard-docker-run`
- `make dashboard-docker-up`
- `make dashboard-docker-logs`
- `make dashboard-docker-down`

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
- Current implementation tasks for limit-order support are tracked in [TASKS.md](TASKS.md).
- Telegram notification implementation notes are tracked in [TASKS_TELEGRAM.md](TASKS_TELEGRAM.md).
- Current agent continuity notes are in [AGENTS.md](AGENTS.md).
- GRVT-specific AI skill notes are in [SKILLS.md](SKILLS.md).

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
- bot inactive after reaching `max_cycles`
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
