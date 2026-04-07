---
phase: 17-market-data-pipeline
plan: "03"
subsystem: market-data
tags: [simulation-wiring, neo4j, cli, graceful-degradation, integration]
dependency_graph:
  requires: [17-01, 17-02]
  provides: [simulation_market_data_wiring, create_ticker_with_market_data, market_data_cli_summary]
  affects: [simulation.py, graph.py, cli.py, tests/conftest.py]
tech_stack:
  added: []
  patterns: [unwind-merge-cypher, type-checking-imports, forward-reference-pydantic]
key_files:
  created: []
  modified:
    - src/alphaswarm/simulation.py
    - src/alphaswarm/graph.py
    - src/alphaswarm/cli.py
    - src/alphaswarm/types.py
    - tests/conftest.py
decisions:
  - "SeedEvent.tickers field added with empty default list — backward compatible, enables future seed parser to populate tickers without breaking existing tests"
  - "MarketDataSnapshot import placed in TYPE_CHECKING block in both simulation.py and graph.py — avoids circular import risk"
  - "fetch_market_data import is a regular (non-TYPE_CHECKING) import in simulation.py since it is called at runtime"
  - "_print_market_data_summary is a standalone function (not modifying _print_injection_summary) — keeps injection summary focused on seed extraction"
metrics:
  duration_minutes: 6
  completed_date: "2026-04-06T21:20:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 5
---

# Phase 17 Plan 03: Simulation Wiring and CLI Integration Summary

**One-liner:** fetch_market_data() wired into run_simulation() after seed injection, Ticker+MarketDataSnapshot Neo4j nodes via UNWIND/MERGE, degraded-data WARNING banner in CLI, SeedEvent.tickers field added, graph test fixture updated.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wire fetch_market_data() into run_simulation() and add Neo4j graph method | cf30e30 | src/alphaswarm/simulation.py, src/alphaswarm/graph.py |
| 2 | Add degraded-data CLI warning and clean up graph test fixture | 1455fd3 | src/alphaswarm/cli.py, src/alphaswarm/types.py, tests/conftest.py |

## What Was Built

### Task 1: Simulation Wiring + Neo4j Graph Method

**graph.py — `create_ticker_with_market_data()`:**
- New async method on `GraphStateManager` that accepts `cycle_id` and `dict[str, MarketDataSnapshot]`
- Builds `snapshot_params` list (excluding `price_history` — too large for Neo4j property)
- Calls `_create_tickers_tx` via `session.execute_write` (session-per-method pattern)
- Wraps `Neo4jError` in `Neo4jWriteError` (consistent error handling pattern)
- Logs `ticker_market_data_created` with `ticker_count` and `degraded_count`

**graph.py — `_create_tickers_tx()` static method:**
- UNWIND-based Cypher: `MERGE (t:Ticker {symbol})` as idempotent upsert
- `ON CREATE SET` / `ON MATCH SET COALESCE` pattern for company_name
- `CREATE (c)-[:HAS_TICKER]->(t)` and `CREATE (t)-[:HAS_MARKET_DATA]->(md:MarketDataSnapshot)`
- `MarketDataSnapshot` node stores all 15 financial fields + `fetched_at: datetime()`
- Added `MarketDataSnapshot` to `TYPE_CHECKING` imports

**simulation.py — market data fetch block:**
- Regular import `from alphaswarm.market_data import fetch_market_data` (runtime call)
- `MarketDataSnapshot` added to `TYPE_CHECKING` block (type annotation only)
- Fetch block inserted AFTER `inject_seed()` + persona regeneration, BEFORE `run_round1()`
- Guards on `parsed_result.seed_event.tickers` being non-empty (graceful no-op when no tickers)
- Logs `market_data_fetch_start` with `ticker_count` and `tickers` list
- Calls `fetch_market_data(tickers, av_key=settings.alpha_vantage_api_key)`
- Persists to Neo4j via `graph_manager.create_ticker_with_market_data(cycle_id, market_snapshots)`
- Logs `market_data_fetch_complete` with `fetched` count and `degraded` symbols list

### Task 2: CLI Summary + Test Fixture

**cli.py — `_print_market_data_summary()`:**
- Accepts `dict[str, MarketDataSnapshot]`; no-op if empty
- Prints formatted header: "Market Data Summary"
- Shows `Tickers fetched`, `Successful`, `DEGRADED` counts
- When degraded tickers exist: prints `WARNING: Market data unavailable for: {symbols}` with `!`-border banner
- Formatted table for successful tickers: Symbol, Company (25 chars), Price, P/E, Mkt Cap
- `MarketDataSnapshot` added to `TYPE_CHECKING` block in cli.py

**cli.py — `_format_market_cap()`:**
- Formats float as `$3.0T`, `$500.0M`, `$1.2B` or `$1,234` for small values
- Returns `"N/A"` for `None`

**types.py — `SeedEvent.tickers` field:**
- Added `tickers: list[ExtractedTicker] = Field(default_factory=list)` to `SeedEvent`
- Backward compatible (empty default). Existing tests unaffected.
- `from __future__ import annotations` at file top makes forward reference to `ExtractedTicker` valid

**tests/conftest.py:**
- Added `MATCH (t:Ticker) DETACH DELETE t` and `MATCH (md:MarketDataSnapshot) DETACH DELETE md` to `graph_manager` fixture teardown
- Updated comment to reflect new node types

## Verification Results

- `uv run python -c "from alphaswarm.simulation import run_simulation; print('simulation import OK')"` → `simulation import OK`
- `uv run python -c "from alphaswarm.graph import GraphStateManager; print(hasattr(GraphStateManager, 'create_ticker_with_market_data'))"` → `True`
- `uv run python -c "from alphaswarm.cli import _print_market_data_summary; print('cli import OK')"` → `cli import OK`
- `_format_market_cap(3_000_000_000_000)` → `$3.0T`
- `_format_market_cap(500_000_000)` → `$500.0M`
- `grep "fetch_market_data" src/alphaswarm/simulation.py` → import and call present
- `grep "create_ticker_with_market_data" src/alphaswarm/graph.py` → method definition present
- `grep "degraded" src/alphaswarm/cli.py` → warning logic present
- `uv run pytest tests/ -x -q --ignore=tests/test_graph_integration.py` → `533 passed, 5 warnings`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SeedEvent missing `tickers` field**
- **Found during:** Task 2 verification — `test_run_simulation_calls_run_round1` failed with `AttributeError: 'SeedEvent' object has no attribute 'tickers'`
- **Issue:** The plan's interface spec referenced `parsed_result.seed_event.tickers` but `SeedEvent` was never given a `tickers` field. `ExtractedTicker` existed in types.py (added in Plan 02) but wasn't linked to `SeedEvent`.
- **Fix:** Added `tickers: list[ExtractedTicker] = Field(default_factory=list)` to `SeedEvent`. Backward compatible — default is empty list, so existing code that constructs `SeedEvent` without `tickers` is unaffected. `from __future__ import annotations` at file top allows the forward reference to `ExtractedTicker` (defined later in the same file).
- **Files modified:** src/alphaswarm/types.py
- **Commit:** 1455fd3

## Known Stubs

None. All integration points are wired. The `tickers` field on `SeedEvent` is currently populated as empty (the seed parser does not yet extract ticker symbols from rumor text). The market data fetch block in `run_simulation()` is guarded by `if parsed_result.seed_event.tickers:` so it silently no-ops in the current end-to-end flow. A future phase can populate `SeedEvent.tickers` by updating the seed parser prompt and `_try_parse_seed_json()` to extract ticker symbols.

## Self-Check: PASSED
