# Changelog

## v0.5.0 - 2026-04-03

- Added Ruff and a gradual mypy rollout, plus `make lint`, `make typecheck`, and `make check`.
- Documented the developer quality-check workflow in `README.md`.
- Hardened config loading so invalid DCA/runtime values fail earlier and more clearly.
- Restored grid bot-local API parity with DCA and momentum runtimes.
- Consolidated shared grid open-order normalization logic.
- Expanded static type coverage across core runtime, recovery, CLI, and GRVT integration modules.
