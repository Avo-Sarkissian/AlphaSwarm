---
phase: 03-resource-governance
plan: 01
subsystem: infra
tags: [asyncio, psutil, sysctl, state-machine, concurrency, memory-pressure]

# Dependency graph
requires:
  - phase: 02-ollama-integration
    provides: "ResourceGovernor stub with BoundedSemaphore, GovernorSettings, worker.py acquire/release pattern"
provides:
  - "Dynamic ResourceGovernor with TokenPool (debt-aware) and 5-state machine"
  - "MemoryMonitor with dual-signal reading (psutil + macOS sysctl)"
  - "MemoryReading with explicit dual-signal precedence (sysctl master)"
  - "GovernorMetrics dataclass and StateStore.update_governor_metrics wiring"
  - "GovernorCrisisError exception for crisis timeout"
  - "7 new GovernorSettings fields for dynamic governance"
affects: [03-02-PLAN, batch-dispatch, tui-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TokenPool with asyncio.Queue and debt tracking for safe concurrent shrinking"
    - "Dual-signal memory monitoring (psutil percent + macOS sysctl kernel pressure)"
    - "5-state machine (RUNNING/THROTTLED/PAUSED/CRISIS/RECOVERING) with reason-logged transitions"
    - "StateStore metric emission on state change only (not every check interval)"

key-files:
  created:
    - src/alphaswarm/memory_monitor.py
  modified:
    - src/alphaswarm/governor.py
    - src/alphaswarm/config.py
    - src/alphaswarm/errors.py
    - src/alphaswarm/state.py
    - src/alphaswarm/app.py
    - tests/test_governor.py
    - tests/test_memory_monitor.py
    - tests/test_worker.py
    - tests/test_integration_inference.py

key-decisions:
  - "TokenPool uses asyncio.Queue with debt counter instead of BoundedSemaphore for O(1) grow/shrink without deadlock"
  - "sysctl kernel pressure is master signal; YELLOW/RED overrides psutil regardless of percent value"
  - "GovernorMetrics emitted on state change only (not every 2s check) to avoid log/metric spam"
  - "GovernorMetrics dataclass added to state.py ahead of Plan 02 schedule to enable governor wiring"
  - "ResourceGovernor constructor accepts optional settings (defaults to GovernorSettings()) for backward compatibility"

patterns-established:
  - "Debt pattern: shrink records debt for checked-out tokens, release consumes debt before returning to pool"
  - "State machine with explicit handler methods per state (_handle_running, _handle_throttled, etc.)"
  - "Runtime import of GovernorMetrics inside _emit_metrics to avoid circular import (governor -> state -> types)"

requirements-completed: [INFRA-01, INFRA-02]

# Metrics
duration: 7min
completed: 2026-03-25
---

# Phase 03 Plan 01: Core ResourceGovernor Summary

**Dynamic ResourceGovernor with Queue-based TokenPool (debt-aware), 5-state machine, dual-signal memory monitoring (psutil + macOS sysctl), and StateStore metric wiring**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-25T03:39:44Z
- **Completed:** 2026-03-25T03:47:12Z
- **Tasks:** 2 (both TDD: RED -> GREEN)
- **Files modified:** 10

## Accomplishments
- Replaced Phase 2 BoundedSemaphore with Queue-based TokenPool supporting O(1) grow/shrink and debt tracking for safe concurrent shrinking
- Implemented 5-state machine (RUNNING, THROTTLED, PAUSED, CRISIS, RECOVERING) with all 17 locked decisions (D-01 through D-17)
- Created MemoryMonitor with dual-signal reading -- psutil percent and macOS sysctl kernel pressure with explicit precedence (sysctl is master)
- Added GovernorMetrics emission to StateStore on state transitions for observability (D-09, D-11)
- All 152 tests pass including 89 new tests for governor and memory monitor

## Task Commits

Each task was committed atomically:

1. **Task 1: GovernorSettings extensions, GovernorCrisisError, MemoryMonitor** (TDD)
   - RED: `597e6ea` (test) - Failing tests for MemoryMonitor, MemoryReading, GovernorSettings, GovernorCrisisError
   - GREEN: `4177107` (feat) - Implement GovernorSettings extensions, GovernorCrisisError, MemoryMonitor
2. **Task 2: TokenPool, ResourceGovernor rewrite, StateStore wiring** (TDD)
   - RED: `304689e` (test) - Failing tests for TokenPool, state machine, StateStore integration
   - GREEN: `08c4a1d` (feat) - Rewrite ResourceGovernor with TokenPool, state machine, StateStore wiring

## Files Created/Modified
- `src/alphaswarm/memory_monitor.py` - NEW: Dual-signal memory monitoring (psutil + sysctl), PressureLevel enum, MemoryReading with threshold properties
- `src/alphaswarm/governor.py` - REWRITTEN: TokenPool with debt tracking, GovernorState enum, ResourceGovernor with 5-state machine
- `src/alphaswarm/config.py` - EXTENDED: 7 new GovernorSettings fields (scale_up, crisis, jitter, batch failure)
- `src/alphaswarm/errors.py` - EXTENDED: GovernorCrisisError with duration_seconds
- `src/alphaswarm/state.py` - EXTENDED: GovernorMetrics dataclass and update_governor_metrics method
- `src/alphaswarm/app.py` - UPDATED: create_app_state passes GovernorSettings and StateStore to governor
- `tests/test_memory_monitor.py` - NEW: 39 tests for memory monitor, reading properties, settings, crisis error
- `tests/test_governor.py` - NEW: 50 tests for TokenPool, state machine, scale-up, crisis, StateStore
- `tests/test_worker.py` - UPDATED: Constructor calls updated for new ResourceGovernor signature
- `tests/test_integration_inference.py` - UPDATED: Constructor calls updated for new ResourceGovernor signature

## Decisions Made
- TokenPool uses asyncio.Queue[bool] with debt counter for O(1) grow/shrink without deadlock risk
- sysctl kernel pressure is the master signal -- YELLOW/RED forces CRISIS regardless of psutil percent
- GovernorMetrics emitted on state change only (not every check_interval) to avoid metric spam
- GovernorMetrics dataclass added to state.py ahead of Plan 02 schedule to enable governor -> StateStore wiring in this plan
- ResourceGovernor constructor accepts `settings: GovernorSettings | None = None` (optional) for backward compat with Phase 2 call sites

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added GovernorMetrics to state.py and update_governor_metrics method**
- **Found during:** Task 2 (ResourceGovernor rewrite)
- **Issue:** Plan says "GovernorMetrics dataclass will be created by Plan 02 Task 2" but governor tests and StateStore wiring need it now
- **Fix:** Added GovernorMetrics frozen dataclass and update_governor_metrics method to state.py
- **Files modified:** src/alphaswarm/state.py
- **Verification:** All tests pass, metrics emitted on state transitions
- **Committed in:** 08c4a1d (Task 2 commit)

**2. [Rule 1 - Bug] Updated existing test files for new constructor signature**
- **Found during:** Task 2 (ResourceGovernor rewrite)
- **Issue:** test_worker.py, test_integration_inference.py used `ResourceGovernor(baseline_parallel=N)` which no longer works
- **Fix:** Updated to `ResourceGovernor(GovernorSettings(baseline_parallel=N))`
- **Files modified:** tests/test_worker.py, tests/test_integration_inference.py
- **Verification:** Full test suite passes (152/152)
- **Committed in:** 08c4a1d (Task 2 commit)

**3. [Rule 1 - Bug] Fixed app.py initialization order for StateStore**
- **Found during:** Task 2 (app.py update)
- **Issue:** StateStore was created after being passed to ResourceGovernor constructor
- **Fix:** Moved StateStore creation before ResourceGovernor creation in create_app_state
- **Files modified:** src/alphaswarm/app.py
- **Verification:** test_app.py passes
- **Committed in:** 08c4a1d (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 bug fixes, 1 blocking dependency)
**Impact on plan:** All auto-fixes necessary for correctness. GovernorMetrics was scheduled for Plan 02 but needed now for governor wiring -- no scope creep, just moved earlier.

## Issues Encountered
None - plan executed cleanly after deviations were auto-fixed.

## Known Stubs
None - all functionality is fully wired. GovernorMetrics in state.py stores the latest metrics but does not yet propagate to TUI (that is Phase 9 scope).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ResourceGovernor is ready for batch dispatch integration (Plan 02)
- Constructor signature is locked: `ResourceGovernor(settings: GovernorSettings, *, state_store: StateStore | None = None)`
- Plan 02 can build BatchDispatcher that calls `governor.acquire()/release(success=True/False)` and `governor.report_wave_failures()`
- GovernorMetrics wiring is already in place for Plan 02 StateStore integration

## Self-Check: PASSED

All 8 created/modified source files verified present. All 4 task commits verified in git log.

---
*Phase: 03-resource-governance*
*Completed: 2026-03-25*
