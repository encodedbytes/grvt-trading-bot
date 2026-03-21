# Grid Bot Implementation Plan

Status: implemented through Phase 8; Phase 9 live rollout remains pending

This file is the persistent implementation plan for a first-pass grid bot in this repo.

## Objective

Add a simple, operationally safe grid strategy that complements the existing DCA and momentum bots.

The first version should:
- run on GRVT perpetual markets
- use bounded quote-budget sizing
- use limit orders only
- be long-only in v1
- maintain a fixed price band and a fixed number of grid levels
- avoid hedged long/short inventory or cross-symbol coordination

## Design Direction

Use the same top-level config selector already present in the repo:

```toml
[strategy]
type = "grid"
```

But keep the runtime and state implementation separate from DCA and momentum:
- `grid_bot.py`
- `grid_state.py`
- `grid_strategy.py`
- `grid_recovery.py`

This follows the same shape already proven by momentum:
- shared exchange/config/dashboard infrastructure
- strategy-specific runtime and persistence

That keeps responsibilities sharp and avoids forcing DCA, momentum, and grid into one oversized runtime class.

## Strategy Spec

### V1 Scope

The first grid version should be a bounded long-only reversion grid.

Behavior:
- define a lower bound and upper bound
- split the band into `grid_levels`
- place resting buy orders below the current price
- after a buy fills, place the corresponding sell order one level above the fill level
- when that sell fills, the level becomes available to buy again
- do not open new orders outside the configured price band

This is intentionally not:
- a neutral long/short hedge grid
- a martingale ladder
- a trend-following breakout grid
- an adaptive or volatility-resizing grid

### Core Concepts

- `price_band_low`
- `price_band_high`
- `grid_levels`
- `spacing_mode`
  - `arithmetic` in v1
  - `geometric` can wait unless clearly needed
- `quote_amount_per_level`
- `max_active_buy_orders`
- `max_inventory_levels`

### Entry / Re-entry Logic

At each polling iteration:
- fetch the latest market price
- compute the configured grid levels
- reconcile local state against live open orders and live position
- ensure eligible buy orders exist for unfilled levels below market
- ensure paired sell orders exist for filled inventory levels above their entry level

### Exit Logic

The normal exit path is per-level profit-taking:
- each filled buy level gets a paired sell order at the next grid level above

Optional v1 safety controls:
- stop opening new buy orders once total inventory reaches `max_inventory_levels`
- optional `global_stop_loss_percent` or `global_stop_price`
- optional `pause_new_entries_above_upper_band` and `pause_new_entries_below_lower_band`

Recommendation:
- keep global stop logic optional in v1
- require bounded price bands and bounded inventory from day one

## Proposed Config Shape

Preferred shape:

```toml
[strategy]
type = "grid"

[grid]
symbol = "ETH_USDT_Perp"
side = "buy"
order_type = "limit"
initial_leverage = "3"
margin_type = "CROSS"

price_band_low = "1800"
price_band_high = "2200"
grid_levels = 8
spacing_mode = "arithmetic"
quote_amount_per_level = "100"
max_active_buy_orders = 3
max_inventory_levels = 4

state_file = "/state/.gravity-grid-eth.json"
```

Notes:
- `side` should remain fixed to `buy` in v1
- `order_type` should be fixed to `limit` in v1
- the bot should reject unsupported values early
- reuse the existing runtime config section for polling, dry-run, bot API port, and retry settings

## Proposed Bot State

State should track both inventory and working orders.

### Grid Definition Snapshot

- `symbol`
- `side`
- `price_band_low`
- `price_band_high`
- `grid_levels`
- `spacing_mode`
- `quote_amount_per_level`

### Per-Level State

For each grid level:
- `level_index`
- `price`
- `status`
  - `idle`
  - `buy_open`
  - `filled_inventory`
  - `sell_open`
- `entry_order_id`
- `entry_client_order_id`
- `entry_fill_price`
- `entry_quantity`
- `exit_order_id`
- `exit_client_order_id`
- `exit_fill_price`
- `realized_pnl_estimate`
- `updated_at`

### Aggregate State

- `started_at`
- `completed_round_trips`
- `active_inventory_levels`
- `last_error`
- `last_reconciled_at`

## Recovery Expectations

Recovery is mandatory before live rollout.

The grid bot must:
- load local grid state
- fetch live open orders for the symbol
- fetch the live exchange position
- fetch recent fills when necessary
- reconcile missing local order IDs or stale local order slots

Safe v1 behavior:
- if local and exchange state materially disagree, stop and surface an operator-facing error
- do not guess through ambiguous order-to-level mappings
- prefer clearing stale closed orders over fabricating inventory

## Dashboard / Bot API Expectations

The dashboard should be able to show:
- strategy type `grid`
- configured band and grid level count
- current active buy orders
- current inventory levels
- completed round trips
- degraded-mode notes if only Docker fallback data is available

The bot-local API should expose:
- `/health`
- `/status`

`/status` should include:
- config summary
- aggregate grid status
- per-level summary
- recent runtime decision

## CLI / Operator Expectations

The CLI should eventually support:
- `--status`
- `--thresholds`
  - for grid, this should print band, spacing, active buy levels, and paired sell levels
- `--recovery-status`

Docker and dashboard workflows should remain the same as DCA and momentum.

## Implementation Phases

### Phase 1: Config Model

Status: implemented

Goal:
- add `grid` config parsing and validation

Tasks:
- add `GridSettings`
- accept `[strategy] type = "grid"` with `[grid]`
- validate long-only and limit-only v1 constraints
- add example config

Completion criteria:
- valid and invalid grid config tests pass

Delivered:
- added `GridSettings` to the shared config model
- extended the strategy selector to accept `grid`
- added validation for v1 long-only, limit-only, arithmetic-spacing constraints
- added `config.grid.example.toml`
- added valid and invalid config parsing tests

### Phase 2: State Model

Status: implemented

Goal:
- add dedicated grid state persistence

Tasks:
- define per-level state model
- define aggregate state model
- add load/save helpers
- add round-trip tests

Completion criteria:
- grid state persistence round-trips cleanly

Delivered:
- added dedicated `gravity_dca.grid_state` persistence for aggregate grid state and per-level order/inventory state
- added explicit level statuses for `idle`, `buy_open`, `filled_inventory`, and `sell_open`
- added safe mutation helpers for initializing grids, opening buy/sell orders, marking fills, and recording reconciliation timestamps
- added round-trip and validation tests for grid state behavior

### Phase 3: Pure Grid Strategy Layer

Status: implemented

Goal:
- compute levels and desired order/inventory actions without exchange I/O

Tasks:
- compute arithmetic grid levels
- map market price to eligible buy/sell actions
- compute next desired orders from local state
- keep this layer pure and deterministic

Completion criteria:
- unit tests cover level generation and decision-making

Delivered:
- added pure grid planning helpers in `gravity_dca.grid_strategy`
- implemented inclusive arithmetic grid-level generation
- implemented paired sell-target derivation from a filled buy level
- implemented a deterministic planner that turns market price plus local grid state into desired buy/sell orders
- added unit tests for level generation, buy-order selection, sell pairing, and capacity limits

### Phase 4: Exchange/Order Reconciliation

Status: implemented

Goal:
- add the order and fill reconciliation needed for a safe grid runtime

Tasks:
- fetch and normalize live open orders
- map open orders to grid levels
- map fills to entry/exit transitions
- detect ambiguous or unsafe states

Completion criteria:
- recovery and reconciliation tests cover stale orders, missing orders, and filled transitions

Delivered:
- added `gravity_dca.grid_recovery` with a normalized open-order snapshot and strict reconciliation flow
- mapped open buy orders by level price and mapped open sell orders back to their source inventory levels
- clear stale local orders only when no unambiguous matching fill exists
- promote filled transitions only when fills match known order IDs or client order IDs
- validate aggregate local inventory quantity against the live exchange position
- added reconciliation tests for missing orders, stale orders, filled transitions, duplicate open orders, and exchange mismatch cases

### Phase 5: Bot Orchestration

Status: implemented

Goal:
- implement the live grid bot loop

Tasks:
- place missing buy orders
- place paired sell orders after fills
- cancel orders that are no longer valid for the current state
- preserve dry-run semantics

Completion criteria:
- orchestration tests pass with mocked exchange responses

Delivered:
- added `gravity_dca.grid_bot` as a dedicated grid runtime separate from DCA and momentum
- added exchange support for listing live open orders
- implemented reconciliation-first runtime orchestration before planning new orders
- placed missing resting buy orders and paired sell orders from the pure planner
- canceled stale buy orders that are no longer valid for the current market/capacity state
- preserved dry-run behavior by planning and logging actions without mutating persisted state
- kept sell sizing tied to recovered inventory quantity instead of recomputing it from quote budget
- added mocked runtime tests for dry-run planning, buy placement, sell placement, and stale-order cancellation

### Phase 6: Recovery

Status: implemented

Goal:
- make restart behavior operationally safe

Tasks:
- reconcile local state against open orders, fills, and exchange position
- rebuild missing per-level state only when the mapping is unambiguous
- fail safely on inconsistent inventory

Completion criteria:
- restart scenarios are covered in tests

Delivered:
- tightened `gravity_dca.grid_recovery` to classify restart outcomes explicitly, including `initialize-from-config`, `rebuild-from-open-orders`, and `rebuild-from-open-orders-and-fills`
- covered empty-local-state restart scenarios instead of relying only on already-populated local state
- allowed sell-side recovery to rebuild source inventory from buy fills mapped back to the originating grid level when local order IDs are missing
- preserved fail-safe behavior for ambiguous order mapping and exchange inventory mismatches
- added restart-focused tests for config initialization, rebuilding open buys, and rebuilding sell-side inventory from live exchange state

### Phase 7: CLI, Bot API, and Dashboard

Status: implemented

Goal:
- make the grid bot observable with the existing operator tooling

Tasks:
- extend CLI status output
- add grid status to the bot-local API
- add dashboard cards and drawer sections for grid-specific data

Completion criteria:
- dashboard and CLI show useful grid runtime state

Delivered:
- extended `cli.py` to support grid `status`, `thresholds`, `recovery-status`, and runtime selection
- extended `status_snapshot.py` and `bot_api.py` so grid bots can expose `/status` through the shared bot-local API
- normalized grid payloads through `dashboard_payload.py` instead of introducing a dashboard-only schema
- added grid fallback/API support in `dashboard.py`
- added grid-specific card and drawer sections in `dashboard_template.py`
- added regression coverage for grid CLI output, shared status snapshots, bot API snapshots, dashboard payload normalization, and dashboard rendering

### Phase 8: Docs and Example Configs

Status: implemented

Goal:
- make the grid bot operable by documentation, not tribal knowledge

Tasks:
- update `README.md`
- update `AGENTS.md`
- add `config.grid.example.toml`
- document risk boundaries and first live rollout defaults

Completion criteria:
- operator docs are current and explicit

Delivered:
- updated `README.md` to describe the implemented grid bot lifecycle, CLI output, state model, and strategy constraints
- updated `AGENTS.md` so session continuity reflects that grid runtime, recovery, CLI, bot API, and dashboard work are now in place
- kept `config.grid.example.toml` aligned with the current v1 constraints and operator defaults
- clarified that the remaining grid work is live rollout, not missing implementation phases

### Phase 9: Live Rollout

Goal:
- validate the first grid bot safely on GRVT

Tasks:
- start with `dry_run = true`
- start with one symbol
- use a narrow band and small quote size
- confirm order placement, fill pairing, recovery, dashboard visibility, and cancellation paths

Completion criteria:
- at least one full buy-fill -> sell-fill round trip completes without manual intervention

## Recommended Initial Defaults

Conservative first live test:
- symbol: `ETH_USDT_Perp`
- leverage: `3`
- band width: narrow and recent-market based, not hand-wavy
- `grid_levels = 6`
- `quote_amount_per_level = "50"`
- `max_active_buy_orders = 2`
- `max_inventory_levels = 2`
- `dry_run = true`

## Open Design Questions

- Should v1 allow a global stop-loss, or should bounded inventory be the only hard risk limit?
- Should paired sell levels always be exactly one grid step above the filled buy, or should the exit target be configurable?
- Do we need geometric spacing soon enough to justify including it in v1?
- Should the dashboard render per-level state in the drawer only, or also summarize it on the card?

## Notes For Future Sessions

- Keep v1 long-only and bounded.
- Do not add short-grid or hedge-grid behavior until the long-only lifecycle is stable.
- Do not couple grid orchestration into `bot.py`; follow the same separate-runtime pattern used by momentum.
- Prefer explicit per-level state over clever implicit reconstruction.
