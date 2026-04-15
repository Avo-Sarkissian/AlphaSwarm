---
phase: 34-replay-mode-web-ui
plan: 01
subsystem: api
tags: [fastapi, asyncio, websocket, replay, state-machine]

# Dependency graph
requires:
  - phase: 32-rest-controls-and-simulation-control-bar
    provides: "Replay route stubs (replay_start, replay_advance), SimulationManager pattern, ConnectionManager broadcast"
  - phase: 28-simulation-replay
    provides: "ReplayStore class, read_full_cycle_signals, read_bracket_narratives_for_round, read_rationale_entries_for_round"
provides:
  - "ReplayManager class with start/advance/stop lifecycle and asyncio.Lock concurrency guard"
  - "Real replay_start endpoint loading Neo4j signals into ReplayStore"
  - "Real replay_advance endpoint stepping through rounds 1-3 with bracket/rationale data"
  - "New replay_stop endpoint resetting phase to IDLE"
  - "Replay-aware broadcaster (snapshot_to_json checks replay_manager.is_active)"
  - "8 new replay tests covering all backend paths"
affects: [34-02, 34-03, frontend-replay-mode]

# Tech tracking
tech-stack:
  added: []
  patterns: ["ReplayManager singleton mounted on app.state via lifespan (mirrors SimulationManager)"]

key-files:
  created:
    - src/alphaswarm/web/replay_manager.py
  modified:
    - src/alphaswarm/web/broadcaster.py
    - src/alphaswarm/web/app.py
    - src/alphaswarm/web/routes/replay.py
    - tests/test_web.py

key-decisions:
  - "ReplayManager checks replay_manager.is_active pre-lock in route handler for fast 409 rejection, with try/except ReplayAlreadyActiveError as race-condition safety net inside the lock"
  - "Broadcaster receives replay_manager as optional parameter rather than reading from global state -- explicit dependency injection"

patterns-established:
  - "ReplayManager lifecycle: same singleton-on-app.state pattern as SimulationManager, with asyncio.Lock for concurrency"
  - "Replay-aware broadcaster: snapshot_to_json checks replay_manager.is_active before falling through to live StateStore path"

requirements-completed: [WEB-06, REPLAY-01]

# Metrics
duration: 4min
completed: 2026-04-15
---

# Phase 34 Plan 01: Replay Backend State Machine Summary

**ReplayManager class with asyncio.Lock lifecycle, three replay REST endpoints (start/advance/stop) loading Neo4j signals into ReplayStore, replay-aware broadcaster, and 8 new tests covering all backend paths**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-15T03:44:11Z
- **Completed:** 2026-04-15T03:48:11Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- ReplayManager class with start/advance/stop lifecycle, asyncio.Lock concurrency guard, and property-based state exposure
- Three replay REST endpoints with real logic: start loads signals from Neo4j and broadcasts round-1 snapshot, advance increments round with bracket/rationale data loading, stop resets to IDLE
- Broadcaster updated to prefer ReplayStore snapshot when replay is active (D-11)
- 8 new tests (39 total in test_web.py) covering start with mocked graph_manager, 409 duplicate start, 404 missing cycle, 503 without Neo4j, advance with round increment, stop resetting phase, stop 409 without active replay, and broadcaster replay-aware snapshot

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ReplayManager class and wire into backend infrastructure** - `1a7b4e3` (feat)
2. **Task 2: Fill in replay route stubs and add replay_stop endpoint** - `ef330da` (feat)
3. **Task 3: Write Wave 0 tests for replay backend** - `4ffbf60` (test)

## Files Created/Modified
- `src/alphaswarm/web/replay_manager.py` - ReplayManager class with start/advance/stop lifecycle, ReplayAlreadyActiveError, NoReplayActiveError
- `src/alphaswarm/web/broadcaster.py` - Replay-aware snapshot_to_json and start_broadcaster/broadcast_loop accepting optional replay_manager
- `src/alphaswarm/web/app.py` - Lifespan creates ReplayManager, mounts on app.state, passes to start_broadcaster
- `src/alphaswarm/web/routes/replay.py` - Real implementations for replay_start, replay_advance, new replay_stop endpoint, ReplayStopResponse model
- `tests/test_web.py` - Updated _make_test_app to mount replay_manager, updated stub tests to match real behavior, 8 new replay tests

## Decisions Made
- ReplayManager checks is_active pre-lock in route handler for fast 409 rejection, with try/except ReplayAlreadyActiveError as race-condition safety net inside the lock
- Broadcaster receives replay_manager as optional parameter rather than reading from global state -- explicit dependency injection keeps the function testable and avoids import-time coupling
- Test fixtures use AgentState(signal, confidence) without sentiment field (plan's test code had a phantom sentiment parameter that doesn't exist on the frozen dataclass)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed AgentState constructor in test fixtures**
- **Found during:** Task 3 (Write Wave 0 tests)
- **Issue:** Plan's test code used `AgentState(signal=SignalType.BUY, confidence=0.8, sentiment=0.5)` but AgentState is a frozen dataclass with only `signal` and `confidence` fields (no `sentiment`)
- **Fix:** Removed `sentiment` parameter from all test AgentState constructors
- **Files modified:** tests/test_web.py
- **Verification:** All 39 tests pass
- **Committed in:** 4ffbf60 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial fix -- plan referenced a non-existent field. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ReplayManager is mounted and functional -- Plan 02 (frontend CyclePicker + ControlBar replay strip) can wire the REST calls
- Plan 03 (integration/polish) can verify end-to-end replay flow
- All three replay endpoints (start/advance/stop) return correct response schemas for frontend consumption

## Self-Check: PASSED

- All 6 key files exist on disk
- All 3 task commits verified in git log
- 39/39 tests passing in test_web.py

---
*Phase: 34-replay-mode-web-ui*
*Completed: 2026-04-15*
