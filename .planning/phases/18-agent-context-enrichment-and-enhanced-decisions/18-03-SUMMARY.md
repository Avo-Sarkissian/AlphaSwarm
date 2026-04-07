---
phase: 18-agent-context-enrichment-and-enhanced-decisions
plan: 03
subsystem: simulation
tags: [sub-wave-dispatch, bracket-enrichment, market-context, positional-merge, integration]

# Dependency graph
requires:
  - phase: 18-01
    provides: enrichment.py module, bracket slice constants, build_enriched_user_message
  - phase: 18-02
    provides: enrich_snapshots_with_headlines for AV NEWS_SENTIMENT headline population
provides:
  - Sub-wave dispatch with bracket-enriched user_message at all 3 dispatch sites
  - _group_personas_by_slice helper for bracket grouping
  - _dispatch_enriched_sub_waves helper with positional merge
  - Pre-Round 1 headline enrichment call in run_simulation
affects: [simulation, worker-agents]

# Tech tracking
tech-stack:
  added: []
  patterns: [sub-wave-dispatch, positional-merge-by-agent-id, bracket-group-peer-context-slicing]

key-files:
  created:
    - tests/test_simulation_enrichment.py
  modified:
    - src/alphaswarm/simulation.py
    - tests/test_simulation.py

key-decisions:
  - "Empty market_snapshots triggers single-dispatch fallback with bare rumor (zero behavior change for simulations without tickers)"
  - "Results merged by agent_id dict lookup in original persona order, not by sub-wave insertion order (Pitfall 5)"
  - "peer_contexts_by_id dict built from positional list before sub-wave split, then sliced per group"
  - "BracketType, AgentPersona, MarketDataSnapshot moved from TYPE_CHECKING to runtime imports (needed at runtime by helpers)"

patterns-established:
  - "Sub-wave dispatch: group personas by bracket slice, dispatch per-group with enriched message, merge by agent_id"
  - "Peer context dict conversion: positional list -> {agent_id: context} -> per-group sliced list"

requirements-completed: [ENRICH-01, ENRICH-02, DECIDE-02]

# Metrics
duration: 5min
completed: 2026-04-07
---

# Phase 18 Plan 03: Sub-Wave Dispatch and Enrichment Wiring Summary

**Sub-wave dispatch at all 3 simulation dispatch sites with bracket-enriched market context, positional merge by agent_id, and pre-Round 1 headline enrichment**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-07T14:10:25Z
- **Completed:** 2026-04-07T14:15:34Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 3

## Accomplishments
- Created `_group_personas_by_slice()` helper that groups all 10 brackets into 3 slice categories (Technicals, Fundamentals, Earnings/Insider)
- Created `_dispatch_enriched_sub_waves()` helper that dispatches per-bracket sub-waves with enriched user_message and merges results by agent_id in original persona order
- Wired sub-wave dispatch into all 3 dispatch sites: run_round1 (Round 1), run_simulation Round 2, run_simulation Round 3
- Added `enrich_snapshots_with_headlines()` call once pre-Round 1 in run_simulation (not per-round)
- Added `market_snapshots` parameter to `run_round1()` function signature
- Converted Round 2/3 positional peer_contexts lists to per-agent dicts for sub-wave slicing
- Empty market_snapshots triggers backward-compatible single-dispatch fallback
- 8 new integration tests covering grouping, fallback, 3-wave dispatch, merge order, peer context slicing, bracket-specific content, and positional invariant
- 578 total tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests for sub-wave dispatch and enrichment wiring** - `575c324` (test)
2. **Task 2 GREEN: Wire sub-wave dispatch into all 3 dispatch sites** - `9fcd897` (feat)

_TDD flow: RED (8 failing tests) -> GREEN (all 578 tests pass)_

## Files Created/Modified
- `tests/test_simulation_enrichment.py` - New: 8 integration tests for sub-wave dispatch
- `src/alphaswarm/simulation.py` - Added _group_personas_by_slice, _dispatch_enriched_sub_waves helpers; wired into all 3 dispatch sites; added enrich_snapshots_with_headlines pre-Round 1; added market_snapshots param to run_round1
- `tests/test_simulation.py` - Updated test_run_round1_dispatches_with_no_peer_context to match new dispatch pattern (peer_contexts vs peer_context)

## Decisions Made
- Empty market_snapshots triggers single-dispatch fallback with bare rumor -- ensures zero behavior change for simulations without tickers (backward compatibility)
- Results merged by agent_id dict lookup in original persona order, not by sub-wave insertion order -- prevents positional misalignment (Pitfall 5 from plan)
- peer_contexts_by_id dict built from positional list before sub-wave split, then sliced per group -- each sub-wave receives only the peer contexts for agents in that group
- BracketType, AgentPersona, MarketDataSnapshot moved from TYPE_CHECKING to runtime imports since _group_personas_by_slice and _dispatch_enriched_sub_waves use them at runtime (not just type annotations)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed runtime NameError for BracketType**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** `BracketType` was imported under `TYPE_CHECKING` but used at runtime in `_group_personas_by_slice` dict values
- **Fix:** Moved `BracketType`, `AgentPersona`, `MarketDataSnapshot` to runtime imports from `alphaswarm.types`
- **Files modified:** `src/alphaswarm/simulation.py`
- **Commit:** `9fcd897`

**2. [Rule 1 - Bug] Updated existing test assertion for new dispatch pattern**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** `test_run_round1_dispatches_with_no_peer_context` asserted `peer_context` kwarg which no longer exists (now `peer_contexts`)
- **Fix:** Updated assertion to check `peer_contexts is None` matching the new `_dispatch_enriched_sub_waves` calling pattern
- **Files modified:** `tests/test_simulation.py`
- **Commit:** `9fcd897`

## Known Stubs

None -- all functions are fully implemented with no placeholder logic.

## Issues Encountered

None.

## Self-Check: PASSED

- [x] tests/test_simulation_enrichment.py exists
- [x] src/alphaswarm/simulation.py modified with all 3 dispatch sites wired
- [x] Commit 575c324 found (RED tests)
- [x] Commit 9fcd897 found (GREEN implementation)
- [x] 578 tests pass with no regressions

---
*Phase: 18-agent-context-enrichment-and-enhanced-decisions*
*Completed: 2026-04-07*
