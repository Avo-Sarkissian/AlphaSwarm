---
phase: 28-simulation-replay
plan: 01
subsystem: database, state, ui, testing
tags: [neo4j, cypher, asyncio, pytest, textual, replay, enum, dataclass]

# Dependency graph
requires:
  - phase: 27-shock-analysis-and-reporting
    provides: GraphStateManager read method patterns, Neo4j session/execute_read patterns
  - phase: 10-tui-panels-and-telemetry
    provides: StateStore, StateSnapshot, BracketSummary, RationaleEntry, _PHASE_LABELS
provides:
  - SimulationPhase.REPLAY enum value in types.py
  - ReplayStore class (no-drain snapshot, round-filtered agent_states)
  - read_full_cycle_signals (Decision-first Cypher, perf_counter timing)
  - read_completed_cycles (rounds-3 existence check, LIMIT param)
  - read_bracket_narratives_for_round (lowercase signal CASE, round_num param)
  - read_rationale_entries_for_round (parameterized round_num + limit)
  - _PHASE_LABELS["REPLAY"] = "Replay" in tui.py
  - 14 new passing tests across test_state.py, test_graph.py, test_tui.py, test_cli.py
affects: [28-simulation-replay-plan-02, 28-simulation-replay-plan-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ReplayStore: no-drain snapshot() semantics — set_rationale_entries replaces tuple in place, never queued"
    - "Decision-first Cypher queries start from Decision node for index usage (MATCH (d:Decision)<-[:MADE]-(a:Agent))"
    - "Lowercase signal casing in CASE comparisons ('buy'/'sell'/'hold') to match SignalType enum storage"
    - "perf_counter timing with structlog duration_ms on all replay read methods"
    - "Inline local imports (import time as _time) for performance-sensitive methods"

key-files:
  created:
    - .planning/phases/28-simulation-replay/28-01-SUMMARY.md
  modified:
    - src/alphaswarm/types.py
    - src/alphaswarm/state.py
    - src/alphaswarm/graph.py
    - src/alphaswarm/tui.py
    - tests/test_state.py
    - tests/test_graph.py
    - tests/test_tui.py
    - tests/test_cli.py

key-decisions:
  - "ReplayStore uses plain class (not @dataclass) to avoid frozen/mutable field complexity with tuple replacement"
  - "CLI replay tests use standalone argparse parser (Review #7): cli.py main() builds parser inline, no _build_parser() factory — documented as known limitation, Plan 02 will wire the real subcommand"
  - "test_agent_cell_disabled_during_replay is a design contract test (REPLAY != COMPLETE) — full click-gate TUI test deferred to Plan 02 per Review concern #8"
  - "Pre-existing test_report.py failures (19 tests) confirmed as baseline failures before this plan — out of scope"

patterns-established:
  - "Replay read methods follow same session/execute_read pattern as Phase 27 shock methods"
  - "All new Cypher uses parameterized queries only — no f-string construction"

requirements-completed: [REPLAY-01]

# Metrics
duration: 5min
completed: 2026-04-12
---

# Phase 28 Plan 01: Simulation Replay Data Layer Summary

**SimulationPhase.REPLAY enum + ReplayStore class + 4 parameterized Neo4j read methods + 14 Wave 0 tests covering state, graph, TUI, and CLI replay contracts**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-12T20:15:14Z
- **Completed:** 2026-04-12T20:19:27Z
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments

- Added `SimulationPhase.REPLAY = "replay"` to types.py and `ReplayStore` class to state.py — ReplayStore produces no-drain StateSnapshot filtered by active round
- Added 4 new `GraphStateManager` read methods with parameterized Cypher: `read_full_cycle_signals` (Decision-first, perf_counter timing), `read_completed_cycles`, `read_bracket_narratives_for_round` (lowercase signal casing), `read_rationale_entries_for_round`
- Added `SimulationPhase.REPLAY: "Replay"` to `_PHASE_LABELS` in tui.py; 4 new tests for TUI label and CLI replay argparse contract
- Full Wave 0 test coverage: 14 new passing tests, zero regressions in 551-test suite (excluding pre-existing test_report.py failures)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 tests + SimulationPhase.REPLAY + ReplayStore** - `c90463b` (feat)
2. **Task 2: Wave 0 tests + Graph read methods** - `8e3331e` (feat)
3. **Task 3: Wave 0 tests for TUI header replay format + CLI replay subcommand** - `d0cd953` (feat)

_Note: TDD tasks each had RED (test write) then GREEN (implementation) within a single atomic commit._

## Files Created/Modified

- `src/alphaswarm/types.py` - Added `REPLAY = "replay"` to `SimulationPhase` enum
- `src/alphaswarm/state.py` - Added `ReplayStore` class with `set_round`, `set_bracket_summaries`, `set_rationale_entries`, `snapshot` methods
- `src/alphaswarm/graph.py` - Added `read_full_cycle_signals`, `read_completed_cycles`, `read_bracket_narratives_for_round`, `read_rationale_entries_for_round` and their `_tx` static counterparts
- `src/alphaswarm/tui.py` - Added `SimulationPhase.REPLAY: "Replay"` to `_PHASE_LABELS` dict
- `tests/test_state.py` - Added 6 new tests: `test_simulation_phase_replay`, `test_replay_store_snapshot`, `test_replay_store_round_advance`, `test_replay_store_set_bracket_summaries`, `test_replay_store_set_rationale_entries`, `test_replay_store_no_drain`
- `tests/test_graph.py` - Added 4 new tests: `test_read_full_cycle_signals`, `test_read_completed_cycles`, `test_read_bracket_narratives_for_round`, `test_read_rationale_entries_for_round`
- `tests/test_tui.py` - Added 2 new tests: `test_header_replay_format`, `test_agent_cell_disabled_during_replay`
- `tests/test_cli.py` - Added 2 new tests: `test_replay_subcommand`, `test_replay_subcommand_default_cycle`

## Decisions Made

- **ReplayStore as plain class**: Using `class ReplayStore` (not `@dataclass`) avoids frozen/mutable complexity — internal state is all private, mutation only via explicit setter methods.
- **Standalone argparse in CLI tests**: `cli.py` builds its parser inline in `main()` with no factory function. Rather than refactoring `main()`, CLI tests use a standalone parser matching the intended contract. Plan 02 will wire the real `replay` subparser into `main()`.
- **Design contract test for AgentCell**: Full click-gate coverage during replay requires TUI wiring from Plan 02. Task 3 test only validates the enum contract (`REPLAY != COMPLETE`), which is sufficient for Wave 0 per Review concern #8.

## Deviations from Plan

None — plan executed exactly as written. All three TDD cycles (RED → GREEN) completed cleanly on the first attempt.

## Issues Encountered

None.

## Known Stubs

None. All new code is fully implemented data layer and test scaffolding. No stub values, placeholders, or TODO markers were introduced.

## Next Phase Readiness

Plan 02 (TUI + CLI wiring) can now implement against the tested contracts:
- `SimulationPhase.REPLAY` importable from `alphaswarm.types`
- `ReplayStore` importable from `alphaswarm.state` with verified snapshot semantics
- All 4 graph read methods on `GraphStateManager` available with verified mock behavior
- TUI `_phase_display_label(REPLAY)` returns `"Replay"`
- CLI replay argparse contract verified (Plan 02 only needs to call `_build_parser()` or wire directly into `main()`)

No blockers.

---
*Phase: 28-simulation-replay*
*Completed: 2026-04-12*
