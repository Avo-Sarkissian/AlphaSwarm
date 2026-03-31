---
phase: 11-live-graph-memory
plan: 02
subsystem: database
tags: [neo4j, asyncio, graph-memory, rationale-episodes, narrative-edges, unwind]

# Dependency graph
requires:
  - phase: 11-live-graph-memory
    plan: 01
    provides: EpisodeRecord frozen dataclass, WriteBuffer with push/drain/flush interface
  - phase: 04-neo4j-graph-state
    provides: GraphStateManager base, session-per-method pattern, UNWIND write pattern

provides:
  - write_rationale_episodes() method on GraphStateManager (batch HAS_EPISODE writes)
  - write_narrative_edges() method (Python-side substring match + REFERENCES edges)
  - read_cycle_entities() method (Cycle-MENTIONS->Entity name loading)
  - write_decision_narratives() method (batch decision_narrative SET on Agent nodes)
  - write_decisions() refactored to return list[str] and accept optional decision_ids
  - RationaleEpisode composite index in SCHEMA_STATEMENTS

affects:
  - 11-03 (simulation integration calls flush() which delegates to these 4 new methods)
  - 14-interviews (queries RationaleEpisode nodes and decision_narrative property)
  - 15-reports (full reasoning arc traversal uses HAS_EPISODE and REFERENCES edges)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "session-per-method isolation for all new graph writes (same as existing write_decisions pattern)"
    - "Python-side substring matching before UNWIND to avoid N*M Cypher cross-product"
    - "Optional pre-generated IDs pattern: caller generates UUIDs, passes to both write_decisions() and WriteBuffer.push()"
    - "Two-statement transaction pattern: episodes + references in separate execute_write calls (readable, under budget)"

key-files:
  created: []
  modified:
    - src/alphaswarm/graph.py
    - tests/test_graph.py

key-decisions:
  - "write_decisions() returns list[str] of decision IDs so callers can pass the same IDs to WriteBuffer.push() -- solves Pitfall 1 (decision_id availability)"
  - "Entity name original casing preserved in REFERENCES matches -- Python match lowercases for comparison, UNWIND sends original name to Cypher MATCH"
  - "write_rationale_episodes() and write_narrative_edges() are separate execute_write() calls (not merged into one tx) -- cleaner separation, still within transaction budget"

patterns-established:
  - "New graph write methods: accept list[EpisodeRecord | dict] via hasattr() duck-typing, normalize to dict list before tx call"
  - "Noop guard: all write methods return early on empty input without opening a session"
  - "REFERENCES edge matching: always pass original-cased entity_name to UNWIND, never lowercased"

requirements-completed: [GRAPH-01, GRAPH-02, GRAPH-03]

# Metrics
duration: 2min
completed: 2026-03-31
---

# Phase 11 Plan 02: GraphStateManager Episode Methods Summary

**4 new GraphStateManager methods (write_rationale_episodes, write_narrative_edges, read_cycle_entities, write_decision_narratives) + write_decisions refactor returning list[str] with optional pre-generated IDs + RationaleEpisode composite index**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-31T22:05:30Z
- **Completed:** 2026-03-31T22:07:50Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Added `write_rationale_episodes()` with `_batch_write_episodes_tx()` -- UNWIND batch creates RationaleEpisode nodes linked to Decision via `HAS_EPISODE` edges
- Added `write_narrative_edges()` with `_batch_write_references_tx()` -- Python-side case-insensitive substring match produces `REFERENCES {match_type: "substring"}` edges preserving original entity name casing (Pitfall 4 from research)
- Added `read_cycle_entities()` -- Cypher MATCH on `Cycle-[:MENTIONS]->Entity` for once-per-cycle entity name loading
- Added `write_decision_narratives()` with `_batch_write_narratives_tx()` -- UNWIND batch SET `decision_narrative` property on Agent nodes
- Refactored `write_decisions()` to accept optional `decision_ids: list[str] | None = None` and return `list[str]` -- solves Pitfall 1 (decision_id availability at buffer push time)
- Extended `SCHEMA_STATEMENTS` with `CREATE INDEX episode_cycle_round IF NOT EXISTS FOR (re:RationaleEpisode) ON (re.cycle_id, re.round)`
- Added 22 new unit tests (47 total in test_graph.py, all passing)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend SCHEMA_STATEMENTS, refactor write_decisions, add 4 new methods + tests** - `c4c2e9c` (feat)

## Files Created/Modified

- `src/alphaswarm/graph.py` - RationaleEpisode index in schema, write_decisions refactor, 4 new write/read methods + 4 static tx functions
- `tests/test_graph.py` - 22 new unit tests: write_decisions return value, pregenerated IDs, mismatch validation, episode writes, narrative edge matching (case/casing/empty), entity reads, narrative writes, schema index assertion

## Decisions Made

- `write_decisions()` returns `list[str]` and accepts `decision_ids: list[str] | None = None` -- the minimal backward-compatible change needed to expose IDs to the caller without touching the proven `_batch_write_decisions_tx` transaction function
- `write_rationale_episodes()` and `write_narrative_edges()` kept as separate `execute_write()` calls rather than merged into one transaction function -- cleaner separation and still within the 10-transaction-per-round budget (4 total: write_decisions + write_episodes + write_references + compute_influence)
- Entity names passed with original casing to UNWIND MATCH -- Python lowercases both sides for comparison; the matched pair stores the original name so `MATCH (e:Entity {name: m.entity_name})` succeeds

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03 (simulation integration) can now call `write_decisions(..., decision_ids=pre_ids)` and `WriteBuffer.flush()` at round boundaries
- `WriteBuffer.flush()` from Plan 01 already calls `write_rationale_episodes()` and `write_narrative_edges()` -- the contract is now fulfilled
- `read_cycle_entities()` is ready for Plan 03 to call at cycle start and cache for all 3 rounds
- `write_decision_narratives()` is ready for post-simulation narrative generation
- No blockers

---
*Phase: 11-live-graph-memory*
*Completed: 2026-03-31*

## Self-Check: PASSED

- src/alphaswarm/graph.py - FOUND
- tests/test_graph.py - FOUND
- .planning/phases/11-live-graph-memory/11-02-SUMMARY.md - FOUND (this file)
- Commit c4c2e9c - FOUND
