---
phase: 11-live-graph-memory
plan: 01
subsystem: database
tags: [neo4j, asyncio, write-buffer, graph-memory, signal-flip, enums]

# Dependency graph
requires:
  - phase: 04-neo4j-graph-state
    provides: GraphStateManager base, existing asyncio.Queue pattern in StateStore
  - phase: 07-rounds-2-3-peer-influence-and-consensus
    provides: SignalType enum, 3-round cascade signal values

provides:
  - FlipType enum (7 values) in types.py for signal transition classification
  - EpisodeRecord frozen dataclass (7 fields) as the unit of write-buffer work
  - WriteBuffer class with push/drain/flush and drop-oldest queue policy
  - compute_flip_type() function covering all signal pairs and edge cases (None, PARSE_ERROR)

affects:
  - 11-02 (GraphStateManager episode methods consume EpisodeRecord)
  - 11-03 (simulation runner calls WriteBuffer.flush at round boundaries)
  - 12-social (social posts become EpisodeRecord input candidates)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "drop-oldest asyncio.Queue policy (mirrors StateStore._rationale_queue)"
    - "TYPE_CHECKING guard for cross-module imports to avoid circular dependencies"
    - "frozen dataclass for immutable intra-process message passing"

key-files:
  created:
    - src/alphaswarm/write_buffer.py
    - tests/test_write_buffer.py
  modified:
    - src/alphaswarm/types.py

key-decisions:
  - "EpisodeRecord stores flip_type as str (FlipType.value) for direct Neo4j property assignment without extra serialization"
  - "WriteBuffer.flush() signature takes graph_manager and entity_names as params (not injected at construction) to keep WriteBuffer stateless and testable without mocking at init time"
  - "compute_flip_type returns NONE for PARSE_ERROR inputs to prevent spurious flip detection on noisy rounds"

patterns-established:
  - "FlipType: signal transition enum uses (str, Enum) convention (not StrEnum) consistent with all other enums in types.py"
  - "WriteBuffer: drop-oldest eviction policy under queue pressure -- same pattern as StateStore rationale queue"
  - "TDD red-green: failing tests committed first, then implementation, separate commits"

requirements-completed: [GRAPH-01, GRAPH-02]

# Metrics
duration: 2min
completed: 2026-03-31
---

# Phase 11 Plan 01: Write-Behind Buffer Summary

**FlipType enum (7 transitions), EpisodeRecord frozen dataclass, WriteBuffer with drop-oldest asyncio queue, and compute_flip_type with full edge-case coverage**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-31T22:01:43Z
- **Completed:** 2026-03-31T22:03:31Z
- **Tasks:** 1 (TDD: 2 commits)
- **Files modified:** 3

## Accomplishments

- Added `FlipType(str, Enum)` with 7 values to `types.py` -- NONE, BUY_TO_SELL, SELL_TO_BUY, BUY_TO_HOLD, HOLD_TO_BUY, SELL_TO_HOLD, HOLD_TO_SELL
- Created `write_buffer.py` with `EpisodeRecord` frozen dataclass, `WriteBuffer` class, and `compute_flip_type()` function
- 23 unit tests covering all 6 signal transitions, 4 edge cases (None, PARSE_ERROR prev, PARSE_ERROR curr, same signal), push/drain/flush lifecycle, empty-flush zero-return, and full-queue drop-oldest behavior

## Task Commits

Each task was committed atomically (TDD split):

1. **Task 1 RED: Failing tests** - `185c2ca` (test)
2. **Task 1 GREEN: Implementation** - `451247e` (feat)

## Files Created/Modified

- `src/alphaswarm/types.py` - Added `FlipType(str, Enum)` with 7 values after `SignalType`
- `src/alphaswarm/write_buffer.py` - New module: `EpisodeRecord`, `WriteBuffer`, `compute_flip_type`
- `tests/test_write_buffer.py` - 23 unit tests covering all behaviors specified in plan

## Decisions Made

- `EpisodeRecord.flip_type` is stored as `str` (the `.value` of `FlipType`) rather than the enum itself -- this makes Neo4j property writes zero-cost with no extra serialization step in Plan 02.
- `WriteBuffer.flush()` accepts `graph_manager` and `entity_names` as call-time parameters rather than constructor injection -- keeps `WriteBuffer` stateless and trivially mockable in tests without constructor mocking.
- `compute_flip_type` returns `FlipType.NONE` for `PARSE_ERROR` inputs (both prev and curr directions) to prevent spurious flip detection when a round fails to parse an agent's output.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02 (GraphStateManager episode methods) can now import `EpisodeRecord` from `write_buffer` and use it as the record type for `write_rationale_episodes()` and `write_narrative_edges()`
- Plan 03 (simulation integration) can wire `WriteBuffer.push()` into agent inference callbacks and call `WriteBuffer.flush()` at round boundaries
- No blockers

---
*Phase: 11-live-graph-memory*
*Completed: 2026-03-31*

## Self-Check: PASSED

- src/alphaswarm/types.py - FOUND
- src/alphaswarm/write_buffer.py - FOUND
- tests/test_write_buffer.py - FOUND
- .planning/phases/11-live-graph-memory/11-01-SUMMARY.md - FOUND
- Commit 185c2ca (RED tests) - FOUND
- Commit 451247e (GREEN implementation) - FOUND
