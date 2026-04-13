---
phase: 31-vue-spa-and-force-directed-graph
plan: 01
subsystem: api
tags: [fastapi, neo4j, rest, staticfiles, pydantic, starlette]

# Dependency graph
requires:
  - phase: 29-fastapi-skeleton-and-event-loop-foundation
    provides: FastAPI app factory, route pattern, AppState container
  - phase: 30-websocket-state-stream
    provides: WebSocket route registration pattern in create_app
provides:
  - "GET /api/edges/{cycle_id}?round=N REST endpoint returning INFLUENCED_BY edges"
  - "GraphStateManager.read_influence_edges() Neo4j query method"
  - "StaticFiles mount for frontend/dist/ (Vue SPA production serving)"
  - "EdgeItem and EdgesResponse Pydantic models"
affects: [31-02, 31-03, 31-04]

# Tech tracking
tech-stack:
  added: [starlette.staticfiles]
  patterns: [os.path.isdir guard for optional static mount, parameterized Cypher edge reads]

key-files:
  created:
    - src/alphaswarm/web/routes/edges.py
  modified:
    - src/alphaswarm/graph.py
    - src/alphaswarm/web/app.py
    - tests/test_web.py

key-decisions:
  - "StaticFiles mount guarded by os.path.isdir so dev mode (no dist/) still works"
  - "Round param validated 1-3 via FastAPI Query(ge=1, le=3) matching 3-round cascade"
  - "503 Service Unavailable when graph_manager is None (Neo4j offline)"

patterns-established:
  - "Edge query pattern: parameterized Cypher returning source_id/target_id/weight dicts"
  - "StaticFiles mount LAST in create_app to avoid catching API routes"

requirements-completed: [VIS-03]

# Metrics
duration: 2min
completed: 2026-04-13
---

# Phase 31 Plan 01: Edges REST Endpoint and Static File Serving Summary

**GET /api/edges/{cycle_id}?round=N endpoint for INFLUENCED_BY edge data, plus StaticFiles mount for Vue SPA production build**

## Performance

- **Duration:** 2 min 29s
- **Started:** 2026-04-13T21:53:44Z
- **Completed:** 2026-04-13T21:56:13Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `read_influence_edges` method to GraphStateManager with parameterized Cypher query for INFLUENCED_BY edges
- Created edges REST route with EdgeItem/EdgesResponse Pydantic models, 503 when Neo4j offline, round validation 1-3
- Wired edges_router and StaticFiles mount into production app factory
- Added 4 new tests covering 503 without Neo4j, missing round param, round boundary validation, and production route registration

## Task Commits

Each task was committed atomically:

1. **Task 1: Add read_influence_edges to GraphStateManager and create edges route** - `5f4e22f` (feat)
2. **Task 2: Wire edges router and StaticFiles into app.py + add tests** - `12fcc42` (feat)

## Files Created/Modified
- `src/alphaswarm/web/routes/edges.py` - New edges REST endpoint with EdgeItem/EdgesResponse models
- `src/alphaswarm/graph.py` - Added read_influence_edges() and _read_influence_edges_tx() methods
- `src/alphaswarm/web/app.py` - Registered edges_router, added StaticFiles mount with os.path.isdir guard
- `tests/test_web.py` - 4 new edge endpoint tests, edges_router added to _make_test_app

## Decisions Made
- StaticFiles mount guarded by `os.path.isdir` so development mode (no dist/ directory) continues working without errors
- Round parameter validated 1-3 via FastAPI `Query(ge=1, le=3)` matching the 3-round consensus cascade
- Returns 503 Service Unavailable when graph_manager is None (Neo4j offline) following the same error pattern as other endpoints
- StaticFiles mount placed LAST in create_app() because `html=True` catches all non-API paths for Vue Router history mode

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Known Stubs
None - all endpoints are fully wired to GraphStateManager methods.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Edges endpoint ready for Vue frontend force-directed graph to consume
- StaticFiles mount ready to serve production Vue build once frontend/dist/ exists
- All 17 tests passing (13 existing + 4 new)

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 31-vue-spa-and-force-directed-graph*
*Completed: 2026-04-13*
