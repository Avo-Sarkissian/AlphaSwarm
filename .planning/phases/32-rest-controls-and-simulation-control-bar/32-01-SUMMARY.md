---
phase: 32-rest-controls-and-simulation-control-bar
plan: 01
subsystem: api
tags: [fastapi, asyncio, create-task, rest, simulation-lifecycle, shock-injection]

# Dependency graph
requires:
  - phase: 29-fastapi-skeleton-and-event-loop-foundation
    provides: FastAPI app skeleton, SimulationManager stub, lifespan pattern
  - phase: 30-websocket-state-stream
    provides: ConnectionManager, WebSocket broadcaster, StateStore snapshot
provides:
  - SimulationManager with fire-and-forget create_task pattern
  - POST /api/simulate/stop endpoint (cancel running simulation)
  - POST /api/simulate/shock endpoint (queue shock for next round)
  - Done-callback that resets StateStore.phase to IDLE on cancel/failure
  - NoSimulationRunningError and ShockAlreadyQueuedError exception classes
affects: [32-02, 32-03, 32-04]

# Tech tracking
tech-stack:
  added: [fastapi>=0.115.0, uvicorn>=0.34.0, httpx>=0.28.0]
  patterns: [manual-lock-acquire-with-done-callback, fire-and-forget-create-task, phase-reset-on-cancel]

key-files:
  created: []
  modified:
    - src/alphaswarm/web/simulation_manager.py
    - src/alphaswarm/web/routes/simulation.py
    - src/alphaswarm/web/app.py
    - tests/test_web.py
    - pyproject.toml

key-decisions:
  - "Manual lock.acquire() instead of async-with to hold lock across background task lifetime"
  - "Done-callback resets phase to IDLE on cancel/error via asyncio.create_task (sync callback cannot await)"
  - "Added fastapi/uvicorn/httpx to pyproject.toml main deps (were missing from prior phases)"

patterns-established:
  - "Lock-across-task: acquire lock in start(), release only in done-callback -- prevents concurrent starts"
  - "Phase-reset-on-cancel: _on_task_done schedules _reset_phase_to_idle via create_task for async cleanup from sync callback"
  - "409-guard-pattern: REST endpoints catch domain exceptions and return HTTP 409 with structured error JSON"

requirements-completed: [BE-05, BE-06, BE-07]

# Metrics
duration: 7min
completed: 2026-04-14
---

# Phase 32 Plan 01: Simulation Lifecycle Endpoints Summary

**SimulationManager refactored with fire-and-forget create_task pattern, stop/shock REST endpoints, and done-callback phase reset to IDLE on cancel/failure**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-14T14:35:30Z
- **Completed:** 2026-04-14T14:42:44Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- SimulationManager.start() fires create_task and returns immediately (HTTP 202 non-blocking)
- Done-callback releases lock unconditionally and resets StateStore.phase to IDLE on cancel/error
- POST /api/simulate/stop returns 200 when running, 409 when not
- POST /api/simulate/shock returns 200 when queued, 409 for not-running or already-queued
- 10 new tests (27 total) all passing -- covers task lifecycle, lock safety, endpoint status codes, and phase reset

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor SimulationManager with create_task + done-callback, stop, shock** - `343669f` (test: RED), `cfe01ef` (feat: GREEN)
2. **Task 2: Add stop and shock REST endpoints with tests** - `90eaf85` (test: RED), `99f34da` (feat: GREEN)
3. **Dependency lockfile update** - `2a6a9ea` (chore)

_Note: TDD tasks have RED/GREEN commit pairs_

## Files Created/Modified
- `src/alphaswarm/web/simulation_manager.py` - Full SimulationManager: create_task + done-callback, stop(), inject_shock(), consume_shock(), _reset_phase_to_idle()
- `src/alphaswarm/web/routes/simulation.py` - Added stop and shock endpoints with 409 guards
- `src/alphaswarm/web/app.py` - Updated SimulationManager constructor to pass brackets
- `tests/test_web.py` - 10 new tests (init_brackets, start_creates_task, lock_on_exception, stop_cancels, inject_shock, start_202, stop_200_409, shock_queued_409, shock_concurrent_409, cancellation_resets_phase)
- `pyproject.toml` - Added fastapi, uvicorn, httpx dependencies

## Decisions Made
- Used manual `await self._lock.acquire()` instead of `async with self._lock` so the lock is held for the entire duration of the background task (released only in done-callback). Without this, the lock would release immediately after `create_task()`, allowing concurrent starts.
- Done-callback schedules `_reset_phase_to_idle()` via `asyncio.create_task()` because the callback is synchronous and cannot `await` the async `set_phase()` method.
- Added fastapi/uvicorn/httpx to pyproject.toml main dependencies -- they were used by the web module but not declared (blocking issue from prior phases, auto-fixed per Rule 3).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added missing web dependencies to pyproject.toml**
- **Found during:** Task 1 (test execution)
- **Issue:** fastapi, uvicorn, and httpx were used by `src/alphaswarm/web/` but not declared in pyproject.toml dependencies. Tests failed with `ModuleNotFoundError: No module named 'fastapi'`.
- **Fix:** Added `fastapi>=0.115.0`, `uvicorn>=0.34.0`, `httpx>=0.28.0` to pyproject.toml dependencies.
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** `uv sync` succeeded, all 27 tests pass
- **Committed in:** cfe01ef (Task 1 commit), 2a6a9ea (lockfile)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for tests to run. No scope creep.

## Issues Encountered
- Worktree had inconsistent file state after `git reset --soft` (older source files from pre-Phase 29). Resolved by `git checkout fd5b921 -- src/ tests/ pyproject.toml` to restore all files from the target base commit, then re-applying changes.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Simulation lifecycle endpoints (start/stop/shock) are fully functional and tested
- Ready for Phase 32-02: Vue SimControlBar component can now wire to these endpoints
- SimulationManager.consume_shock() is available for the simulation pipeline to read queued shocks

## Self-Check: PASSED

- All 5 key files found on disk
- All 5 commit hashes verified in git log
- 27/27 tests pass

---
*Phase: 32-rest-controls-and-simulation-control-bar*
*Completed: 2026-04-14*
