# Gravity App Skills

## What Was Learned

### 1. GRVT price fields are not consistently represented the way older SDK helpers imply

The live GRVT market-data responses used in this app returned decimal strings such as:
- `best_ask_price = "2024.41"`
- `best_bid_price = "36.019"`

Older assumptions about 1e9-scaled integer price fields caused incorrect sizing.

Practical rule:
- Parse decimal strings directly.
- Only apply 1e9 scaling fallback when the payload is clearly an integer-style encoded price.

### 2. `min_notional` is necessary but insufficient

A quote budget can pass `min_notional` and still fail `min_size`.

Examples observed live:
- `ETH_USDT_Perp`: `min_notional = 20.0`, `min_size = 0.01`
- `HYPE_USDT_Perp`: `min_notional = 5.0`, `min_size = 1.0`

Practical rule:
- Validate both:
  - `quote_amount >= min_notional`
  - aligned size `>= min_size`

### 3. Size must be aligned to tradable market increments

Rounding only to `base_decimals` was not enough.

Observed failure from GRVT:
- `Order size too granular`

Practical rule:
- First round to `base_decimals`
- Then snap down to a multiple of `min_size`

### 4. Submit acknowledgment is not a fill

GRVT may accept the create-order request and return a response before the order is fully resolved.

Observed behavior:
- create-order returned an acknowledgment with placeholder `order_id = 0x00`
- order lookup later returned the actual order id and fill state

Practical rule:
- Poll the order endpoint by `client_order_id`
- Persist cycle state only after:
  - `traded_size > 0`
  - `avg_fill_price > 0`

### 5. The real order id must come from follow-up order status

The create-order response can carry a temporary or placeholder id.

Practical rule:
- Use the `order` lookup endpoint to capture the final real `order_id`
- Store that id in local state, not the initial ack id

### 6. Testnet and production behavior can differ meaningfully

Observed:
- Production auth worked correctly with the provided credentials
- Testnet auth failed because the credentials were not valid there

Practical rule:
- Confirm environment and credentials match before debugging code paths
- Treat auth failures as possible environment mismatch first

### 7. The SDK is usable, but its abstractions are not enough by themselves

The app needed additional guardrails around the SDK:
- explicit auth preflight for private requests
- market-aware size alignment
- order fill polling
- defensive state persistence behavior

Practical rule:
- Wrap exchange SDKs with local validation and state rules
- Do not trust exchange acks or client libraries to fully model the trading lifecycle

## Operational Heuristics

- Use `make instrument CONFIG=config.toml SYMBOL=<symbol>` before changing symbols.
- Keep `dry_run = true` until instrument constraints and live prices are verified.
- If a live order is rejected, inspect `.gravity-dca-state.json` before rerunning.
- If local state and exchange state differ, prefer exchange order lookup as source of truth.

## Current Matured Capabilities

The app now knows how to:
- inspect live GRVT instrument constraints
- align order size to exchange requirements
- submit signed GRVT market orders
- confirm fills by polling GRVT order status
- persist a DCA cycle from actual fill data instead of optimistic submit responses
