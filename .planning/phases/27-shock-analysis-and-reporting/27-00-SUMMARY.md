---
phase: 27-shock-analysis-and-reporting
plan: "00"
subsystem: testing
tags: [wave-0, tdd, stubs, nyquist]
dependency_graph:
  requires: []
  provides: [27-01, 27-02]
  affects: []
tech_stack:
  added: []
  patterns: [pytest.fail RED stubs, pytest.mark.asyncio, deferred AttributeError via in-function import]
key_files:
  created: []
  modified:
    - tests/test_graph.py
    - tests/test_tui.py
    - tests/test_report.py
    - tests/test_cli.py
decisions:
  - Stubs use pytest.fail not bare pass — enforces RED state and prevents false GREEN
  - New APIs accessed inside function body (not module-level import) to defer AttributeError to runtime per T-02 threat model
metrics:
  duration: ~8 minutes
  completed: 2026-04-11T17:43:26Z
  tasks_completed: 2
  files_modified: 4
---

# Phase 27 Plan 00: Wave 0 Test Scaffolding Summary

**One-liner:** 15 failing RED stubs across 4 test files establishing Nyquist compliance before any Phase 27 production code lands.

## Objective

Create Wave 0 test scaffolding for Phase 27. All 15 test stubs compile, are collected by pytest, and fail with an explicit "Not yet implemented" message pointing to the implementing plan.

## Tasks Completed

### Task 1: Add graph + TUI test stubs
**Commit:** `2232d4c`
**Files:** `tests/test_graph.py`, `tests/test_tui.py`

Appended 7 failing stubs:

| # | Test Name | File | Plan Ref |
|---|-----------|------|----------|
| 1 | `test_read_shock_event_returns_dict_when_exists` | test_graph.py | Plan 01 |
| 2 | `test_read_shock_event_returns_none_when_no_shock` | test_graph.py | Plan 01 |
| 3 | `test_read_shock_impact_returns_per_agent_rows` | test_graph.py | Plan 01 |
| 4 | `test_read_shock_impact_pivot_flag_computed_correctly` | test_graph.py | Plan 01 |
| 5 | `test_bracket_panel_enable_delta_mode_triggers_refresh` | test_tui.py | Plan 01 |
| 6 | `test_bracket_panel_render_delta_uses_delta_data` | test_tui.py | Plan 01 |
| 7 | `test_bracket_panel_live_mode_unchanged_without_shock` | test_tui.py | Plan 01 |

### Task 2: Add report + CLI test stubs
**Commit:** `5e5faf6`
**Files:** `tests/test_report.py`, `tests/test_cli.py`

Appended 8 failing stubs:

| # | Test Name | File | Plan Ref |
|---|-----------|------|----------|
| 8 | `test_tool_to_template_contains_shock_impact` | test_report.py | Plan 02 |
| 9 | `test_section_order_contains_shock_impact_after_portfolio` | test_report.py | Plan 02 |
| 10 | `test_assemble_includes_shock_section_when_observation_present` | test_report.py | Plan 02 |
| 11 | `test_assemble_skips_shock_section_when_no_observation` | test_report.py | Plan 02 |
| 12 | `test_shock_impact_template_renders_bracket_delta_table` | test_report.py | Plan 02 |
| 13 | `test_shock_impact_template_renders_pivot_list` | test_report.py | Plan 02 |
| 14 | `test_shock_impact_preseeded_when_shock_event_exists` | test_cli.py | Plan 02 |
| 15 | `test_shock_impact_not_preseeded_when_no_shock_event` | test_cli.py | Plan 02 |

## Verification Results

### Collection check
- Task 1: 7 stubs collected — `wc -l` output `7`
- Task 2: 8 stubs collected — `wc -l` output `8`
- Full `-k shock` collection: 22 tests (15 new + 7 pre-existing Phase 26 shock tests)

### Failure check (4-stub sample)
All 4 sampled stubs fail with "Not yet implemented" message and exit non-zero.

### Full suite regression check
- Result: `15 failed, 705 passed, 5 warnings, 15 errors`
- The 15 failures = exactly the 15 new stubs (all correct RED state)
- The 15 errors = pre-existing `test_graph_integration.py` Neo4j connection errors (no Neo4j running in test environment, pre-existing before this plan)
- No new regressions introduced

## Deviations from Plan

None — plan executed exactly as written.

## Next Steps

Plans 01 and 02 run sequentially:
1. **Plan 01** (Wave 1) — Implement `GraphStateManager.read_shock_event` / `read_shock_impact` and `BracketPanel` delta mode, turning the 7 graph + TUI stubs GREEN
2. **Plan 02** (Wave 2, depends on Plan 01) — Implement shock impact Jinja2 template, `TOOL_TO_TEMPLATE`/`SECTION_ORDER` wiring, and CLI pre-seeding, turning the 8 report + CLI stubs GREEN

## Known Stubs

None beyond the 15 intentional RED stubs created by this plan. All stubs are intentional scaffolding — each references the plan that will implement them.

## Self-Check: PASSED

- `tests/test_graph.py` — modified, contains 4 new stubs
- `tests/test_tui.py` — modified, contains 3 new stubs
- `tests/test_report.py` — modified, contains 6 new stubs
- `tests/test_cli.py` — modified, contains 2 new stubs
- Commit `2232d4c` — verified in git log
- Commit `5e5faf6` — verified in git log
- No production code modified
