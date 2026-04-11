---
phase: 26-shock-injection-core
plan: "01"
subsystem: testing
tags: [tdd, scaffolding, shock-injection, wave-0]
dependency_graph:
  requires: []
  provides: [shock-test-stubs, mock-state-store-fixture]
  affects: [26-02, 26-03, 26-04, 26-05]
tech_stack:
  added: []
  patterns: [pytest-fail-stubs, conftest-fixture-sharing]
key_files:
  created: []
  modified:
    - tests/test_governor.py
    - tests/test_state.py
    - tests/test_graph.py
    - tests/test_tui.py
    - tests/test_simulation.py
    - tests/conftest.py
decisions:
  - "All 20 shock stubs use pytest.fail('Not yet implemented — see Plan XX') — no silent passes"
  - "mock_state_store lives in conftest.py (single source) — prevents per-file drift"
  - "test_end_to_end_shock_round2 excluded from Wave 0 — Plan 05 creates it in-place using AsyncMock(side_effect=...) to avoid maxsize=1 queue deadlock"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-11"
  tasks_completed: 2
  files_modified: 6
---

# Phase 26 Plan 01: Wave 0 Test Scaffolding Summary

**One-liner:** 20 failing pytest stubs across 5 test files establishing RED-state TDD scaffolding for the complete shock-injection feature (governor suspend/resume, StateStore shock bridge, ShockEvent persistence, TUI ShockInputScreen, simulation wiring).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Governor + state + graph stubs + conftest fixture | 57638f7 | tests/test_governor.py, tests/test_state.py, tests/test_graph.py, tests/conftest.py |
| 2 | TUI + simulation stubs | 4073e4d | tests/test_tui.py, tests/test_simulation.py |

## Files Modified

### tests/conftest.py
- Added `mock_state_store` fixture (Phase 26 section) providing the shock-window API surface: `is_shock_window_open`, `shock_next_round`, `request_shock`, `close_shock_window`, `submit_shock`, `await_shock`

### tests/test_governor.py
Added `TestSuspendResume` class with 5 failing stubs:
1. `test_suspend_blocks_acquire`
2. `test_resume_unblocks_acquire`
3. `test_suspend_does_not_touch_state_machine`
4. `test_monitor_loop_continues_during_suspend`
5. `test_suspend_does_not_bypass_memory_pressure_state` (reviews revision — concurrent memory-pressure guard)

### tests/test_state.py
Added 2 failing stubs:
1. `test_shock_queue_roundtrip`
2. `test_shock_window_event_reflects_state`

### tests/test_graph.py
Added 4 failing stubs:
1. `test_write_shock_event_creates_node_and_edge`
2. `test_write_shock_event_returns_uuid`
3. `test_write_shock_event_wraps_driver_errors`
4. `test_ensure_schema_includes_shock_cycle_index`

### tests/test_tui.py
Added 5 failing stubs:
1. `test_shock_input_screen_enter_dismisses_with_text`
2. `test_shock_input_screen_esc_dismisses_with_none`
3. `test_shock_input_screen_empty_enter_dismisses_with_none` (reviews revision — empty-Enter dismiss)
4. `test_poll_snapshot_pushes_shock_screen_on_window_open`
5. `test_shock_screen_pushed_once_per_window`

### tests/test_simulation.py
Added 4 failing stubs:
1. `test_shock_injected_into_round2_user_message`
2. `test_round2_unchanged_when_no_shock`
3. `test_shock_does_not_mutate_base_rumor`
4. `test_run_simulation_without_state_store_skips_shock`

## Stub Failure Confirmation

All 20 stubs raise `pytest.fail("Not yet implemented — see Plan XX")`. No silent passes exist.

```
uv run pytest tests/test_governor.py::TestSuspendResume → 5 failed (Not yet implemented)
uv run pytest tests/test_state.py::test_shock_queue_roundtrip → 1 failed (Not yet implemented)
uv run pytest tests/test_graph.py::test_write_shock_event_creates_node_and_edge → 1 failed (Not yet implemented)
uv run pytest tests/test_tui.py::test_shock_input_screen_enter_dismisses_with_text → 1 failed (Not yet implemented)
uv run pytest tests/test_simulation.py::test_shock_injected_into_round2_user_message → 1 failed (Not yet implemented)
```

## mock_state_store Fixture

Confirmed present in `tests/conftest.py` (single definition, no duplicates across test files).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

All 20 stubs are intentional RED-state scaffolding. Each references the implementing plan:
- Plans 02: governor stubs (5)
- Plan 03: state + graph stubs (6)
- Plan 04: TUI stubs (5)
- Plan 05: simulation stubs (4)

These are not defects — they are the explicit output of this plan.

## Next Step

Plans 02 and 03 (Wave 1) run in parallel to implement the production code that lights up these stubs:
- Plan 02: `ResourceGovernor.suspend()` / `resume()` → lights up `TestSuspendResume`
- Plan 03: `StateStore` shock bridge + `GraphStateManager.write_shock_event()` → lights up state + graph stubs

## Self-Check: PASSED

- tests/test_governor.py modified: FOUND
- tests/test_state.py modified: FOUND
- tests/test_graph.py modified: FOUND
- tests/test_tui.py modified: FOUND
- tests/test_simulation.py modified: FOUND
- tests/conftest.py modified: FOUND
- Commit 57638f7: FOUND
- Commit 4073e4d: FOUND
- 20 stubs collected by pytest: VERIFIED
