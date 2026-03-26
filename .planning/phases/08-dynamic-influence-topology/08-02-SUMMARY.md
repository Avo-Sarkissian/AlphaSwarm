---
phase: 08-dynamic-influence-topology
plan: 02
subsystem: simulation
tags: [influence-topology, bracket-summaries, dynamic-peers, peer-selection, asyncio]

# Dependency graph
requires:
  - phase: 08-01
    provides: compute_influence_edges, select_diverse_peers, BracketSummary, compute_bracket_summaries
  - phase: 07-rounds-2-3-peer-influence-and-consensus
    provides: run_simulation, _dispatch_round, RoundCompleteEvent, SimulationResult
provides:
  - run_simulation with influence injection between rounds (compute_influence_edges after R1 and R2)
  - _dispatch_round with dynamic peer selection (select_diverse_peers) and zero-citation fallback
  - RoundCompleteEvent carrying bracket_summaries per round
  - SimulationResult carrying round1/2/3_summaries
  - CLI rendering bracket tables from BracketSummary instead of inline computation
affects: [09-tui, cli.py, simulation.py, test_simulation.py, test_cli.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Zero-citation fallback: empty dict from compute_influence_edges triggers static read_peer_decisions path"
    - "Falsy guard pattern: `round_weights if round_weights else None` routes to static vs dynamic"
    - "Keyword-only parameters on _dispatch_round for influence_weights and prev_decisions"
    - "BracketSummary as promoted data type flowing from simulation -> CLI via event/result"

key-files:
  created: []
  modified:
    - src/alphaswarm/simulation.py
    - src/alphaswarm/cli.py
    - tests/test_simulation.py
    - tests/test_cli.py

key-decisions:
  - "Falsy guard `round1_weights if round1_weights else None` correctly handles empty dict (zero-citation cold start per Pitfall 1): _dispatch_round receives None -> static fallback"
  - "bracket_summaries is a required (non-optional) field on RoundCompleteEvent and SimulationResult: all construction sites updated"
  - "_aggregate_brackets retained in cli.py as documented fallback for inject path and round1 standalone; docstring notes simulation.py as authoritative source"
  - "_print_bracket_table_from_summaries extracted as reusable helper for D-08 rendering in both _print_round_report and _print_simulation_summary"
  - "run_simulation receives brackets parameter to pass to compute_bracket_summaries; _run_pipeline in cli.py threads it through"

patterns-established:
  - "Data promotion pattern: compute values in simulation layer, carry in result/event types, render in CLI — no recomputation at render time"
  - "Zero-citation fallback: when weights empty, fallback to static Neo4j read (not failure)"

requirements-completed: [SIM-07, SIM-08]

# Metrics
duration: 11min
completed: 2026-03-26
---

# Phase 8 Plan 02: Simulation Pipeline Wiring Summary

**run_simulation() injects compute_influence_edges() between rounds with dynamic peer selection via select_diverse_peers, zero-citation static fallback, and bracket summaries embedded in all result/event types**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-03-26T21:23:00Z
- **Completed:** 2026-03-26T21:34:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Wired compute_influence_edges() into run_simulation() after Round 1 (shapes Round 2) and Round 2 (shapes Round 3) per D-02/D-04
- Updated _dispatch_round with influence_weights + prev_decisions kwargs: dynamic path via select_diverse_peers, static fallback path when weights empty (D-05/D-06, Pitfall 1)
- Added bracket_summaries to RoundCompleteEvent and round1/2/3_summaries to SimulationResult (D-08)
- Updated CLI to render bracket tables from BracketSummary via _print_bracket_table_from_summaries (D-08)
- All 339 tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire influence computation and _dispatch_round dynamic/static selection** - `e7d5629` (feat)
2. **Task 2: Update CLI to consume BracketSummary from simulation layer** - `8049ea9` (feat)

## Files Created/Modified

- `src/alphaswarm/simulation.py` - Extended RoundCompleteEvent/SimulationResult with bracket_summaries fields; updated _dispatch_round for dynamic/static peer selection; wired compute_influence_edges and compute_bracket_summaries into run_simulation; added brackets parameter
- `src/alphaswarm/cli.py` - Added BracketSummary import; added _print_bracket_table_from_summaries; updated _print_round_report with bracket_summaries kwarg; updated _print_simulation_summary to use round3_summaries; updated _aggregate_brackets docstring; updated _make_round_complete_handler and _run_pipeline
- `tests/test_simulation.py` - Added BracketConfig import and TEST_BRACKETS fixture; updated mock_graph_manager with compute_influence_edges mock; updated all run_simulation call sites with brackets=TEST_BRACKETS; updated SimulationResult constructions with new summary fields; added 4 new integration tests
- `tests/test_cli.py` - Updated SimulationResult constructions with round1/2/3_summaries=(); updated RoundCompleteEvent constructions with bracket_summaries=(); fixed mock_result.round3_summaries in _run_pipeline test

## Decisions Made

- Falsy guard `round1_weights if round1_weights else None` correctly handles zero-citation cold start: empty dict evaluates falsy, passes None to _dispatch_round, triggers static fallback per D-05
- bracket_summaries is non-optional on both dataclasses: all construction sites must provide it (empty tuple `()` as backward-compatible default in tests)
- _aggregate_brackets kept in cli.py with documented sync requirement note — not deleted, serves inject/Round1 fallback path
- compute_influence_edges mock added to mock_graph_manager fixture (returns {}) to allow run_simulation tests to pass without Neo4j

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- test_run_pipeline_calls_run_simulation_with_callback used `MagicMock(spec=SimulationResult)` but did not set `round3_summaries` on the mock. Fixed by adding `mock_result.round3_summaries = ()` to match new field requirement. No logic change.

## Known Stubs

None - all data flows are wired. BracketSummary populated from real compute_bracket_summaries in run_simulation.

## Next Phase Readiness

- Dynamic influence topology (Phase 8) integration complete: influence edges shape peer selection, bracket summaries flow through all layers
- Phase 9 TUI can consume BracketSummary from SimulationResult/RoundCompleteEvent without recomputation
- Simulation pipeline ready for Phase 9 snapshot-based TUI rendering

---
*Phase: 08-dynamic-influence-topology*
*Completed: 2026-03-26*
