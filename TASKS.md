# Limit Order Support

Status: implemented

This file is now a completion record for the first-pass limit-order work. It is no longer an active task checklist.

## Implemented

The bot now supports:
- `market` and `limit` order execution modes
- aggressive limit pricing based on live bid/ask plus `limit_price_offset_percent`
- configurable limit order TTL via `runtime.limit_ttl_seconds`
- cancel-on-timeout behavior for unfilled limit orders
- fill-confirmed state updates only
- threshold inspection from the command line via `--thresholds`

## Verified Behavior

Verified locally:
- config parsing for limit-order settings
- limit price derivation and alignment
- compile check and automated tests

Verified live on GRVT prod:
- filled limit order path
- timed-out and canceled limit order path
- no local state mutation on no-fill
- correct state persistence on fill

## What Was Delivered

Core files updated:
- [config.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/config.py)
- [strategy.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/strategy.py)
- [exchange.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/exchange.py)
- [bot.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/bot.py)
- [cli.py](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/src/gravity_dca/cli.py)

Operator docs updated:
- [README.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/README.md)
- [AGENTS.md](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/AGENTS.md)
- [config.example.toml](/Users/gsantovena/Projects/Crypto_Strategies/Gravity/config.example.toml)

## Future Enhancements

Not included in the first pass:
- post-only / maker-only execution
- automatic repricing for resting limit orders
- partial-fill inventory handling
- exchange-state reconstruction when the local state file is missing or stale

## Notes For Future Sessions

- The current limit-order implementation is intentionally simple and safe.
- If a limit order is not filled within `runtime.limit_ttl_seconds`, it is canceled and local state is left unchanged.
- The default market-order path remains supported and backward-compatible.
- Any future work on maker strategies or advanced order management should build on this implementation rather than replace it.
