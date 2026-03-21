# Session Continuity

Use this file only to resume work safely in a new session.

## What This Repo Is

Python GRVT futures bot repo with:
- DCA bot: initial entry, safety-order ladder, take-profit, optional stop-loss
- momentum bot: trend-plus-breakout entry with ATR/trailing-stop management
- grid bot: bounded long-only limit grid with restart recovery and observability support
- local state persistence and restart recovery
- Docker and local `.venv` workflows

## Resume Checklist

Before making changes or running the bot again, check:
- [config.toml](config.toml)
- current state file referenced by `dca.state_file`, `momentum.state_file`, or `grid.state_file`
- whether a live container is running
- whether the exchange already has an open position for the configured symbol
- [TASKS.md](TASKS.md) if resuming limit-order work
- [TASKS_TELEGRAM.md](TASKS_TELEGRAM.md) if resuming Telegram notification work
- [TASKS_MOMENTUM.md](TASKS_MOMENTUM.md) if resuming momentum strategy work
- [TASKS_DASHBOARD.md](TASKS_DASHBOARD.md) if resuming dashboard architecture work
- [TASKS_GRID.md](TASKS_GRID.md) if resuming grid bot planning or implementation
- whether current work should happen on a feature branch instead of `main`

## Current Operational Facts

- The bot supports `market` and aggressive `limit` orders for entries and exits.
- Each long-running bot exposes a tiny read-only local API with `/health` and `/status`; `runtime.bot_api_port` defaults to `8787`.
- Telegram notifications are optional and one-way only.
- Take profit is price-based, not ROE-based.
- On startup, the bot first attempts full active-cycle reconstruction from exchange fills, then falls back to position-level recovery if reconstruction is not safe.
- The momentum bot now has a separate runtime, state model, recovery flow, and CLI diagnostics (`status`, `thresholds`, `recovery-status`).
- Momentum `status` now prints flat-state entry diagnostics too, including `entry_decision`, `entry_reason`, `breakout_level`, `ema_fast`, `ema_slow`, `adx`, and `atr_percent`.
- The dashboard now shows a momentum `Signals` section with live entry/exit diagnostics from the bot-local API.
- The dashboard architecture work is complete: payload shaping, runtime access, and the static template now live in separate modules instead of one monolithic dashboard file.
- Transient GRVT private-auth failures are retried; if recovery fails transiently and local active state exists, the bot keeps local state for that iteration.
- Private GRVT POST calls refresh and synchronize the SDK session cookie, and retry once on unauthenticated `401` responses or payloads.
- Each bot must use a unique `state_file`.
- Optional config values should be omitted entirely when unused; TOML `null` is invalid and the loader now raises a clearer operator-facing error for that case.
- For host-side CLI use, Docker-style `state_file = "/state/..."` paths are mapped to the nearest parent `state/` directory when `/state` does not exist locally.
- The dashboard prefers the bot-local API for config/state details, reads each bot's configured API port from its config, and falls back to Docker-based inspection when the API is unreachable.
- The dashboard drawer now exposes whether details are coming from `bot-api`, `docker-fallback`, or `error`, and momentum signal diagnostics explicitly note when fallback mode cannot provide live signals.
- The grid bot now has separate config, state, strategy, reconciliation, runtime, CLI, bot API, and dashboard support on the `grid-bot-implementation` branch.
- Grid v1 is intentionally constrained to `side = "buy"`, `order_type = "limit"`, and `spacing_mode = "arithmetic"`.
- Grid configs can optionally set `seed_enabled = true` to place one startup market buy on fresh grid initialization, then continue with the normal paired-sell lifecycle from that seeded inventory.
- If GRVT rejects exposure-increasing orders because the account is `risk-reduce-only`, the bot runtime status records that explicitly and the dashboard surfaces it.
- When a bot has no active cycle and has reached `max_cycles`, it now sends a one-time inactive notification with reason `max-cycles-reached`.
- Multiple bots on the same symbol and sub-account are unsafe.
- `margin_type` changes are blocked when a live position exists for that symbol.
- Limit orders that do not fill within `runtime.limit_ttl_seconds` are canceled and do not mutate state.

## Commands

Local:
```bash
make install
make test
make once CONFIG=config.toml
make run CONFIG=config.toml
make dashboard
make instrument CONFIG=config.toml SYMBOL=ETH_USDT_Perp
make position-config CONFIG=config.toml
make status CONFIG=config.toml
make thresholds CONFIG=config.toml
make recovery-status CONFIG=config.toml
make notify-test CONFIG=config.toml
```

Docker:
```bash
make docker-image-info
make docker-build
make docker-up CONFIG=config.toml CONTAINER=grvt-dca-eth
make docker-restart CONFIG=config.toml CONTAINER=grvt-dca-eth
make docker-logs CONTAINER=grvt-dca-eth
make docker-down CONTAINER=grvt-dca-eth
make dashboard-docker-build
make dashboard-docker-run
make dashboard-docker-up
make dashboard-docker-logs
make dashboard-docker-down
```

Docker image defaults:
- local Docker image tags are derived from `git describe --tags --always --dirty`
- override with `IMAGE_TAG=...` when you want a specific local tag

## Files That Matter Most

- [config.toml](config.toml)
- [src/gravity_dca/bot.py](src/gravity_dca/bot.py)
- [src/gravity_dca/exchange.py](src/gravity_dca/exchange.py)
- [src/gravity_dca/grvt_auth.py](src/gravity_dca/grvt_auth.py)
- [src/gravity_dca/grvt_market.py](src/gravity_dca/grvt_market.py)
- [src/gravity_dca/grvt_trading.py](src/gravity_dca/grvt_trading.py)
- [src/gravity_dca/strategy.py](src/gravity_dca/strategy.py)
- [src/gravity_dca/state.py](src/gravity_dca/state.py)
- [src/gravity_dca/grid_state.py](src/gravity_dca/grid_state.py)
- [src/gravity_dca/grid_strategy.py](src/gravity_dca/grid_strategy.py)
- [src/gravity_dca/grid_recovery.py](src/gravity_dca/grid_recovery.py)
- [src/gravity_dca/grid_bot.py](src/gravity_dca/grid_bot.py)
- [src/gravity_dca/bot_api.py](src/gravity_dca/bot_api.py)
- [src/gravity_dca/status_snapshot.py](src/gravity_dca/status_snapshot.py)
- [src/gravity_dca/dashboard.py](src/gravity_dca/dashboard.py)
- [src/gravity_dca/dashboard_payload.py](src/gravity_dca/dashboard_payload.py)
- [src/gravity_dca/dashboard_runtime.py](src/gravity_dca/dashboard_runtime.py)
- [src/gravity_dca/dashboard_template.py](src/gravity_dca/dashboard_template.py)

## Safe Defaults

- Inspect instrument constraints before changing symbol or budget.
- Keep `dry_run = true` while changing environment, sizing, leverage, or margin settings.
- If behavior looks wrong, compare exchange position data against the local state file before rerunning.
- Recovery now prefers exchange fill-history reconstruction for the active cycle. If fill history is ambiguous, it falls back to position-level recovery.
- Prefer doing new implementation work on a feature branch and only merge back after verification.
