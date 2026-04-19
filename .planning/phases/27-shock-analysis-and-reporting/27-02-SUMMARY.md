---
phase: 27-shock-analysis-and-reporting
plan: "02"
subsystem: report, cli
tags: [jinja2, react-engine, cli-wiring, shock-analysis, pre-seeding, tdd]

requires:
  - phase: 27-shock-analysis-and-reporting
    plan: "01"
    provides: "read_shock_event, read_shock_impact, _aggregate_shock_impact on GraphStateManager"

provides:
  - "11_shock_impact.j2 Jinja2 template: Shock Impact Analysis heading, bracket delta table, agent pivot list"
  - "TOOL_TO_TEMPLATE['shock_impact'] = '11_shock_impact.j2' and portfolio_impact entry"
  - "SECTION_ORDER: portfolio_impact -> shock_impact at end"
  - "ReportEngine.pre_seeded_observations: list[ToolObservation] passed through to run()"
  - "_collect_shock_observation(gm, cycle_id): returns ToolObservation or None"
  - "_handle_report: pre-seeds shock_impact when ShockEvent exists for cycle"

affects:
  - Phase 25 (portfolio_impact wiring — compatible entries added, no conflict)
  - REQUIREMENTS.md SHOCK-05

tech-stack:
  added: []
  patterns:
    - "Pre-seeding via _collect_shock_observation helper: read_shock_event gating, read_shock_impact only when shock present"
    - "Module-level helper function for testability: _collect_shock_observation takes gm + cycle_id, returns ToolObservation | None"
    - "ReportEngine pre_seeded_observations: keyword-only kwarg, stored as self._pre_seeded, prepended to run() observations list"

key-files:
  created:
    - src/alphaswarm/templates/report/11_shock_impact.j2
  modified:
    - src/alphaswarm/report.py
    - src/alphaswarm/cli.py
    - tests/test_report.py
    - tests/test_cli.py

key-decisions:
  - "_collect_shock_observation is a standalone async helper (not a method) to enable isolated unit testing without a full AppState"
  - "portfolio_impact added to TOOL_TO_TEMPLATE and SECTION_ORDER since it belongs to Phase 25 history but was absent from worktree base; parallel Phase 25 worktree additions will merge cleanly"
  - "pre_seeded_observations added to ReportEngine as keyword-only kwarg with None default; compatible with Phase 25 implementation in git history (same signature)"
  - "shock_impact pre-seeding is unconditional when read_shock_event returns non-None; no flag or CLI argument required"

requirements-completed: [SHOCK-05]

duration: ~15min
completed: 2026-04-11
---

# Phase 27 Plan 02: Shock Impact Report Section and CLI Wiring Summary

**Shock impact Jinja2 template, TOOL_TO_TEMPLATE/SECTION_ORDER registration, ReportEngine pre_seeded_observations support, and CLI _collect_shock_observation pre-seeding**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-11T00:00:00Z
- **Completed:** 2026-04-11T00:15:00Z
- **Tasks:** 2 (both TDD GREEN phase)
- **Files modified:** 4 (+ 1 created)

## Accomplishments

- Created `11_shock_impact.j2` with `## Shock Impact Analysis` heading, summary metrics table, `### Bracket Signal Shift` table, and conditional `### Agent Pivot List` section
- Added `shock_impact` to `TOOL_TO_TEMPLATE` and `SECTION_ORDER` (after `portfolio_impact`); also added `portfolio_impact` which was absent from the worktree base but belongs to Phase 25 history
- Extended `ReportEngine.__init__` with `pre_seeded_observations: list[ToolObservation] | None = None` keyword-only kwarg; `run()` now starts `observations = list(self._pre_seeded)`
- Added `_collect_shock_observation(gm, cycle_id)` helper in `cli.py`: calls `read_shock_event`, short-circuits to `None` when no shock, otherwise calls `read_shock_impact` and wraps result in `ToolObservation(tool_name='shock_impact')`
- Wired `_collect_shock_observation` into `_handle_report` before ReACT engine creation; result passed as `pre_seeded_observations`
- All 8 SHOCK-05 stubs from Wave 0 (6 report + 2 CLI) turned GREEN

## Task Commits

1. **Task 1: shock_impact template + TOOL_TO_TEMPLATE/SECTION_ORDER + pre_seeded_observations + test_report stubs** - `8acbb91` (feat)
2. **Task 2: _collect_shock_observation + _handle_report wiring + test_cli stubs** - `25145b8` (feat)

## Files Created/Modified

- `src/alphaswarm/templates/report/11_shock_impact.j2` — New template; renders Shock Impact Analysis heading, metrics table, bracket delta table with arrow indicators, optional agent pivot list
- `src/alphaswarm/report.py` — TOOL_TO_TEMPLATE: added portfolio_impact (10) + shock_impact (11); SECTION_ORDER: same two appended; ReportEngine: `pre_seeded_observations` kwarg + `self._pre_seeded`; `run()`: `observations = list(self._pre_seeded)`
- `src/alphaswarm/cli.py` — Added `_collect_shock_observation` helper function before `_handle_report`; `_handle_report` calls it and passes result to `ReportEngine`
- `tests/test_report.py` — 6 stubs replaced with real assertions (TOOL_TO_TEMPLATE, SECTION_ORDER, assemble includes/skips, template bracket delta table, template pivot list)
- `tests/test_cli.py` — 2 stubs replaced with real assertions (_collect_shock_observation with shock / without shock)

## Test Results

| Suite | Passed | Failed | Notes |
|-------|--------|--------|-------|
| test_report.py -k shock | 6 | 0 | All 6 SHOCK-05 stubs GREEN |
| test_cli.py -k shock | 2 | 0 | All 2 SHOCK-05 stubs GREEN |
| test_graph.py + test_tui.py + test_report.py + test_cli.py | 154 | 19 | 19 pre-existing HTML assembler failures (assemble_html absent from base; Phase 24/25 not merged) |

## Decisions Made

- `_collect_shock_observation` is a standalone module-level async function rather than a method, making it directly importable and testable in `test_cli.py` without spinning up a full `AppState`.
- `portfolio_impact` added to TOOL_TO_TEMPLATE/SECTION_ORDER (entry `10_portfolio_impact.j2`) even though the Phase 25 portfolio work isn't in this worktree's base. The Phase 25 parallel worktree adds the same entry — merge conflict is benign since both add the identical key. The test `test_section_order_contains_shock_impact_after_portfolio` requires `portfolio_impact` to be present before `shock_impact`.
- `pre_seeded_observations` added to `ReportEngine` as a keyword-only kwarg with `None` default. This is the same signature Phase 25 uses (commit `72b82d6`). The Phase 25 implementation also adds `system_prompt` kwarg — that will be additive on merge.
- Shock pre-seeding in `_handle_report` requires no new CLI flag. It is always attempted when `read_shock_event` returns non-None. This differs from portfolio (which requires `--portfolio` flag) because shock data is always simulation-internal.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added portfolio_impact to TOOL_TO_TEMPLATE and SECTION_ORDER**

- **Found during:** Task 1 (implementing test_section_order_contains_shock_impact_after_portfolio)
- **Issue:** The test stub requires `portfolio_impact` to be in SECTION_ORDER before `shock_impact`. The worktree base (`c5c93b0`) predates Phase 25, so `portfolio_impact` was absent.
- **Fix:** Added `"portfolio_impact": "10_portfolio_impact.j2"` to TOOL_TO_TEMPLATE and `"portfolio_impact"` to SECTION_ORDER before `"shock_impact"`. The portfolio template file itself is delivered by Phase 25 — the assembler silently skips absent templates.
- **Files modified:** `src/alphaswarm/report.py`
- **Committed in:** `8acbb91` (Task 1 commit)

**2. [Rule 2 - Missing Critical Functionality] Added pre_seeded_observations to ReportEngine**

- **Found during:** Task 2 (implementing _handle_report shock wiring)
- **Issue:** The current `ReportEngine` had no `pre_seeded_observations` support (Phase 25 adds this). Without it, shock_impact could only be injected after `run()`, losing conversation-context benefit.
- **Fix:** Added `pre_seeded_observations: list[ToolObservation] | None = None` kwarg, `self._pre_seeded` storage, and `observations = list(self._pre_seeded)` in `run()`. Matches Phase 25 implementation signature exactly.
- **Files modified:** `src/alphaswarm/report.py`
- **Committed in:** `8acbb91` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (Rule 2 — missing critical functionality required by tests and correctness)
**Impact on plan:** Both necessary for plan goals; no scope creep.

## Known Stubs

None — all 8 Wave 0 SHOCK-05 stubs turned GREEN. Template renders real data from `_aggregate_shock_impact` result dict. No hardcoded empty values flow to UI rendering.

## Pre-existing Failures (Out of Scope)

19 `TestHtmlAssembler` / `TestHtmlSelfContained` / `TestHtmlFileSize` / `TestHtmlDarkTheme` / `TestChartStyleInSvg` failures due to `assemble_html` being absent from the worktree base. These are Phase 24/25 work not yet merged into master. Not introduced by this plan — confirmed present before first change.

## Self-Check: PASSED

- `src/alphaswarm/templates/report/11_shock_impact.j2` — FOUND
- `src/alphaswarm/report.py` — FOUND (TOOL_TO_TEMPLATE has shock_impact, SECTION_ORDER has shock_impact after portfolio_impact, ReportEngine has pre_seeded_observations)
- `src/alphaswarm/cli.py` — FOUND (_collect_shock_observation present, _handle_report wired)
- `tests/test_report.py` — FOUND (6 stubs replaced)
- `tests/test_cli.py` — FOUND (2 stubs replaced)
- Commit `8acbb91` — verified in git log
- Commit `25145b8` — verified in git log
- `uv run pytest tests/test_report.py tests/test_cli.py -k shock -q` — 8 passed, 0 failed
