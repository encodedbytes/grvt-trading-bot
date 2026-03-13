# Limit Order Support Tasks

This document tracks the implementation plan for adding limit-order support to the GRVT futures DCA bot. It is intended to persist across sessions and provide enough structure to resume work without re-planning.

## Goal

Add configurable limit-order support without breaking the current market-order workflow or the bot's fill-confirmed state guarantees.

## Scope

In scope:
- Configurable `market` or `limit` order execution
- GRVT-compatible limit price and size alignment
- Timeout handling for unfilled limit orders
- State safety: no cycle mutation until confirmed fill
- Test coverage and operator documentation updates

Out of scope for the first pass:
- Post-only or maker-only behavior
- Advanced repricing loops
- Partial-fill inventory accounting
- Exchange-side reconstruction of local state

## Principles

- Keep the current market-order path working unchanged by default.
- Separate strategy decisions from execution details.
- Persist state only after confirmed fills.
- Prefer simple timeout behavior over complex adaptive order management.

## Task List

### 1. Config Surface

Status: completed

Tasks:
- Add `order_type` to [config.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/config.py) with allowed values `market` and `limit`.
- Add optional limit settings:
  - `limit_price_offset_percent`
  - `limit_ttl_seconds`
  - `limit_reprice_on_timeout` or a simpler timeout policy flag
- Keep current configs backward-compatible by defaulting to `market`.
- Update [config.example.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.example.toml).

Completion criteria:
- Existing configs load unchanged.
- A limit-order config validates cleanly.

### 2. Strategy and Execution Separation

Status: completed

Tasks:
- Refactor [strategy.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/strategy.py) so it returns an execution intent instead of a fully concrete market order.
- Preserve current trigger logic for:
  - initial entry
  - safety order
  - take profit
  - stop loss
- Keep strategy responsible for "what action should happen" and exchange/order builder responsible for "how to place it".

Completion criteria:
- Strategy can describe the same action for both market and limit execution paths.
- No trading behavior changes for the market path.

### 3. Exchange Limit Order Path

Status: completed

Tasks:
- Extend [exchange.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/exchange.py) to place `limit` orders with:
  - aligned `price`
  - aligned `amount`
  - existing `reduce_only`
  - existing `client_order_id`
- Reuse current tick-size rounding for price alignment.
- Reuse current min-size / base-decimal alignment for amount.

Completion criteria:
- Exchange layer can place both market and limit orders through one consistent interface.
- Price alignment is explicit and tested.

### 4. Limit Pricing Rules

Status: completed

Tasks:
- Define deterministic aggressive limit pricing rules:
  - long entry/safety buy: ask plus offset
  - long exit: bid minus offset
  - short side: mirrored logic
- Add offset handling using `limit_price_offset_percent`.
- Document that these are marketable or near-marketable limits, not passive maker orders.

Completion criteria:
- Limit prices are derived from live market data predictably.
- Price rounding respects GRVT tick size.

### 5. Fill Waiting and Timeout Policy

Status: completed

Tasks:
- Extend [bot.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/bot.py) execution flow to support limit orders that may remain open.
- Add timeout polling using `limit_ttl_seconds`.
- On timeout, implement a simple first-pass policy:
  - cancel and fail, or
  - cancel and optionally fall back to market
- Keep the first version simple; avoid complex repricing loops.

Completion criteria:
- The bot does not hang indefinitely on resting limit orders.
- Timeout behavior is configurable and documented.

### 6. State Safety

Status: completed

Tasks:
- Preserve the existing rule that local cycle state changes only after a confirmed fill.
- Ensure unfilled, canceled, or expired limit orders do not mutate:
  - active cycle
  - last order id
  - average entry
  - completed safety count
- Confirm this behavior for both entry and exit actions.

Completion criteria:
- No fake cycle or false exit state can be created by an unfilled limit order.

### 7. Tests

Status: completed

Tasks:
- Add config parsing tests for `order_type` and limit settings.
- Add unit tests for limit price derivation and alignment.
- Add bot-flow tests for:
  - successful filled limit order
  - unfilled timeout
  - canceled order
  - no state mutation on no-fill
- Keep all existing tests passing.

Completion criteria:
- Test suite covers the new branch points introduced by limit orders.
- Existing market-order behavior remains covered and stable.

### 8. Documentation

Status: completed

Tasks:
- Update [README.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/README.md) with:
  - `market` vs `limit`
  - limit timeout behavior
  - operational caveats for unfilled orders
- Update [AGENTS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/AGENTS.md) with only the minimal resume info needed for the new execution mode.
- Update [config.example.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.example.toml) to show both safe defaults and limit options.

Completion criteria:
- Human docs and resume docs are aligned with the new implementation.

## Suggested Implementation Order

1. Config surface
2. Strategy and execution separation
3. Exchange limit order path
4. Limit pricing rules
5. Fill waiting and timeout policy
6. State safety verification
7. Tests
8. Documentation

## Risks to Watch

- Limit orders may rest and not fill quickly, especially on fast moves.
- Incorrect price rounding can cause exchange rejection.
- Timeout and cancel behavior must not leave local state inconsistent.
- Entry and exit behavior must remain symmetric for long and short.
- The market path must remain the default and stay backward-compatible.

## Notes For Future Sessions

- The current bot is stable on GRVT prod using market orders.
- State is local and trusted; it is not rebuilt from exchange history.
- Fill-confirmed persistence is already implemented and must not be weakened.
- Any limit-order implementation should preserve the same safety guarantee before expanding features.
- First-pass limit-order support is now implemented.
- Limit orders use aggressive prices derived from live bid/ask plus `limit_price_offset_percent`.
- If a limit order is not filled within `runtime.limit_ttl_seconds`, the bot cancels it and leaves local state unchanged.
- Advanced repricing, post-only, and partial-fill handling are still out of scope.
