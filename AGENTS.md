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
- [config.toml](config.toml)
- current state file referenced by `dca.state_file`
- whether a live container is running
- whether the exchange already has an open position for the configured symbol
- [TASKS.md](TASKS.md) if resuming limit-order work
- [TASKS_TELEGRAM.md](TASKS_TELEGRAM.md) if resuming Telegram notification work
- [TASKS_MOMENTUM.md](TASKS_MOMENTUM.md) if resuming momentum strategy work
- whether current work should happen on a feature branch instead of `main`

## Current Operational Facts

- The bot supports `market` and aggressive `limit` orders for entries and exits.
- Each long-running bot exposes a tiny read-only local API with `/health` and `/status`; `runtime.bot_api_port` defaults to `8787`.
- Telegram notifications are optional and one-way only.
- Take profit is price-based, not ROE-based.
- On startup, the bot first attempts full active-cycle reconstruction from exchange fills, then falls back to position-level recovery if reconstruction is not safe.
- Transient GRVT private-auth failures are retried; if recovery fails transiently and local active state exists, the bot keeps local state for that iteration.
- Private GRVT POST calls refresh and synchronize the SDK session cookie, and retry once on unauthenticated `401` responses or payloads.
- Each bot must use a unique `state_file`.
- For host-side CLI use, Docker-style `state_file = "/state/..."` paths are mapped to the nearest parent `state/` directory when `/state` does not exist locally.
- The dashboard prefers the bot-local API for config/state details, reads each bot's configured API port from its config, and falls back to Docker-based inspection when the API is unreachable.
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
make docker-build
make docker-up CONFIG=config.toml CONTAINER=grvt-dca-eth
make docker-restart CONFIG=config.toml CONTAINER=grvt-dca-eth
make docker-logs CONTAINER=grvt-dca-eth
make docker-down CONTAINER=grvt-dca-eth
make dashboard-docker-build
make dashboard-docker-up
make dashboard-docker-logs
make dashboard-docker-down
```

## Files That Matter Most

- [config.toml](config.toml)
- [src/gravity_dca/bot.py](src/gravity_dca/bot.py)
- [src/gravity_dca/exchange.py](src/gravity_dca/exchange.py)
- [src/gravity_dca/grvt_auth.py](src/gravity_dca/grvt_auth.py)
- [src/gravity_dca/grvt_market.py](src/gravity_dca/grvt_market.py)
- [src/gravity_dca/grvt_trading.py](src/gravity_dca/grvt_trading.py)
- [src/gravity_dca/strategy.py](src/gravity_dca/strategy.py)
- [src/gravity_dca/state.py](src/gravity_dca/state.py)
- [src/gravity_dca/bot_api.py](src/gravity_dca/bot_api.py)
- [src/gravity_dca/status_snapshot.py](src/gravity_dca/status_snapshot.py)
- [src/gravity_dca/dashboard.py](src/gravity_dca/dashboard.py)

## Safe Defaults

- Inspect instrument constraints before changing symbol or budget.
- Keep `dry_run = true` while changing environment, sizing, leverage, or margin settings.
- If behavior looks wrong, compare exchange position data against the local state file before rerunning.
- Recovery now prefers exchange fill-history reconstruction for the active cycle. If fill history is ambiguous, it falls back to position-level recovery.
- Prefer doing new implementation work on a feature branch and only merge back after verification.
