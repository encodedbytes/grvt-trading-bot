# Changelog

## v0.5.1 - 2026-04-21

- Hardened grid recovery so partial fills resting on still-open buy orders count toward live inventory reconciliation.
- Synced `sell_open` grid inventory quantity to the remaining live sell order size when fill snapshots lag behind exchange order state.
- Added regression coverage for partial-fill recovery paths in the grid bot/runtime tests.
- Refreshed `README.md` and `AGENTS.md` so the operator and agent docs match the current recovery behavior.

## v0.5.0 - 2026-04-03

- Added Ruff and a gradual mypy rollout, plus `make lint`, `make typecheck`, and `make check`.
- Documented the developer quality-check workflow in `README.md`.
- Hardened config loading so invalid DCA/runtime values fail earlier and more clearly.
- Restored grid bot-local API parity with DCA and momentum runtimes.
- Consolidated shared grid open-order normalization logic.
- Expanded static type coverage across core runtime, recovery, CLI, and GRVT integration modules.
