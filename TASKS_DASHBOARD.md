# Dashboard Architecture Improvements

Status: planned

This file is the persistent implementation plan for structural dashboard work after the momentum rollout.

## Objective

Reduce dashboard coupling and regression risk by separating UI rendering, Docker discovery, bot-status normalization, and HTTP serving into smaller focused modules.

The goal is not a visual redesign. The goal is to make the dashboard easier to change safely.

## Current Problems

- `src/gravity_dca/dashboard.py` carries HTML, CSS, JavaScript, HTTP serving, Docker CLI/API access, bot API access, payload normalization, and fallback state loading in one module.
- The dashboard currently maintains more than one status-shaping path, which already caused drift between DCA and momentum support.
- UI changes and backend inspection changes are forced through the same file, which raises review cost and regression risk.

## Target Shape

Preferred structure:

- `dashboard.py`
  - thin HTTP entry point only
- `dashboard_payload.py`
  - shared bot-summary shaping and normalization
- `dashboard_discovery.py`
  - Docker container listing and config/source discovery
- `dashboard_runtime.py`
  - bot API fetches, Docker fallback reads, and log access
- `dashboard_template.py`
  - static HTML/CSS/JS page template

Exact filenames can change if a cleaner split becomes obvious during implementation, but the responsibility split should stay roughly this sharp.

## Phase 1: Extract Payload Builder

Status: implemented

Goal:
- make the dashboard use one shared summary-building path for DCA and momentum

Tasks:
- move normalization helpers out of `dashboard.py`
- reuse `build_status_snapshot(...)` wherever possible
- keep Docker-specific fields as a thin wrapper around the shared payload

Completion criteria:
- one canonical dashboard summary shape exists
- DCA and momentum regressions are covered in tests

Delivered:
- extracted shared payload helpers into `gravity_dca.dashboard_payload`
- moved threshold defaults, status normalization, and container/error summary assembly out of `dashboard.py`
- kept `dashboard.py` focused on discovery, runtime access, and HTTP serving
- added direct payload-layer tests alongside existing dashboard end-to-end tests

## Phase 2: Extract Runtime Access Layer

Status: implemented

Goal:
- separate Docker and bot-API access from payload shaping

Tasks:
- move bot API fetch logic into a runtime-access module
- move Docker socket/file/log helpers into the same access layer
- keep transport errors localized and easy to test

Completion criteria:
- `dashboard.py` no longer contains Docker transport details
- runtime access can be unit-tested without the HTML template in scope

Delivered:
- extracted Docker socket access, Docker CLI fallback, bot API fetches, log loading, and container discovery into `gravity_dca.dashboard_runtime`
- kept `dashboard.py` behavior-preserving by importing the runtime helpers through stable local aliases
- added direct runtime-layer tests in `tests/test_dashboard_runtime.py`

## Phase 3: Extract Template

Status: implemented

Goal:
- isolate the HTML/CSS/JS page from backend logic

Tasks:
- move `HTML_PAGE` into a template-focused module
- keep the page static and string-based for now; do not introduce a templating engine unless necessary
- preserve existing behavior and tests

Completion criteria:
- UI changes no longer require editing the transport/HTTP module
- template-level tests still pass

Delivered:
- moved the static dashboard HTML/CSS/JS page into `gravity_dca.dashboard_template`
- kept the page string-based; no templating engine was introduced
- updated `dashboard.py` to import the template module instead of owning the large inline string
- verified the existing template assertions still pass unchanged

## Phase 4: Tighten Bot Detail Schema

Status: implemented

Goal:
- remove remaining DCA naming leakage from the dashboard UI

Tasks:
- replace generic `active_cycle`/`last_closed_cycle` UI assumptions with strategy-aware labels in the payload layer
- decide whether the UI should keep a normalized common schema or render strategy-specific sections explicitly
- make signal/threshold sections consistent between vertical cards, horizontal cards, and the drawer

Completion criteria:
- no DCA-only naming assumptions leak into momentum rendering paths
- the payload contract is explicitly documented in code/tests

Delivered:
- added generic trade-level payload fields such as `active_trade`, `last_closed_trade`, and corresponding `*_kind` markers
- switched the dashboard template and summary counting to use the generic trade fields instead of DCA-oriented names
- kept compatibility aliases in the payload layer so the transition stays low-risk
- added regression coverage for the tightened payload schema and generic trade rendering

## Phase 5: Operational Hardening

Status: planned

Goal:
- reduce operator ambiguity when the dashboard is partially degraded

Tasks:
- distinguish bot API data from Docker fallback data in the drawer
- expose when signal diagnostics are unavailable because the dashboard is in fallback mode
- consider a small health block for dashboard/runtime inspection capability

Completion criteria:
- the operator can tell whether a detail view is API-backed or fallback-backed
- degraded mode does not silently hide important runtime context

## Notes For Future Sessions

- Keep the current Solarized Dark visual language unless there is a deliberate redesign request.
- Avoid introducing a frontend framework for this refactor alone.
- Prefer small extraction steps with regression tests after each phase instead of a one-shot rewrite.
