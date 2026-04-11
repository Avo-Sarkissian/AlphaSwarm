---
phase: 26-shock-injection-core
plan: "05"
subsystem: simulation
tags: [tdd, shock-injection, simulation, integration, wave-3]
dependency_graph:
  requires:
    - phase: 26-02
      provides: ResourceGovernor.suspend() / resume() with memory-pressure guard
    - phase: 26-03
      provides: StateStore shock bridge (request_shock, close_shock_window, await_shock, submit_shock)
    - phase: 26-03
      provides: GraphStateManager.write_shock_event()
    - phase: 26-04
      provides: ShockInputScreen + _check_shock_window edge latch
  provides:
    - _collect_inter_round_shock() helper in simulation.py
    - R1→R2 and R2→R3 shock window wiring in run_simulation()
    - effective_message_r2 / effective_message_r3 locals (rumor never mutated)
    - 5 simulation test stubs GREEN + 1 in-place E2E test
    - Phase 26 implementation-complete (all 20 Plan 01 stubs + E2E = 21 shock tests GREEN)
  affects: []
tech_stack:
  added: []
  patterns:
    - "Nested try/finally: inner finally for close_shock_window, outer finally for governor.resume() — both run even on cancellation"
    - "_collect_inter_round_shock helper called at both R1→R2 and R2→R3 — single definition prevents drift"
    - "effective_message_rN local variable pattern — rumor variable never reassigned"
    - "AsyncMock(side_effect=[...]) pattern for multi-call await_shock mocking — bypasses maxsize=1 queue deadlock"
    - "_invoke_run_simulation_with_mocks shared test helper — patches inject_seed + run_round1, caller patches dispatch_wave"
key_files:
  created: []
  modified:
    - src/alphaswarm/simulation.py
    - tests/test_simulation.py
decisions:
  - "_collect_inter_round_shock placed before run_simulation at module level — single helper called at both R1→R2 and R2→R3 per Codex MEDIUM review"
  - "Neo4jWriteError imported at runtime (not TYPE_CHECKING) — needed for except clause at runtime"
  - "governor.resume() in outer finally; close_shock_window() in inner finally — per Codex HIGH + Gemini MEDIUM reviews"
  - "Caller does NOT check governor._state before resume() — Plan 02 enforces memory-pressure invariant at callee"
  - "E2E test uses AsyncMock side_effect pattern, NOT real StateStore — avoids maxsize=1 queue deadlock per Codex HIGH review"
  - "_invoke_run_simulation_with_mocks auto-patches MagicMock state_store methods with AsyncMock for set_phase/set_round/etc."
metrics:
  duration: "~20 minutes"
  completed: "2026-04-11"
  tasks_completed: 2
  files_modified: 2
---

# Phase 26 Plan 05: Simulation Shock Wiring Summary

**One-liner:** `_collect_inter_round_shock` helper with nested try/finally wired at R1→R2 and R2→R3 gaps in `run_simulation`, completing Phase 26 implementation with 21 shock tests GREEN.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extract _collect_inter_round_shock helper and wire R1→R2 gap | 31aa388 | src/alphaswarm/simulation.py, tests/test_simulation.py |
| 2 | Wire R2→R3 gap via helper and implement remaining stubs + E2E test | 31aa388 | src/alphaswarm/simulation.py, tests/test_simulation.py |

(Tasks 1 and 2 were committed atomically in one commit since the R2→R3 gap and remaining tests were implemented together.)

## Files Modified

### src/alphaswarm/simulation.py (+109 lines)

**Import added:**
- `from alphaswarm.errors import Neo4jWriteError` — required at runtime for except clause

**New helper `_collect_inter_round_shock()` (~70 LoC, inserted before run_simulation):**
- Returns `None` immediately when `state_store is None` (non-TUI/CLI path unaffected)
- `governor.suspend()` called before the outer try block
- OUTER TRY: calls `request_shock(next_round=N)`, then INNER TRY/FINALLY around `await_shock()` / `close_shock_window()`
- If `shock_text` is truthy: `write_shock_event()` inside a try/except that catches `Neo4jWriteError` and logs `shock_event_write_failed` (continues to next round)
- OUTER FINALLY: `governor.resume()` — unconditional; Plan 02's callee-side guard handles memory pressure

**R1→R2 gap (between Round 1 callback and `ensure_clean_state`):**
- `shock_text_r2 = await _collect_inter_round_shock(next_round=2, ...)`
- `effective_message_r2 = f"{rumor}\n\n[BREAKING] {shock_text_r2}" if shock_text_r2 else rumor`

**R2→R3 gap (between Round 2 callback and Round 3 phase transition):**
- `shock_text_r3 = await _collect_inter_round_shock(next_round=3, ...)`
- `effective_message_r3 = f"{rumor}\n\n[BREAKING] {shock_text_r3}" if shock_text_r3 else rumor`

**Round 2 dispatch_wave:** `user_message=rumor` → `user_message=effective_message_r2`
**Round 3 dispatch_wave:** `user_message=rumor` → `user_message=effective_message_r3`

### tests/test_simulation.py (+252 lines, -7 stubs replaced)

**New module-level helpers:**
- `_make_governor_mock()` — AsyncMock governor with `suspend`/`resume` as plain `MagicMock` (synchronous methods)
- `_invoke_run_simulation_with_mocks(*, rumor, state_store, governor, graph_manager)` — patches `inject_seed` + `run_round1`; accepts `dispatch_wave` patch from caller; auto-supplements `MagicMock` state_store with `AsyncMock` for `set_phase`/`set_round`/`set_bracket_summaries`/`update_agent_state`/`push_rationale`

**5 stubs replaced (Plan 01 RED → GREEN):**
1. `test_shock_injected_into_round2_user_message` — `await_shock` side_effect `["Fed cut rates", None]`; asserts Round 2 message `== "Apple beats earnings\n\n[BREAKING] Fed cut rates"`
2. `test_round2_unchanged_when_no_shock` — `await_shock` returns `None`; asserts Round 2 message `== "Apple beats earnings"`
3. `test_shock_does_not_mutate_base_rumor` — two distinct shocks; asserts R2 + R3 each get correct shock, original_rumor unchanged
4. `test_run_simulation_without_state_store_skips_shock` — `state_store=None`; asserts `governor.suspend` never called, all rounds receive bare rumor
5. _(E2E test added in-place, not from Plan 01 stubs)_

**1 in-place E2E test (new, REVIEWS REVISION — not a Plan 01 stub):**
- `test_end_to_end_shock_round2` — verifies Round 2 dispatch receives `[BREAKING]` prefix, `graph_mock.write_shock_event` called once with `injected_before_round=2`, `close_shock_window.call_count == 2` (both gaps)

## Line Counts

| Change | Lines |
|--------|-------|
| `_collect_inter_round_shock` helper | +70 |
| R1→R2 gap call + effective_message | +14 |
| R2→R3 gap call + effective_message | +14 |
| Round 2/3 dispatch_wave keyword change | +2 (net 0, just keyword swap) |
| Neo4jWriteError import | +1 |
| **simulation.py total** | **+109** |
| Shared test helpers | +80 |
| 4 replaced stubs + 1 E2E test | +180 |
| **test_simulation.py total** | **+252 (-7)** |

## Phase 26 Complete: All 21 Shock Tests GREEN

| Stub Group | Count | Plan | Status |
|------------|-------|------|--------|
| TestSuspendResume (governor) | 5 | 02 | GREEN |
| StateStore shock bridge | 2 | 03 | GREEN |
| GraphStateManager.write_shock_event | 4 | 03 | GREEN |
| ShockInputScreen + _check_shock_window | 5 | 04 | GREEN |
| Simulation shock wiring (stubs) | 4 | 05 | GREEN |
| E2E integration test (in-place) | 1 | 05 | GREEN |
| **Total** | **21** | | **ALL GREEN** |

## Reviews-Compliance Checklist

- [x] `close_shock_window()` is in a `finally:` block nested inside the outer `try:` — NOT in a raw try path (Gemini MEDIUM / Codex HIGH)
- [x] `governor.resume()` is in an outer `finally:` block — runs even if `request_shock` / `write_shock_event` raise (Gemini / Codex HIGH)
- [x] E2E test uses `AsyncMock(side_effect=[...])` on `await_shock`, NOT real `StateStore` with pre-populated queue (Codex HIGH — maxsize=1 deadlock fix)
- [x] Plan 05 `depends_on` includes 26-04 in frontmatter — wave=3 serializes after Wave 2 Plans 03+04 (Codex HIGH)
- [x] No `governor._state ==` check in `simulation.py` — Plan 02 enforces memory-pressure guard at callee (Codex HIGH / TOCTOU fix)
- [x] Single `_collect_inter_round_shock` helper prevents R2/R3 drift — called at both gaps (Codex MEDIUM)

## ROADMAP.md Phase 26 Success Criteria — All Satisfied

1. **SHOCK-01: User can type a breaking event** — `test_shock_input_screen_enter_dismisses_with_text` + `test_shock_input_screen_empty_enter_dismisses_with_none` (Plan 04)
2. **SHOCK-02: All 100 agents receive shock in prompt** — `test_shock_injected_into_round2_user_message` + `test_end_to_end_shock_round2` (Plan 05)
3. **SHOCK-03: ShockEvent persisted to Neo4j** — `test_write_shock_event_creates_node_and_edge` + `test_end_to_end_shock_round2` (Plans 03 + 05)
4. **Governor does not enter false THROTTLED/PAUSED** — `test_suspend_does_not_touch_state_machine` + `test_monitor_loop_continues_during_suspend` + `test_suspend_does_not_bypass_memory_pressure_state` (Plan 02)

## Authoritative Sources

- 26-CONTEXT.md D-05..D-10: suspend/resume design, shock window protocol
- 26-RESEARCH.md Pattern 3 (lines 222-256): nested try/finally lifecycle
- 26-RESEARCH.md Pitfalls 1, 3, 5: memory pressure race, state_store=None deadlock, rumor mutation
- 26-REVIEWS.md Consensus Summary HIGH items: nested finally, E2E test deadlock, dependency ordering

## Deviations from Plan

**1. [Rule 2 - Missing Critical Functionality] Auto-patch MagicMock state_store in _invoke_run_simulation_with_mocks**
- **Found during:** Task 1 first test run
- **Issue:** `mock_state_store` fixture from conftest.py is a `MagicMock` base with specific async attributes set, but `set_phase`, `set_round`, `set_bracket_summaries`, `update_agent_state`, `push_rationale` return plain `MagicMock` (not awaitable). `run_simulation` awaits these methods, causing `TypeError: object MagicMock can't be used in 'await' expression`.
- **Fix:** Added a loop in `_invoke_run_simulation_with_mocks` that checks each needed async method and replaces non-AsyncMock attributes with `AsyncMock()` — preserves the caller's custom side_effect/return_value while making the state_store work with the full run_simulation body.
- **Files modified:** tests/test_simulation.py
- **Commit:** 31aa388

**2. [Out of Scope - Pre-existing] 6 mypy errors in simulation.py**
- 6 pre-existing mypy errors confirmed in baseline commit 487d705 (verified via `git stash` + mypy). Zero new errors introduced by Plan 05. Logged to deferred-items per scope boundary rule.

## Known Stubs

None — all 20 Plan 01 stubs are now implemented (plus 1 in-place E2E test). Phase 26 implementation is complete.

## Next Step

Phase 26 implementation is complete. Run `/gsd:verify-work 26` for checker validation of the full shock-injection feature.

## Self-Check: PASSED

- `src/alphaswarm/simulation.py` modified: FOUND
- `tests/test_simulation.py` modified: FOUND
- `grep -c "async def _collect_inter_round_shock" src/alphaswarm/simulation.py` = 1: VERIFIED
- `grep -c "if state_store is None" src/alphaswarm/simulation.py` = 1: VERIFIED
- `grep -c "governor.suspend()" src/alphaswarm/simulation.py` = 1: VERIFIED
- `grep -c "governor.resume()" src/alphaswarm/simulation.py` = 2 (docstring + actual call): VERIFIED
- `grep -c "close_shock_window" src/alphaswarm/simulation.py` = 3: VERIFIED
- `grep -c "effective_message_r2" src/alphaswarm/simulation.py` = 2: VERIFIED
- `grep -c "effective_message_r3" src/alphaswarm/simulation.py` = 2: VERIFIED
- `grep -c "user_message=effective_message" src/alphaswarm/simulation.py` = 2 (R2 + R3): VERIFIED
- `grep -c "governor._state" src/alphaswarm/simulation.py` = 0: VERIFIED
- `grep -c "_collect_inter_round_shock" src/alphaswarm/simulation.py` = 4 (def + 2 calls + 1 comment): VERIFIED
- `grep -c "def test_end_to_end_shock_round2" tests/test_simulation.py` = 1: VERIFIED
- `grep -c "async def _invoke_run_simulation_with_mocks" tests/test_simulation.py` = 1: VERIFIED
- 21 Phase 26 shock tests GREEN: VERIFIED (253 total, 0 failures)
- 0 new mypy errors introduced: VERIFIED
- Commit 31aa388: FOUND
