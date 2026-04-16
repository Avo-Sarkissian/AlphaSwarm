---
phase: quick-260416-m8x
plan: 01
subsystem: web/simulation-lifecycle
tags: [bugfix, tier-1, concurrency, websocket, replay, simulation-manager]
dependency-graph:
  requires: []
  provides:
    - "B4 bi-directional guard (sim/replay mutual exclusion)"
    - "B7 writer-side cleanup on unclean disconnect"
    - "B8 synchronous phase reset on cancel/failure"
    - "B9 advance/stop serialization behind _lock"
    - "B10 single source of truth for COMPLETE phase"
  affects:
    - src/alphaswarm/web/simulation_manager.py
    - src/alphaswarm/web/routes/replay.py
    - src/alphaswarm/web/replay_manager.py
    - src/alphaswarm/web/connection_manager.py
    - src/alphaswarm/web/app.py
    - tests/test_web.py
tech-stack:
  added: []
  patterns:
    - "Injected ReplayManager via SimulationManager constructor (avoids circular import; keeps AppState stable)"
    - "Phase-reset-inside-_run pattern (sync await before done-callback fires → no lock-release/reset race)"
    - "finally-block cleanup in _writer (B7) — idempotent double-pop with disconnect()"
    - "async with self._lock wrapping replay advance()/stop() bodies"
key-files:
  created: []
  modified:
    - src/alphaswarm/web/simulation_manager.py
    - src/alphaswarm/web/routes/replay.py
    - src/alphaswarm/web/replay_manager.py
    - src/alphaswarm/web/connection_manager.py
    - src/alphaswarm/web/app.py
    - tests/test_web.py
decisions:
  - "ReplayManager injected via SimulationManager constructor kwarg (default None) rather than attached to AppState — keeps AppState dataclass stable, avoids circular import, preserves MagicMock-based unit test compatibility."
  - "Pre-existing test_sim_manager_cancellation_resets_phase_to_idle patched sm._run (which defeats the B8 fix). Updated to patch alphaswarm.simulation.run_simulation at the module level + yield between start() and stop() so the real _run with its new try/except actually runs."
  - "pytest-timeout is not installed in this project; plan's --timeout=N flags were silently dropped (pytest errored on unrecognized arg). Documented here for future reference."
metrics:
  duration: "609 seconds (~10 minutes)"
  completed: "2026-04-16T20:16:21Z"
---

# Phase quick-260416-m8x Plan 01: Tier 1 Surgical Bug Fixes (B4/B7/B8/B9/B10) Summary

Five Tier 1 bugs (B4, B7, B8, B9, B10) from `.planning/BUGFIX-CONTEXT.md` fixed across five web-package files plus the regression test file. Each fix preserves the async-first, non-blocking contract (no new locks on hot paths, no blocking I/O on the main event loop, `structlog` for any new log events). All six new regression tests pass; all 39 pre-existing tests in `tests/test_web.py` continue to pass.

## Scope

**Fixed bugs:**

| Bug | Description |
|-----|-------------|
| B4 (route-side) | `POST /api/replay/start/{cycle_id}` now returns 409 `{"error": "simulation_in_progress"}` when `sim_manager.is_running`. |
| B4 (sim-side) | `SimulationManager.start()` raises new `ReplayActiveError` when the injected `replay_manager.is_active`. |
| B7 | `ConnectionManager._writer` pops `ws` from `_clients` and `_tasks` in a `finally` block — cleanup now runs on every exit path (CancelledError, exception, normal return). |
| B8 | Phase-reset-to-IDLE on cancel/exception moved INSIDE `_run`'s try/except (awaited BEFORE the done-callback fires). The lock is therefore never released while phase is still non-IDLE, closing the race with concurrent `start()`. |
| B9 | `ReplayManager.advance()` and `ReplayManager.stop()` bodies now wrapped in `async with self._lock:` — matches `start()`. |
| B10 | Duplicate `await self._app_state.state_store.set_phase(SimulationPhase.COMPLETE)` at `simulation_manager.py:107` removed. `simulation.py:1109` is now the single source of truth for COMPLETE. |

## Files Changed

| File | Insertions | Deletions | Purpose |
|------|-----------|-----------|---------|
| `src/alphaswarm/web/simulation_manager.py` | +72 | -26 | B4(sim), B8, B10 — ReplayActiveError class, replay_manager kwarg on __init__, try/except-based phase reset in _run, simplified done-callback, deleted _reset_phase_to_idle helper |
| `src/alphaswarm/web/routes/replay.py` | +13 | -0 | B4(route) — 409 guard on `/api/replay/start/{cycle_id}` when sim_manager.is_running |
| `src/alphaswarm/web/replay_manager.py` | +65 | -39 | B9 — `async with self._lock:` around advance() and stop() bodies (plus docstrings) |
| `src/alphaswarm/web/connection_manager.py` | +16 | -5 | B7 — finally-block cleanup of _clients / _tasks on all exit paths |
| `src/alphaswarm/web/app.py` | +5 | -2 | Wire replay_manager into SimulationManager constructor in lifespan |
| `tests/test_web.py` | +236 | -6 | Fixture update + 1 existing-test patch-target fix + 6 new m8x regression tests |
| **Total** | **+387** | **-90** | across 6 files |

## New Tests (6 added)

All new tests live at the bottom of `tests/test_web.py` under the clearly-marked
`# Quick-260416-m8x Tier 1 regression tests` section:

1. `test_m8x_replay_start_409_when_simulation_running` — B4 route-side.
2. `test_m8x_sim_manager_start_raises_when_replay_active` — B4 sim-side.
3. `test_m8x_connection_manager_writer_cleans_up_on_exception` — B7.
4. `test_m8x_sim_manager_cancellation_phase_reset_before_lock_release` — B8 (uses capturing done-callback to assert ordering).
5. `test_m8x_replay_manager_advance_and_stop_hold_lock` — B9 (wraps `_lock.acquire` to count acquisitions across start/advance/stop; asserts 3).
6. `test_m8x_sim_manager_complete_phase_set_once` — B10 (simulates `simulation.py:1109` calling COMPLETE once, asserts no second call from the manager).

## Test Suite Confirmation

- `uv run pytest tests/test_web.py`: **45 passed** (0 failed).
- Scoped run `tests/test_simulation.py tests/test_replay_red.py tests/test_state.py`: **101 passed, 1 pre-existing failure** (`test_replay_red.py::test_replay_module_exists` expects 3 routes but finds 4 — pre-existing, unrelated to m8x scope; confirmed by running on pre-m8x baseline).
- Full suite excluding Ollama-integration tests: **608 passed, 20 pre-existing failures in `test_report.py`** (all `AttributeError: 'ReportAssembler' object has no attribute 'assemble_html'` — Phase 36 Report Viewer territory, confirmed pre-existing) **and 15 errors in `test_graph_integration.py`** (require live Neo4j).
- mypy: no NEW errors introduced by m8x changes. Pre-existing errors in `ollama_models.py`, `logging.py`, and the pre-existing `run_simulation` argument-type mismatches in `simulation_manager.py` remain unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated existing `test_sim_manager_cancellation_resets_phase_to_idle` to properly exercise the B8 fix**

- **Found during:** Task 1 verify.
- **Issue:** The existing test (written pre-m8x) used `patch.object(sm, "_run", side_effect=_long_run)` — patching out the whole `_run` method. Under the B8 fix, phase-reset-to-IDLE on cancel is INSIDE `_run`'s except block, so patching `_run` defeats the fix and the test failed with "set_phase: not called".
- **Secondary issue:** the test called `sm.stop()` immediately after `sm.start()` without yielding to the event loop, so the task was cancelled before its body ever ran (Python asyncio semantics: a task cancelled before its first scheduling never enters its body). Even patching `run_simulation` instead of `_run` wouldn't help without a `sleep(0)`.
- **Fix:** (a) Patched `alphaswarm.simulation.run_simulation` at module level so the real `_run` with its try/except runs; (b) added `await asyncio.sleep(0)` between `start()` and `stop()` so the task body reaches `await run_simulation(...)` before cancellation.
- **Files modified:** `tests/test_web.py` (one existing test, ~10 lines updated with a docstring explaining the architectural change).
- **Commit:** 73b7b9d (bundled with Task 3 tests).

**2. [Rule 3 - Blocking issue] `pytest-timeout` plugin not installed**

- **Found during:** Task 1 verify first run.
- **Issue:** Plan prescribes `uv run pytest ... --timeout=30`, but pytest errors with "unrecognized arguments: --timeout=30" because `pytest-timeout` is not listed in `pyproject.toml` dev-deps.
- **Fix:** Dropped the `--timeout` flag. All test runs completed in under 2 seconds each — the timeout would never have fired anyway.
- **Files modified:** none (execution-only; no code change).

**3. [Rule 2 - Critical functionality] Updated `_make_test_app()` fixture to wire replay_manager into SimulationManager**

- **Found during:** Task 3, as prescribed in the plan (Task 3 action step 3).
- **Fix:** 1-line change: `sim_manager = SimulationManager(app_state, brackets, replay_manager=replay_manager)` (also reordered so replay_manager is constructed first). Mirrors production `web/app.py` lifespan pattern.
- **Files modified:** `tests/test_web.py` fixture.
- **Commit:** 73b7b9d.

### Auth Gates

None.

### Known Stubs

None. All changes are to production-path behavior, not UI renderings.

### Deferred Issues

Pre-existing failures confirmed on base commit `824c980` (NOT introduced by m8x and out of scope per Rule 4 SCOPE BOUNDARY):

- `tests/test_report.py` — 19 failures, all `AttributeError: 'ReportAssembler' object has no attribute 'assemble_html'`. This is Phase 36 Report Viewer territory — unfinished work. Not in m8x scope.
- `tests/test_graph_integration.py` — 15 errors. Require live Neo4j driver; skipped in CI-like environments.
- `tests/test_replay_red.py::test_replay_module_exists` — 1 failure, expects 3 routes but finds 4 (cycles + start + advance + stop). Test was written when the router had 3 routes; a 4th was added later. Not in m8x scope.

## Commits (3 atomic)

| # | Hash | Message |
|---|------|---------|
| 1 | 009c853 | fix(web): simulation-lifecycle bugs B4(sim), B8, B10 |
| 2 | dd751c7 | fix(web): replay/writer concurrency bugs B4(route), B7, B9 |
| 3 | 73b7b9d | test(web): regression tests for B4, B7, B8, B9, B10 |

## Orphan-Reference Grep (per plan verification)

- `grep -n "_reset_phase_to_idle" src/` — only log event names remain (`failed_to_reset_phase_to_idle_on_cancel` / `_on_error`). No method references. **Clean.**
- `grep -n "set_phase(SimulationPhase.COMPLETE)" src/alphaswarm/web/simulation_manager.py` — zero matches. **Clean.**
- `grep -n "set_phase(SimulationPhase.COMPLETE)" src/` — 2 matches: `simulation.py:1109` (single source of truth) and `tui.py:943` (old TUI, out of scope per v5 direction memo).

## Self-Check: PASSED

All created/modified files exist at the paths documented above. All three commits (009c853, dd751c7, 73b7b9d) are present in `git log --oneline HEAD~3..HEAD`. All 45 tests in `tests/test_web.py` pass. No regression introduced outside pre-existing known-broken tests.
