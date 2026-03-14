# Telegram Notifications

Status: planned

This document tracks the first-pass Telegram notification integration for the GRVT bot.

## Goal

Add one-way Telegram notifications for important bot events without introducing remote control or changing trading behavior.

## Scope

Include:
- optional Telegram config
- startup notification
- startup recovery notification
- initial entry fill notification
- safety order fill notification
- take profit notification
- stop loss notification
- limit timeout / cancel notification
- iteration failure notification
- leverage / margin config change notification
- a safe verification path, preferably a test notification command

Exclude for the first pass:
- Telegram command handling
- start/stop/reconfigure bot from chat
- trade execution from Telegram
- multi-user or group-admin logic
- complex chat UI or menus

## Implementation Plan

1. Add config support
- Extend `src/gravity_dca/config.py`
- Add optional `[telegram]` section
- Parse:
  - `enabled`
  - `bot_token`
  - `chat_id`
  - optional `send_startup_summary`
  - optional `notify_position_config_changes`

2. Add notifier module
- Create `src/gravity_dca/telegram.py`
- Implement:
  - `TelegramNotifier`
  - `NullNotifier`
- Keep Telegram transport logic isolated from bot orchestration and exchange logic

3. Add message formatting helpers
- Keep message formatting centralized and compact
- Ensure messages are stable and easy to scan in chat

4. Wire notifications into bot lifecycle
- Startup
- Recovery decision
- Initial entry fill
- Safety order fill
- Take profit fill
- Stop loss fill
- Limit timeout and cancel
- Position config change
- Iteration failure in `run_forever()`

5. Add a safe verification path
- Add a CLI test path, for example `--notify-test`
- It should validate config wiring without requiring a live trade event

6. Add tests
- Config parsing tests
- Notifier behavior tests
- Message formatting tests
- Bot event hook tests with a fake notifier

7. Update docs
- `config.example.toml`
- `README.md`
- `AGENTS.md`

## Design Constraints

- Telegram notification failures must not block trading.
- Telegram integration must be optional and disabled by default.
- No Telegram logic should be embedded in `exchange.py`.
- Use the notifier from the bot orchestration layer only.
- Keep the first version one-way only.

## Completion Criteria

The task is complete when:
- Telegram config is parsed and optional
- A notifier can send a test message
- Bot lifecycle events emit Telegram notifications
- Notification failures are logged but do not interrupt trading
- Docs and example config are updated
- Tests pass

## Notes For Future Sessions

- Start with notifications only; do not add chat commands in the same change.
- A no-op notifier should be the default path when Telegram is disabled.
- A future phase can add heartbeat or status-on-demand if needed.
