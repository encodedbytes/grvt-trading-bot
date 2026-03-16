# Telegram Notifications

Status: implemented

This file is now a completion record for the first-pass Telegram notification work. It is no longer an active task checklist.

## Implemented

The bot now supports optional one-way Telegram notifications for:
- bot startup
- startup recovery result
- initial entry fill
- safety order fill
- take profit fill
- stop loss fill
- bot inactive after reaching `max_cycles`
- limit timeout and cancel
- iteration failure
- leverage or margin config changes
- explicit notifier verification via `--notify-test`

## Verified Behavior

Verified locally:
- Telegram config parsing
- notifier error handling
- message formatting
- bot startup and recovery notification hooks
- compile check and automated tests

Verified live:
- `--notify-test` successfully delivered a real Telegram message
- five running bot containers were restarted and startup notifications were received successfully

## What Was Delivered

Core files updated:
- [config.py](src/gravity_dca/config.py)
- [telegram.py](src/gravity_dca/telegram.py)
- [bot.py](src/gravity_dca/bot.py)
- [cli.py](src/gravity_dca/cli.py)

Operator docs updated:
- [config.example.toml](config.example.toml)
- [README.md](README.md)
- [AGENTS.md](AGENTS.md)
- [Makefile](Makefile)

Tests added:
- [test_config.py](tests/test_config.py)
- [test_telegram.py](tests/test_telegram.py)

## Future Enhancements

Not included in the first pass:
- Telegram command handling
- bot control or trade execution from chat
- heartbeat notifications
- on-demand status queries from Telegram
- multi-chat or multi-user notification routing

## Notes For Future Sessions

- Telegram failures are logged but do not block trading.
- The notifier is optional and disabled by default.
- The first version is deliberately one-way only.
- Any future command/control work should be treated as a separate feature with stricter safety design.
