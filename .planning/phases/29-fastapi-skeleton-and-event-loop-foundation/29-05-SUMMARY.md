---
phase: 29-fastapi-skeleton-and-event-loop-foundation
plan: 05
subsystem: api
tags: [fastapi, http, simulation, 409, endpoint, pytest]

requires:
  - phase: 29-fastapi-skeleton-and-event-loop-foundation
    provides: SimulationManager with asyncio.Lock guard and SimulationAlreadyRunningError

provides:
  - POST /api/simulate/start HTTP endpoint returning 202 on success and 409 when already running
  - simulation_router registered in app.py under /api prefix
  - HTTP-layer translation of SimulationAlreadyRunningError to 409 Conflict with structured detail body
  - Test 7 in test_web.py asserting HTTP 409 response via patched sim_manager

affects: [phase-30-vue-frontend, phase-32-simulation-wiring]

tech-stack:
  added: [fastapi>=0.115, uvicorn[standard]>=0.34, httpx>=0.28 (added to worktree pyproject.toml)]
  patterns:
    - "APIRouter per feature module, registered in create_app() under /api prefix"
    - "request.app.state.sim_manager pattern for dependency access without FastAPI DI overhead"
    - "SimulationAlreadyRunningError caught at route boundary, converted to HTTPException(409)"
    - "HTTP 202 Accepted for async operations; 409 Conflict for concurrency guard violations"

key-files:
  created:
    - src/alphaswarm/web/routes/simulation.py
  modified:
    - src/alphaswarm/web/app.py
    - tests/test_web.py
    - pyproject.toml (worktree: added fastapi/uvicorn/httpx deps)

key-decisions:
  - "HTTP 202 Accepted (not 200) for simulate/start — semantically correct for async operation acceptance"
  - "Structured 409 detail body {error: simulation_already_running, message: str(exc)} for frontend parseability"
  - "patch.object on sim_manager.start with AsyncMock side_effect to test 409 path without real concurrency"
  - "Added fastapi/uvicorn/httpx to worktree pyproject.toml (Rule 3 fix — were missing, blocking import)"

patterns-established:
  - "Simulation router: src/alphaswarm/web/routes/simulation.py follows same structure as health.py"
  - "Test helper _make_test_app() registers all routers so endpoint tests can hit full route tree"

requirements-completed: [BE-03]

duration: 12min
completed: 2026-04-12
---

# Phase 29 Plan 05: HTTP 409 Endpoint for Simulate Start Summary

**POST /api/simulate/start endpoint wrapping SimulationManager's asyncio.Lock guard, returning HTTP 409 Conflict with structured error body when a simulation is already running**

## Performance

- **Duration:** 12 min
- **Started:** 2026-04-12T00:00:00Z
- **Completed:** 2026-04-12T00:12:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `src/alphaswarm/web/routes/simulation.py` with POST /simulate/start returning 202 Accepted or 409 Conflict
- Registered `simulation_router` in `app.py` under `/api` prefix alongside existing `health_router`
- Added Test 7 (`test_simulate_start_409_when_running`) to `test_web.py` — all 7 tests pass, 35 total with no regression
- Closed SC-4 gap: HTTP 409 is now observable behavior, not just a Python exception inside SimulationManager

## Task Commits

Each task was committed atomically:

1. **Task 1: Create simulation.py with POST /api/simulate/start** - `2a9362c` (feat)
2. **Task 2: Register router in app.py and add HTTP 409 test** - `35c7fae` (feat)

## Files Created/Modified

- `src/alphaswarm/web/routes/simulation.py` - POST /simulate/start route with 202/409 response logic
- `src/alphaswarm/web/app.py` - Added simulation_router import and include_router call
- `tests/test_web.py` - Added simulation_router to _make_test_app(); added Test 7 for HTTP 409
- `pyproject.toml` - Added fastapi/uvicorn/httpx deps missing from worktree (deviation fix)

## Decisions Made

- Used HTTP 202 Accepted (not 200) for the success response — correct semantics for an async operation that is accepted and queued, not immediately completed
- Structured the 409 detail body as `{"error": "simulation_already_running", "message": str(exc)}` so the Vue 3 frontend (Phase 30) can parse the error type programmatically
- Used `patch.object` with `AsyncMock(side_effect=...)` for Test 7 — tests the HTTP translation layer without needing real concurrency, which is the correct isolation level for a route test

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added fastapi/uvicorn/httpx to worktree pyproject.toml**
- **Found during:** Task 1 verification (import check)
- **Issue:** `uv run python -c "from alphaswarm.web.routes.simulation import router"` failed with `ModuleNotFoundError: No module named 'fastapi'` — these deps existed in the main project pyproject.toml but were absent from the worktree's copy
- **Fix:** Added `fastapi>=0.115`, `uvicorn[standard]>=0.34`, `httpx>=0.28` to worktree `pyproject.toml` and ran `uv sync`
- **Files modified:** `pyproject.toml`, `uv.lock`
- **Verification:** Import succeeded after sync; all 7 tests pass
- **Committed in:** `2a9362c` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking import failure)
**Impact on plan:** Required for any import to succeed. No scope creep — deps were already present in the main repo; worktree had stale pyproject.toml.

## Issues Encountered

- Worktree was initially at wrong base commit (git merge-base returned 718edab instead of 5b7ed94). Performed `git reset --soft 5b7ed94` then `git checkout HEAD` to restore files that had been staged as deletions. Resolved cleanly before any code changes.

## Known Stubs

- `SimulationManager.start()` body is a stub (`pass`) — Phase 32 will wire actual simulation call. The HTTP endpoint returns 202 Accepted correctly; no data is flowing to simulation engine yet. This is intentional and documented in simulation_manager.py.

## Next Phase Readiness

- SC-4 requirement satisfied: POST /api/simulate/start returns HTTP 409 when simulation is running
- Vue 3 frontend (Phase 30) can call POST /api/simulate/start and handle 409 with the structured `detail.error` field
- Phase 32 can wire `SimulationManager.start()` body without changing the HTTP contract

---
*Phase: 29-fastapi-skeleton-and-event-loop-foundation*
*Completed: 2026-04-12*
