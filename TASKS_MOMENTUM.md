# Momentum Strategy Implementation

Status: planned

This file is the persistent implementation plan for a first-pass momentum bot in this repo.

## Objective

Add a simple, operationally safe momentum strategy that complements the existing DCA bot.

The first version should:
- be long-only
- manage at most one active position per symbol
- use quote-budget sizing
- use market orders by default
- enter on confirmed trend plus breakout
- exit on stop loss, trailing stop, or trend failure

## Strategy Spec

### Entry

Enter long only when all of the following pass:
- `ema_fast > ema_slow`
- latest price is above the highest close of the last `breakout_lookback` candles
- `adx >= min_adx`
- `atr_percent >= min_atr_percent`

Recommended initial defaults:
- timeframe: `5m`
- `ema_fast_period = 20`
- `ema_slow_period = 50`
- `breakout_lookback = 20`
- `adx_period = 14`
- `min_adx = 20`
- `atr_period = 14`
- `min_atr_percent = 0.4`

### Exit

Once in position, exit on the first condition hit:
- initial stop loss: `entry_price - atr * stop_atr_multiple`
- trailing stop: `highest_price_since_entry - atr * trailing_atr_multiple`
- trend failure: `ema_fast < ema_slow`
- optional fixed take profit, disabled by default

Recommended initial defaults:
- `stop_atr_multiple = 1.5`
- `trailing_atr_multiple = 2.0`
- `use_trend_failure_exit = true`
- `take_profit_percent = null`

### Position Model

- one entry only in v1
- no pyramiding
- no safety orders
- no partial exits

## Proposed Config Shape

Preferred long-term shape:

```toml
[strategy]
type = "momentum"

[strategy.momentum]
symbol = "ETH_USDT_Perp"
side = "buy"
quote_amount = "500"
order_type = "market"
limit_price_offset_percent = "0.05"
initial_leverage = "5"
margin_type = "CROSS"
max_cycles = 5

timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
use_trend_failure_exit = true
take_profit_percent = null

state_file = "/state/.gravity-momentum-eth.json"
```

If multi-strategy config is deferred, a temporary flat `[momentum]` section is acceptable.

## Proposed Bot State

Active position state should track:
- `symbol`
- `side`
- `started_at`
- `total_quantity`
- `total_cost`
- `average_entry_price`
- `leverage`
- `margin_type`
- `last_order_id`
- `last_client_order_id`
- `highest_price_since_entry`
- `initial_stop_price`
- `trailing_stop_price`
- `breakout_level`
- `timeframe`

Closed position state should track:
- `side`
- `closed_at`
- `exit_reason`
- `average_entry_price`
- `exit_price`
- `total_quantity`
- `realized_pnl_estimate`
- `leverage`
- `margin_type`

## Implementation Phases

### Phase 1: Candle Data Support

Status: implemented

Goal:
- support OHLCV or equivalent candle-history reads for momentum indicators

Tasks:
- add exchange-layer candle fetch support
- define an exchange-neutral candle model
- validate available GRVT timeframe support
- add tests around candle parsing

Completion criteria:
- bot can fetch recent candles for one symbol and timeframe

Delivered:
- added exchange-neutral `Candle` model
- added `GrvtMarketData.get_candles(...)`
- added `GrvtExchange.get_candles(...)`
- verified installed GRVT SDK exposes `fetch_ohlcv(...)` with CCXT-style timeframe support
- added parsing and transient-error tests

### Phase 2: Indicator Layer

Status: implemented

Goal:
- compute the exact indicators required for the first momentum strategy

Tasks:
- add EMA calculation
- add ATR calculation
- add ADX calculation
- add breakout-high / highest-close helper
- keep the indicator layer independent from exchange code

Completion criteria:
- deterministic unit tests for indicator outputs

Delivered:
- added pure indicator helpers in `gravity_dca.indicators`
- implemented EMA with SMA seeding
- implemented true range and Wilder ATR
- implemented Wilder ADX
- implemented highest-close helper with optional latest-candle offset
- added deterministic unit tests for indicator values and validation paths

### Phase 3: Config Model

Status: implemented

Goal:
- add config parsing for the momentum strategy

Tasks:
- add momentum config dataclass(s)
- validate required and optional fields
- decide whether to introduce a top-level strategy selector now or defer it
- add example config

Completion criteria:
- config parsing tests pass for valid and invalid momentum configs

Delivered:
- added `MomentumSettings` config dataclass
- added config parsing for flat `[momentum]` configs
- added compatibility parsing for selector-style `[strategy] type = "momentum"` with `[strategy.momentum]`
- kept legacy DCA configs unchanged and operational
- added `config.momentum.example.toml`
- added valid and invalid momentum config parsing tests

### Phase 4: State Model

Status: implemented

Goal:
- add dedicated momentum state persistence

Tasks:
- add active and closed momentum state models
- add save/load support
- decide whether to reuse the current state file structure or create a strategy-specific one

Completion criteria:
- momentum state round-trip tests pass

Delivered:
- added dedicated momentum state models in `gravity_dca.momentum_state`
- separated active position and closed position persistence from DCA cycle state
- added JSON load/save helpers for momentum state files
- added active-position update helpers for trailing-stop and breakout metadata
- added round-trip and validation tests for momentum state persistence

### Phase 5: Strategy Logic

Status: implemented

Goal:
- implement pure momentum decision-making independent of exchange I/O

Tasks:
- implement entry conditions
- implement initial stop computation
- implement trailing stop updates
- implement trend failure exit
- implement max-cycle handling

Completion criteria:
- strategy unit tests cover entry, hold, stop, trail, and exit cases

Delivered:
- added pure momentum strategy helpers in `gravity_dca.momentum_strategy`
- implemented entry checks for trend, breakout, ADX, ATR percent, and max-cycle gating
- implemented initial stop and trailing-stop computation
- implemented trend-failure and optional take-profit exits
- added unit tests for entry, hold, stop-loss, trailing-stop progression, and trend-failure exits

### Phase 6: Bot Orchestration

Status: implemented

Goal:
- add a runtime bot flow for momentum execution

Tasks:
- add order planning and execution path for momentum
- reuse fill-confirmed persistence pattern
- reuse Telegram notification pattern
- ensure dry-run behavior is correct

Completion criteria:
- end-to-end orchestration tests pass with mocked exchange responses

Delivered:
- added a dedicated `MomentumBot` runtime flow in `gravity_dca.momentum_bot`
- reused shared order submission, fill-confirmed persistence, notifier, and runtime-status patterns
- added CLI dispatch to run momentum configs through `MomentumBot`
- extended bot-local status snapshots and notifier helpers to support momentum configs
- added orchestration tests for dry-run entry, live entry persistence, and live exit persistence

### Phase 7: Recovery

Status: implemented

Goal:
- make momentum restart-safe

Tasks:
- recover active position from exchange position snapshot
- recover last entry metadata from recent fills if possible
- recompute trailing stop from current ATR on startup
- fail safely on material mismatch

Completion criteria:
- restart tests pass with missing local state and live exchange position

Delivered:
- added momentum-specific recovery in `gravity_dca.momentum_recovery`
- reconciles local momentum state against live exchange position before each momentum iteration
- rebuilds local active position from exchange position and reuses recent fill metadata when possible
- recomputes trailing-stop state from current ATR-backed indicator context on recovery
- preserves local active state on transient exchange recovery errors for the current iteration
- added recovery tests for rebuild, keep-local refresh, stale-local clear, and mismatch failure paths

### Phase 8: CLI and Operator Tooling

Status: implemented

Goal:
- expose momentum state and diagnostics from the command line

Tasks:
- add `status` support for momentum state
- add threshold/stop inspection for momentum
- ensure Make targets stay clear and consistent

Completion criteria:
- operator commands work for both DCA and momentum flows

Delivered:
- added momentum-aware `status` output in `gravity_dca.cli`
- added momentum-aware `thresholds` output in `gravity_dca.cli`
- added momentum-aware `recovery-status` output in `gravity_dca.cli`
- included current indicator and stop metadata in momentum status reporting
- added CLI tests covering momentum operator commands

### Phase 9: Documentation

Goal:
- document setup and operation clearly

Tasks:
- update `README.md`
- update `AGENTS.md`
- add a momentum example config
- document recommended first live rollout sequence

Completion criteria:
- docs reflect implemented momentum behavior and limitations

### Phase 10: Live Rollout

Goal:
- validate the first version safely on GRVT

Tasks:
- start with `dry_run = true`
- first live symbol: `ETH_USDT_Perp`
- use small quote sizing and low leverage
- verify Telegram notifications and recovery behavior
- only then consider `BTC_USDT_Perp`

Completion criteria:
- one live ETH cycle completed without manual intervention

## Recommended Initial Live Defaults

ETH:
- `quote_amount = 500`
- `initial_leverage = 3`

BTC:
- `quote_amount = 750`
- `initial_leverage = 3`

Operational defaults:
- `order_type = market`
- `timeframe = 5m`
- `ema_fast_period = 20`
- `ema_slow_period = 50`
- `breakout_lookback = 20`
- `min_adx = 20`
- `stop_atr_multiple = 1.5`
- `trailing_atr_multiple = 2.0`

## Non-Goals For V1

Not in the first version:
- short-side trading
- pyramiding
- partial exits
- multi-timeframe confirmation
- maker-only execution
- portfolio-level momentum allocation
- multi-strategy framework unless needed to support the implementation cleanly

## Risks

- Candle availability or quality may limit indicator reliability.
- ADX and ATR depend on consistent historical data; if GRVT candle support is thin, the signal set may need to be simplified.
- A momentum bot will underperform badly in chop unless filters are strict enough.
- Adding momentum without a clean strategy boundary can tangle the current DCA-oriented architecture.

## Resume Notes

If resuming this work in a later session:
- read this file first
- check whether exchange candle support already exists
- confirm whether the implementation should happen behind a strategy selector or as a parallel bot path
- prefer ETH as the first live validation symbol
