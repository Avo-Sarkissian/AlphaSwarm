---
phase: 20-report-enhancement-and-integration-hardening
plan: "01"
subsystem: graph-persistence
tags: [neo4j, consensus, graph, tdd, simulation]
dependency_graph:
  requires: []
  provides: [write_ticker_consensus_summary, read_market_context, TickerConsensusSummary-nodes]
  affects: [simulation.py, graph.py, tests/conftest.py]
tech_stack:
  added: []
  patterns: [UNWIND-batch-write, session-per-method, OPTIONAL-MATCH-for-compatibility]
key_files:
  created: []
  modified:
    - src/alphaswarm/graph.py
    - src/alphaswarm/simulation.py
    - tests/test_graph.py
    - tests/conftest.py
decisions:
  - "compute_ticker_consensus called once per round site and assigned to local variable (no double-compute)"
  - "graph write placed OUTSIDE state_store guard so it runs in headless/non-TUI mode"
  - "round2_weights reused for Round 3 graph write (no round3_weights computed post-simulation)"
  - "OPTIONAL MATCH in read_market_context for backward compatibility with pre-Phase-20 cycles"
metrics:
  duration: "~12 min"
  completed: "2026-04-08T03:27:21Z"
  tasks_completed: 2
  files_modified: 4
---

# Phase 20 Plan 01: Neo4j Ticker Consensus Persistence Summary

**One-liner:** UNWIND batch write and OPTIONAL MATCH read for TickerConsensusSummary nodes wired into all 3 simulation rounds via graph_manager.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add graph methods for ticker consensus persistence and retrieval, update test teardown | 0e9324b | src/alphaswarm/graph.py, tests/test_graph.py, tests/conftest.py |
| 2 | Wire simulation.py to persist ticker consensus to Neo4j after each round | d80fa3d | src/alphaswarm/simulation.py |

## What Was Built

### graph.py additions

- **SCHEMA_STATEMENTS**: Added `CREATE INDEX tcs_round IF NOT EXISTS FOR (tcs:TickerConsensusSummary) ON (tcs.round_num)` for efficient round-based queries.
- **TYPE_CHECKING import**: Added `from alphaswarm.state import TickerConsensus` for type annotations without circular import.
- **`write_ticker_consensus_summary(cycle_id, round_num, consensus_list)`**: Converts `list[TickerConsensus]` to 6-field dicts (omits `bracket_breakdown`), calls `session.execute_write` with the UNWIND tx function, wraps `Neo4jError` as `Neo4jWriteError`. Empty list is a no-op.
- **`_write_ticker_consensus_tx(tx, cycle_id, round_num, consensus_params)`**: UNWIND batch write creating `TickerConsensusSummary` nodes linked to both `Ticker` via `HAS_CONSENSUS` and `Cycle` via `HAS_CONSENSUS`.
- **`read_market_context(cycle_id)`**: Session-per-method read returning `list[dict]` with 16 keys (market data + latest-round consensus). Wraps `Neo4jError` as `Neo4jConnectionError`.
- **`_read_market_context_tx(tx, cycle_id)`**: Cypher with `OPTIONAL MATCH` for `TickerConsensusSummary`, `ORDER BY tcs.round_num DESC` + `collect(tcs)[0]` to select latest round consensus per ticker.

### tests/conftest.py

Added `MATCH (n:TickerConsensusSummary) DETACH DELETE n` to `graph_manager` fixture teardown to prevent cross-test pollution. Updated comment to include `TickerConsensusSummary` in listed node types.

### simulation.py (3 sites)

At each of the 3 `set_ticker_consensus` call sites (Round 1 line ~1117, Round 2 line ~1261, Round 3 line ~1397):
- Extracted `compute_ticker_consensus()` call to a `ticker_consensus_rN` local variable OUTSIDE the `state_store is not None` guard.
- `state_store.set_ticker_consensus(ticker_consensus_rN)` stays inside the guard.
- Added `if ticker_consensus_rN: await graph_manager.write_ticker_consensus_summary(cycle_id, N, list(ticker_consensus_rN))` OUTSIDE the guard.

### tests/test_graph.py (5 new tests)

- **`TestWriteTickerConsensus`**: 3 tests covering correct params, empty-list no-op, Neo4jError wrapping.
- **`TestReadMarketContext`**: 2 tests covering 16-key return structure, Neo4jError wrapping.

## Verification

- `uv run pytest tests/test_graph.py -x -q` — 67 passed
- `uv run pytest tests/ -x -q --ignore=tests/test_graph_integration.py` — 608 passed
- `grep -c "write_ticker_consensus_summary" src/alphaswarm/simulation.py` — 3
- All plan verification grep checks: pass

**Note:** `tests/test_graph_integration.py` has a pre-existing event loop failure (requires live Neo4j Docker container) that was present before this plan's changes. Confirmed via git stash verification.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/src/alphaswarm/graph.py` — FOUND (modified)
- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/src/alphaswarm/simulation.py` — FOUND (modified)
- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/tests/test_graph.py` — FOUND (modified)
- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/tests/conftest.py` — FOUND (modified)
- Commit `0e9324b` — FOUND
- Commit `d80fa3d` — FOUND
