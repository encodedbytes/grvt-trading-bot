---
name: grvt-futures-dca
description: Build, review, debug, or operate Python trading bots for GRVT perpetual markets. Use when working on GRVT auth, market metadata, order sizing, leverage or margin configuration, fill confirmation, or local bot state for DCA-style futures strategies.
---

# GRVT Futures DCA

Use this skill when the task involves a Python bot that trades GRVT perpetuals and needs exchange-specific handling rather than generic exchange logic.

## Scope

This skill is for:
- GRVT market metadata and ticker handling
- quote-to-size conversion for perpetual orders
- leverage and `margin_type` configuration
- market-order lifecycle and fill confirmation
- local state persistence for DCA cycle bots
- multi-bot operation with separate config and state files

This skill is not for:
- generic portfolio advice
- strategy profitability claims
- non-GRVT exchange integrations

## Workflow

1. Read the local config and identify:
   - `environment`
   - `trading_account_id`
   - `symbol`
   - `state_file`
   - `dry_run`
   - `initial_leverage`
   - `margin_type`
2. Check the current GRVT instrument metadata before changing sizing.
3. Treat order sizing as valid only if both `min_notional` and `min_size` pass after alignment.
4. Treat create-order acknowledgment as provisional.
5. Persist local cycle state only after a real fill is confirmed.
6. If multiple bots are involved, require a unique `state_file` per bot.

## GRVT Rules

### Price parsing

GRVT price fields may arrive as normal decimal strings.

Use this rule:
- If the value already contains a decimal point, parse it directly.
- Only apply the legacy `1e9` scaling fallback when the payload is clearly integer-encoded.

Do not assume old SDK comments match live payloads.

### Instrument validation

Before accepting a quote budget:
- verify `quote_amount >= min_notional`
- compute base size from live entry price
- align size to market increments
- verify aligned size `>= min_size`

For this bot, alignment must happen in this order:
1. round to `base_decimals`
2. snap down to a multiple of `min_size`

If you skip the second step, GRVT may reject the order as too granular.

### Order model

For this project, entries and exits are market orders unless the user explicitly asks to change that.

Treat the submission lifecycle as:
1. submit order
2. capture `client_order_id`
3. poll order status by `client_order_id`
4. require non-zero `traded_size`
5. require non-zero `avg_fill_price`
6. store the final `order_id` from order lookup, not the placeholder submit ack id

### Leverage and margin type

Use GRVT instrument-level position config, not just sub-account summary, when comparing desired leverage or `margin_type`.

Normalize cross-margin variants:
- `CROSS`
- `CROSS_MARGIN`
- `SIMPLE_CROSS_MARGIN`
- `PORTFOLIO_CROSS_MARGIN`

Treat them as the same effective cross-margin family unless the local code intentionally distinguishes them.

If a live position exists for the symbol:
- do not change `margin_type` automatically
- changing leverage may still be possible, but validate current behavior against GRVT responses

### Environment handling

Always verify the configured environment matches the credentials:
- `prod`
- `testnet`
- `staging`
- `dev`

If auth fails, check environment mismatch before assuming a code bug.

## Local State

The bot’s local state should capture the minimum data needed to resume a cycle safely:
- `symbol`
- `side`
- `started_at`
- `total_quantity`
- `total_cost`
- `average_entry_price`
- `completed_safety_orders`
- `last_order_id`
- `last_client_order_id`
- `leverage`
- `margin_type`

Closed-cycle history should carry forward:
- realized PnL estimate
- leverage used
- margin type used

Do not share one state file across multiple running bots.

## Multi-Bot Guidance

Safe pattern:
- one config file per bot
- one unique `state_file` per bot
- preferably one symbol per bot

Risky pattern:
- multiple bots sharing the same symbol on the same sub-account
- multiple bots sharing the same state file
- cross-margin bots sharing a sub-account without explicit capital separation

## Practical Checks

Use these checks before live trading:
- inspect instrument constraints first
- keep `dry_run = true` while changing symbol, environment, leverage, or budgets
- verify state file path is unique
- verify local state is consistent with the actual exchange position

## Known GRVT Behaviors

- `min_notional` alone is not enough; `min_size` can still reject the trade.
- ETH and HYPE can have very different `min_size` behavior even when `min_notional` looks small.
- Production and testnet behavior can differ because credentials may only exist in one environment.
- The SDK is useful, but local wrappers should still enforce auth checks, amount alignment, and fill confirmation.

## Output Expectations

When using this skill:
- prefer concrete config and code changes over abstract advice
- mention exchange constraints when recommending sizing changes
- call out when a local state file can become inconsistent with exchange state
- separate exchange-level truth from local bot-state assumptions
