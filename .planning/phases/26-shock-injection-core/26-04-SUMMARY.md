---
phase: 26-shock-injection-core
plan: "04"
subsystem: tui
tags: [tdd, textual, shock-injection, modal, edge-latch, wave-2]
dependency_graph:
  requires:
    - phase: 26-01
      provides: 5 failing TUI stubs in tests/test_tui.py
    - phase: 26-03
      provides: StateStore.is_shock_window_open(), shock_next_round(), submit_shock()
  provides:
    - ShockInputScreen(Screen[str | None]) class in tui.py
    - AlphaSwarmApp._check_shock_window() rising/falling edge latch
    - AlphaSwarmApp._on_shock_submitted() run_worker callback
    - AlphaSwarmApp._shock_window_was_open: bool attribute
    - 5 test_tui.py stubs GREEN
  affects: [26-05]
tech_stack:
  added: []
  patterns:
    - "Textual Screen[str | None] modal with dismiss(value) pattern — mirrors RumorInputScreen"
    - "Rising-edge latch on _shock_window_was_open — prevents duplicate push_screen per window"
    - "Extracted _check_shock_window() helper from _poll_snapshot — enables isolation testing without full widget mount"
    - "run_worker(coroutine) sync->async bridge in dismiss callback — prevents Pitfall 4 (coroutine never runs)"
key_files:
  created: []
  modified:
    - src/alphaswarm/tui.py
    - tests/test_tui.py
decisions:
  - "_check_shock_window extracted from _poll_snapshot per Codex MEDIUM review — testable in isolation without mounting full dashboard widget tree"
  - "Tests use AlphaSwarmApp() with injected mock state_store + patch.object(push_screen) — avoids Textual run_test() overhead for synchronous latch logic"
  - "empty/whitespace Enter dismisses with None via text.strip() or None — D-07 guard with belt-and-suspenders whitespace test"
metrics:
  duration: "~3 minutes"
  completed: "2026-04-11"
  tasks_completed: 2
  files_modified: 2
---

# Phase 26 Plan 04: TUI ShockInputScreen + _poll_snapshot Shock Detection Summary

**One-liner:** ShockInputScreen modal (80 LoC) + _check_shock_window rising/falling edge latch added to AlphaSwarmApp, turning 5 RED TUI stubs GREEN with zero regressions.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add ShockInputScreen class and its three behavior tests | 0fce426 | src/alphaswarm/tui.py, tests/test_tui.py |
| 2 | Wire _poll_snapshot shock-window detection with edge latch | 0f59f7d | src/alphaswarm/tui.py, tests/test_tui.py |

## Files Modified

### src/alphaswarm/tui.py (+129 lines total across both tasks)

**New class: `ShockInputScreen(Screen[str | None])`** (~80 LoC, inserted after `RumorInputScreen`)
- `BINDINGS = [("escape", "skip_shock", "Skip")]`
- `DEFAULT_CSS`: `width: 72`, `border: solid #4FC3F7`, `background: #1E1E1E`, title `#4FC3F7 bold`, subtitle/hint `#78909C` — exact copy of 26-UI-SPEC.md
- `__init__(self, next_round: int)` — stores `_next_round` for subtitle
- `compose()` — yields `#shock-input-container` > `#shock-title` + `#shock-subtitle` + `#shock-input` + `#shock-hint`
- `on_mount()` — auto-focuses `#shock-input`
- `on_input_submitted()` — `text.strip() if text.strip() else None` (D-07 guard)
- `action_skip_shock()` — `self.dismiss(None)`

**New attribute on `AlphaSwarmApp.__init__`:**
- `self._shock_window_was_open: bool = False`

**New methods on `AlphaSwarmApp`:**
- `_check_shock_window()` — reads `store.is_shock_window_open()`, pushes `ShockInputScreen` on rising edge, resets latch on falling edge
- `_on_shock_submitted(shock_text: str | None)` — `self.run_worker(store.submit_shock(shock_text), exclusive=False, exit_on_error=True)`

**Modified `_poll_snapshot()`:** added `self._check_shock_window()` call at end (one line, purely additive)

### tests/test_tui.py (+179 lines, -3 stubs replaced)

Replaced 5 `pytest.fail` stubs with real implementations:

1. `test_shock_input_screen_enter_dismisses_with_text` — `run_test()` + Pilot presses chars then Enter, asserts `app.result == "Fed emergency rate cut"`
2. `test_shock_input_screen_esc_dismisses_with_none` — `run_test()` + Pilot presses Escape, asserts `app.result is None`
3. `test_shock_input_screen_empty_enter_dismisses_with_none` — two sub-cases: bare Enter (empty) and whitespace-only Enter, both assert `result is None`
4. `test_poll_snapshot_pushes_shock_screen_on_window_open` — instantiates `AlphaSwarmApp`, injects mock_state_store, patches `push_screen`, calls `_check_shock_window()` directly, asserts 1 push + latch set
5. `test_shock_screen_pushed_once_per_window` — 3 consecutive calls assert only 1 push, then falling edge resets latch, then rising edge #2 asserts 2nd push

## Test Results

| Suite | Before | After |
|-------|--------|-------|
| tests/test_tui.py (Phase 26 stubs) | 5 failing (pytest.fail) | 5 passed |
| tests/test_tui.py (full suite) | 29 passed + 5 failing | 34 passed (0 failed) |

## Color Palette Verification

`grep -oE '#[0-9A-Fa-f]{6}' src/alphaswarm/tui.py | sort -u` produces only pre-approved tokens:
`#121212`, `#1E1E1E`, `#252525`, `#333333`, `#4FC3F7`, `#555555`, `#66BB6A`, `#78909C`, `#E0E0E0`, `#EF5350`, `#FFA726`

No new hex codes introduced by ShockInputScreen CSS.

## Deviations from Plan

None — plan executed exactly as written.

The plan's acceptance criterion for `grep -c "action_skip_shock"` expected "at least 2 (binding + method)" but BINDINGS uses `"skip_shock"` (Textual convention) not `"action_skip_shock"`, so the grep returns 1 for the `def` line. This is the plan's own recommended code snippet — the functionality is correct and Textual maps `"skip_shock"` to `action_skip_shock` automatically. Noted as a plan wording inconsistency, not a defect.

## Known Stubs

None — all 5 Phase 26 TUI stubs from Plan 01 are now implemented.

## Next Step

Plan 05 (simulation wiring) is the final deliverable — it calls `governor.suspend()`/`resume()` (Plan 02), `state_store.request_shock()`/`close_shock_window()`/`await_shock()` (Plan 03), and receives the shock text from the TUI via `StateStore.submit_shock` (this plan). The TUI is now ready to receive the signal from simulation.

## Self-Check: PASSED

- `src/alphaswarm/tui.py` modified: FOUND
- `tests/test_tui.py` modified: FOUND
- `grep -c "class ShockInputScreen" src/alphaswarm/tui.py` = 1: VERIFIED
- `grep -c "_shock_window_was_open" src/alphaswarm/tui.py` = 5 (≥3): VERIFIED
- `grep -c "_check_shock_window" src/alphaswarm/tui.py` = 3 (≥2): VERIFIED
- `grep -c "_on_shock_submitted" src/alphaswarm/tui.py` = 3 (≥2): VERIFIED
- `grep -c "is_shock_window_open" src/alphaswarm/tui.py` = 2 (≥1): VERIFIED
- `grep -c "submit_shock" src/alphaswarm/tui.py` = 3 (≥1): VERIFIED
- Rising-edge check appears exactly once: VERIFIED
- Falling-edge reset appears exactly once: VERIFIED
- 5 Phase 26 TUI stubs GREEN: VERIFIED
- 34 total test_tui.py tests passed: VERIFIED
- 0 new mypy errors (4 pre-existing confirmed in baseline): VERIFIED
- Commit 0fce426: FOUND
- Commit 0f59f7d: FOUND
