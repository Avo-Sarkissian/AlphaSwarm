---
phase: 07-rounds-2-3-peer-influence-and-consensus
plan: 01
subsystem: simulation
tags: [asyncio, consensus-cascade, peer-influence, dataclass, frozen, callback, structlog]

# Dependency graph
requires:
  - phase: 06-round-1-standalone
    provides: "run_round1(), dispatch_wave(), graph read_peer_decisions, AgentDecision types"
provides:
  - "run_simulation() full 3-round consensus cascade orchestrator"
  - "_dispatch_round() per-agent peer context assembly and dispatch"
  - "ShiftMetrics, SimulationResult, RoundCompleteEvent frozen dataclasses"
  - "_format_peer_context() with prompt guard and D-01/D-02/D-03 formatting"
  - "_compute_shifts() in-memory signal flip and bracket confidence delta computation"
  - "dispatch_wave peer_contexts list parameter for personalized per-agent context"
  - "sanitize_rationale shared utility in utils.py"
  - "OnRoundComplete callback type for progressive output"
affects: [07-02-cli-simulate-command, 08-dynamic-influence-topology, 09-textual-tui-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Callback pattern (OnRoundComplete) for progressive output without coupling"
    - "Tuple-only frozen dataclasses for true immutability"
    - "Shared utility module (utils.py) to avoid simulation->CLI import dependency"
    - "Sequential peer reads before dispatch to avoid Neo4j pool exhaustion"
    - "ValueError for runtime contract checks (not assert)"

key-files:
  created:
    - src/alphaswarm/utils.py
  modified:
    - src/alphaswarm/simulation.py
    - src/alphaswarm/batch_dispatcher.py
    - src/alphaswarm/cli.py
    - tests/test_simulation.py
    - tests/test_batch_dispatcher.py

key-decisions:
  - "Callback pattern for progressive output: on_round_complete fires after each round, decoupling simulation engine from CLI/TUI rendering"
  - "Tuple fields in frozen dataclasses: ShiftMetrics uses tuple[tuple[str,int],...] not dict for true immutability"
  - "sanitize_rationale extracted to utils.py: avoids simulation importing from CLI module (Codex review concern)"
  - "Sequential peer reads: avoids Neo4j connection pool exhaustion with 100 concurrent reads"
  - "ValueError over assert: runtime contract checks survive Python -O optimization"
  - "Prompt guard in peer context: prevents cross-agent prompt injection via peer rationale text"

patterns-established:
  - "OnRoundComplete callback: async callback type alias for progressive output"
  - "Shared utilities in utils.py: cross-layer functions that avoid import cycles"
  - "peer_contexts list parameter: per-agent context injection via dispatch_wave"

requirements-completed: [SIM-05, SIM-06]

# Metrics
duration: 6min
completed: 2026-03-26
---

# Phase 7 Plan 1: Simulation Engine Summary

**Full 3-round consensus cascade engine with per-agent peer context injection, progressive on_round_complete callback, and immutable shift metrics computation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-26T15:32:36Z
- **Completed:** 2026-03-26T15:39:11Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- run_simulation() orchestrates all 3 rounds end-to-end: run_round1() then Rounds 2-3 with per-agent peer context
- Each agent gets personalized top-5 peer context from the previous round via _format_peer_context with prompt guard
- on_round_complete callback enables progressive CLI/TUI output without coupling simulation engine to rendering
- ShiftMetrics detects signal flips and per-bracket confidence deltas between consecutive rounds
- Worker model reloads once for Rounds 2-3 block with fresh governor monitoring session
- Full test suite: 293 passed, 10 skipped, 0 failures (37 tests in test_simulation.py alone)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract shared utility, extend dispatch_wave, add simulation types and pure functions** - `c364fcc` (feat)
2. **Task 2: Implement _dispatch_round and run_simulation with on_round_complete callback** - `ad96881` (feat)

_Both tasks followed TDD: RED (failing tests) then GREEN (implementation)._

## Files Created/Modified
- `src/alphaswarm/utils.py` - Shared sanitize_rationale utility (extracted from CLI)
- `src/alphaswarm/simulation.py` - ShiftMetrics, RoundCompleteEvent, SimulationResult dataclasses; _format_peer_context, _compute_shifts pure functions; _dispatch_round, run_simulation orchestrator
- `src/alphaswarm/batch_dispatcher.py` - Added peer_contexts list parameter with ValueError validation
- `src/alphaswarm/cli.py` - Delegated _sanitize_rationale to utils.py, removed re import
- `tests/test_simulation.py` - 26 new tests (Task 1: 13 pure function/type tests, Task 2: 14 orchestration tests)
- `tests/test_batch_dispatcher.py` - 3 new tests for per-agent peer_contexts

## Decisions Made
- Callback pattern (OnRoundComplete) for progressive output: decouples simulation engine from CLI/TUI
- Tuple fields in frozen dataclasses for true immutability (Codex review concern)
- sanitize_rationale extracted to utils.py to avoid simulation -> CLI import dependency
- Sequential peer reads before dispatch to prevent Neo4j pool exhaustion
- ValueError for runtime contract checks (not assert -- survives -O)
- Prompt guard text appended to peer context to prevent cross-agent injection

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None - all functions are fully wired and operational.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- run_simulation() is ready for CLI integration in Plan 02 (simulate subcommand)
- OnRoundComplete callback is the integration point for progressive CLI output
- ShiftMetrics and SimulationResult are the data contracts for report rendering
- dispatch_wave's peer_contexts parameter enables per-agent context in the full pipeline

## Self-Check: PASSED

All 6 created/modified files exist. Both task commits (c364fcc, ad96881) verified in git log.

---
*Phase: 07-rounds-2-3-peer-influence-and-consensus*
*Completed: 2026-03-26*
