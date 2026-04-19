---
phase: 32-rest-controls-and-simulation-control-bar
plan: 02
subsystem: api
tags: [fastapi, replay, neo4j, rest, pydantic, contract-stubs]

# Dependency graph
requires:
  - phase: 29-fastapi-skeleton-and-event-loop-foundation
    provides: FastAPI app skeleton, lifespan pattern, router registration
  - phase: 31-vue-spa-and-force-directed-graph
    provides: GET /api/edges/{cycle_id} endpoint (SC-3)
  - phase: 32-01
    provides: SimulationManager, app.py router pattern, test helpers
provides:
  - GET /api/replay/cycles endpoint (real Neo4j query via read_completed_cycles)
  - POST /api/replay/start/{cycle_id} contract stub for Phase 34
  - POST /api/replay/advance contract stub for Phase 34
  - Pydantic response models: CycleItem, ReplayCyclesResponse, ReplayStartResponse, ReplayAdvanceResponse
affects: [34-replay-mode-web-ui]

# Tech tracking
tech-stack:
  added: []
  patterns: [neo4j-503-guard-pattern, contract-stub-for-future-phase]

key-files:
  created:
    - src/alphaswarm/web/routes/replay.py
  modified:
    - src/alphaswarm/web/app.py
    - tests/test_web.py

key-decisions:
  - "round_count hard-coded to 3 because read_completed_cycles() only returns cycles with Round 3 decisions"
  - "Replay start/advance are contract stubs -- Phase 34 fills in the real state machine logic"
  - "Reused 503 Neo4j guard pattern from edges.py for consistency"

patterns-established:
  - "Contract stubs: return correct Pydantic schema with placeholder values, documented for future phase to fill in"
  - "Round 3 filter documented in docstring to address review concern #5"

requirements-completed: [BE-08, BE-09, BE-10]

# Metrics
duration: 3min
completed: 2026-04-14
---

# Phase 32 Plan 02: Replay Endpoints Summary

**Replay REST router with real Neo4j cycles-listing query (Round 3 filter) and contract stubs for start/advance, plus SC-3 edges regression test**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-14T14:48:27Z
- **Completed:** 2026-04-14T14:51:15Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- GET /api/replay/cycles returns completed cycles from Neo4j (only those with Round 3 decisions) or 503 if Neo4j offline
- POST /api/replay/start/{cycle_id} and POST /api/replay/advance return correct contract schemas for Phase 34
- SC-3 edges endpoint regression test confirms Phase 31 endpoint still works after Phase 32 router additions
- 32 total tests pass (5 new: cycles 503, start stub, advance stub, production route registration, edges regression)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create routes/replay.py with cycles endpoint and stubs** - `2719647` (test: RED), `6790238` (feat: GREEN)
2. **Task 2: Register replay_router and add tests including edges regression** - `6fb6afa` (feat)

_Note: Task 1 is TDD with RED/GREEN commit pair_

## Files Created/Modified
- `src/alphaswarm/web/routes/replay.py` - New replay router: GET /replay/cycles (real query), POST /replay/start/{cycle_id} (stub), POST /replay/advance (stub)
- `src/alphaswarm/web/app.py` - Added replay_router import and registration in create_app()
- `tests/test_web.py` - 5 new tests: replay 503, start stub, advance stub, production routes, edges regression
- `tests/test_replay_red.py` - TDD RED scaffold (3 tests for import, models, 503 guard)

## Decisions Made
- Hard-coded `round_count=3` in CycleItem because `read_completed_cycles()` already filters to cycles with at least one Round 3 decision -- all returned cycles have exactly 3 rounds by definition.
- Replay start and advance endpoints are intentional contract stubs returning correct Pydantic response schemas. Phase 34 fills in the real replay state machine logic without changing the API contract.
- Reused the exact same 503 Neo4j guard pattern from `edges.py` for consistency across all graph-dependent endpoints.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Known Stubs

| File | Line | Stub | Reason |
|------|------|------|--------|
| src/alphaswarm/web/routes/replay.py | 88-95 | replay_start returns fixed {status: "ok", round_num: 1} | Intentional contract stub -- Phase 34 fills in real replay state machine |
| src/alphaswarm/web/routes/replay.py | 98-105 | replay_advance returns fixed {status: "ok", round_num: 1} | Intentional contract stub -- Phase 34 fills in real state progression |

These stubs are by design (documented in plan as D-13, D-14) and do not block this plan's goal of establishing the correct response schemas.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three replay endpoints are registered and tested
- Phase 34 (Replay Mode Web UI) can wire to these endpoints immediately
- Response schemas are finalized -- Phase 34 only adds logic, not schema changes
- SC-3 edges endpoint confirmed working after all Phase 32 router additions

## Self-Check: PASSED

- All 4 key files found on disk
- All 3 commit hashes verified in git log
- 32/32 tests pass

---
*Phase: 32-rest-controls-and-simulation-control-bar*
*Completed: 2026-04-14*
