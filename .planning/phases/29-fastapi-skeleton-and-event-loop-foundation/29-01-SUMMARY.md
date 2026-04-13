---
phase: 29-fastapi-skeleton-and-event-loop-foundation
plan: 01
subsystem: api
tags: [fastapi, uvicorn, asyncio, state, tui, statestore]

# Dependency graph
requires:
  - phase: 28-simulation-replay
    provides: ReplayStore with non-draining snapshot() as reference pattern
provides:
  - fastapi>=0.115 and uvicorn[standard]>=0.34 installed and importable
  - StateStore.snapshot() is non-destructive (rationale_entries always empty tuple)
  - StateStore.drain_rationales(limit) method for explicit queue drain
  - TUI _poll_snapshot calls drain_rationales(5) for normal-mode rationale processing
affects: [30-websocket-broadcaster, future-web-api-plans]

# Tech tracking
tech-stack:
  added: [fastapi>=0.115, uvicorn[standard]>=0.34, starlette (transitive), uvloop (transitive)]
  patterns:
    - "Non-destructive snapshot + explicit drain: StateStore.snapshot() returns scalar state only; consumers call drain_rationales() to pop queue entries"
    - "Independent consumer drain: TUI and WebSocket broadcaster each call drain_rationales() without interfering with each other's reads"

key-files:
  created: []
  modified:
    - pyproject.toml
    - src/alphaswarm/state.py
    - tests/test_state.py
    - src/alphaswarm/tui.py

key-decisions:
  - "StateStore.snapshot() made non-destructive so WebSocket broadcaster (Phase 30) and TUI can both read state without stealing entries from each other (D-06)"
  - "drain_rationales(limit=5) is the explicit destructive read path, called independently by each consumer (D-07)"
  - "TUI _poll_snapshot updated to call state_store.drain_rationales(5) rather than reading snapshot.rationale_entries"

patterns-established:
  - "Non-destructive snapshot pattern: snapshot() returns only scalar/dict state; queue draining is always explicit via drain_rationales()"
  - "Consumer-owned drain: each TUI/WebSocket consumer independently calls drain_rationales() on its own tick cadence"

requirements-completed: [BE-02]

# Metrics
duration: 15min
completed: 2026-04-13
---

# Phase 29 Plan 01: FastAPI Skeleton and Event Loop Foundation Summary

**Non-destructive StateStore.snapshot() refactor with drain_rationales() method, fastapi+uvicorn installed, and TUI call site updated — enabling independent multi-consumer queue draining for Phase 30 WebSocket broadcaster**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-13T01:30:00Z
- **Completed:** 2026-04-13T01:44:58Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Installed fastapi>=0.115 and uvicorn[standard]>=0.34 via `uv sync` (starlette, uvloop, watchfiles transitively installed)
- Refactored StateStore.snapshot() to be non-destructive: `rationale_entries` always returns `()`, eliminating the queue drain side-effect
- Added `drain_rationales(limit=5)` method that explicitly pops up to `limit` entries from the queue
- Updated TUI `_poll_snapshot` to call `state_store.drain_rationales(5)` in the normal-mode branch (replay branch unchanged)
- Updated all affected tests: 2 existing drain tests rewritten, 2 `_push_top_rationales` tests fixed, 1 `test_rationale_queue_full_drops_oldest` drain loop updated, 3 new tests added (31 total, all pass)

## Task Commits

Each task was committed atomically:

1. **Task 1: Install FastAPI + Uvicorn dependencies and refactor StateStore** - `b643470` (feat)
2. **Task 2: Update test_state.py — fix breaking tests + add new non-destructive tests** - `4399652` (test)
3. **Task 3: Update TUI _poll_snapshot to call drain_rationales(5)** - `0a8774d` (feat)

## Files Created/Modified

- `pyproject.toml` — Added fastapi>=0.115 and uvicorn[standard]>=0.34 to project dependencies
- `src/alphaswarm/state.py` — snapshot() made non-destructive; drain_rationales(limit) added after snapshot()
- `tests/test_state.py` — 4 existing tests updated, 3 new tests added; 31 tests total, all green
- `src/alphaswarm/tui.py` — _poll_snapshot normal-mode branch updated to call drain_rationales(5)

## Decisions Made

- Used `drain_rationales(limit=5)` as the default limit to match the original batch size from the old snapshot() drain loop
- Kept replay branch reading `snapshot.rationale_entries` unchanged — ReplayStore.snapshot() pre-sets rationale_entries and has no drain_rationales() method; changing it would require architectural work outside this plan's scope
- Fixed `test_push_top_rationales_sorts_by_influence` and `test_push_top_rationales_skips_parse_errors` (Rule 1: auto-fix) — they used `snap.rationale_entries` expecting non-empty data, which would fail with the non-destructive refactor

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed two _push_top_rationales tests that would fail after snapshot() refactor**
- **Found during:** Task 2 (test_state.py update)
- **Issue:** `test_push_top_rationales_sorts_by_influence` and `test_push_top_rationales_skips_parse_errors` called `store.snapshot()` and asserted `snap.rationale_entries` had non-empty content — this would fail with the non-destructive snapshot since rationale_entries is always `()`
- **Fix:** Changed both tests to call `store.drain_rationales(5)` and assert on the returned tuple instead
- **Files modified:** tests/test_state.py
- **Verification:** `uv run pytest tests/test_state.py -x -q` — 31 passed
- **Committed in:** 4399652 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug: tests that would break after planned refactor)
**Impact on plan:** Fix was necessary for correctness. Both tests tested the same logical behavior; only the drain mechanism changed. No scope creep.

## Issues Encountered

None — plan executed cleanly. `uv sync` resolved all transitive dependencies (starlette, uvloop, watchfiles) without conflicts.

## User Setup Required

None — no external service configuration required. FastAPI and Uvicorn are installed locally; no server is started in this plan.

## Known Stubs

None — no stub values or placeholder data introduced. All changes are structural refactors of existing production code.

## Next Phase Readiness

- Phase 30 (WebSocket broadcaster) can now `import fastapi` and call `state_store.drain_rationales()` independently on its own tick cadence without interfering with the TUI drain
- StateStore contract is stable: `snapshot()` for all scalar state, `drain_rationales(limit)` for queue pop
- ReplayStore.snapshot() is unaffected (already non-destructive by design)

---
*Phase: 29-fastapi-skeleton-and-event-loop-foundation*
*Completed: 2026-04-13*
