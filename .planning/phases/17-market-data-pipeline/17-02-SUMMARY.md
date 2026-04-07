---
phase: 17-market-data-pipeline
plan: "02"
subsystem: market-data
tags: [yfinance, alpha-vantage, disk-cache, asyncio, graceful-degradation, tests]
dependency_graph:
  requires: [17-01]
  provides: [market_data_module, fetch_market_data, disk_cache, av_fallback, ExtractedTicker]
  affects: [17-03-PLAN, simulation.py integration]
tech_stack:
  added: []
  patterns: [asyncio-to-thread, per-ticker-lock, atomic-cache-write, taskgroup-parallel, structlog-component]
key_files:
  created: [src/alphaswarm/market_data.py]
  modified: [src/alphaswarm/types.py, tests/test_market_data.py]
decisions:
  - "ExtractedTicker added to types.py (not ticker_validator.py) — types.py is the canonical home for all frozen Pydantic data contracts"
  - "_safe_float returns None for '0' string in addition to None/'-'/'None' — AV returns '0' for missing numeric fields"
  - "Per-ticker lock dict _ticker_locks at module level — persists across calls in same process, prevents concurrent yfinance access to same symbol"
  - "yfinance import inside _fetch_yfinance_sync function body — avoids import-time side effects that could interfere with test patching"
metrics:
  duration_minutes: 3
  completed_date: "2026-04-07T01:11:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 17 Plan 02: Core Market Data Module Summary

**One-liner:** Async market_data.py with asyncio.to_thread yfinance fetch, httpx Alpha Vantage fallback, aiofiles atomic disk cache (1-hour TTL), asyncio.TaskGroup parallel dispatch, and graceful is_degraded=True fallback — all 12 tests passing.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement market_data.py core module | 056d56c | src/alphaswarm/market_data.py (349 lines), src/alphaswarm/types.py (+ExtractedTicker) |
| 2 | Un-stub all 9 test skips with real implementations | f866598 | tests/test_market_data.py (307 lines) |

## What Was Built

### Task 1: market_data.py Core Module

Created `src/alphaswarm/market_data.py` (349 lines) as the standalone async market data fetcher:

- **`_fetch_yfinance_sync(symbol)`** — synchronous blocking function wrapping `yf.Ticker(symbol).history(period="3mo")` and `.info`. Converts DataFrame to list of dicts. Computes summary stats (last_close, price_change_30d/90d_pct, avg_volume_30d). Raises `ValueError` if `.info` returns empty dict (Pitfall 2 mitigation).

- **`_fetch_alpha_vantage(symbol, api_key)`** — async httpx client calling `GLOBAL_QUOTE` + `OVERVIEW` endpoints. Maps AV field names to MarketDataSnapshot fields. `_safe_float()` helper handles None/"-"/"None"/"0" sentinel values from AV responses. Rate limit detection via `"Note"` key check.

- **`_read_cache(symbol, cache_dir)`** — async aiofiles read with UTC-aware TTL check (1 hour). Returns None if missing or expired.

- **`_write_cache(symbol, snapshot, cache_dir)`** — atomic temp-file-rename write pattern (`{symbol}.json.tmp` → `{symbol}.json`). Stores `cached_at` ISO timestamp + `snapshot.model_dump(mode="json")`.

- **`_fetch_single_ticker(symbol, company_name, av_key, cache_dir)`** — per-ticker `asyncio.Lock` from module-level `_ticker_locks` dict. Cache-first → yfinance via `asyncio.to_thread()` → AV fallback → degraded `MarketDataSnapshot(is_degraded=True)`. Writes successful fetches to cache.

- **`fetch_market_data(tickers, av_key, cache_dir)`** — public entry point. `asyncio.TaskGroup` spawns one task per `ExtractedTicker`. Returns `dict[symbol, MarketDataSnapshot]`.

Added `ExtractedTicker(symbol, company_name, relevance)` frozen Pydantic model to `types.py` (required for `fetch_market_data` signature; was referenced in plan interface spec but missing from types.py).

### Task 2: Test Implementations

Replaced all 9 `pytest.skip()` stubs with real async test implementations:

- **TestYfinanceFetch (2 tests):** Patch `_fetch_yfinance_sync` with pre-built dict; assert pe_ratio, price_history length, is_degraded. Patch `_fetch_single_ticker` as side_effect coroutine for 3-ticker parallel test.
- **TestFallbackDegradation (3 tests):** httpx.AsyncClient mocked with `__aenter__`/`__aexit__` AsyncMock returning AV JSON; assert not degraded when AV succeeds. Both fail path asserts is_degraded=True. No-key path asserts `httpx.AsyncClient` never instantiated.
- **TestDiskCache (4 tests):** cache_dir=tmp_path for isolation. Expired TTL test manually writes JSON with `cached_at` 2 hours ago. Cache hit log test uses `structlog.testing.capture_logs()` to assert event="cache_hit", ticker="AAPL".

## Verification Results

- `uv run pytest tests/test_market_data.py -v` → 12 passed, 0 skipped, 0 failed
- `uv run pytest tests/ -q --ignore=tests/test_graph_integration.py` → 533 passed, 5 warnings
- `from alphaswarm.market_data import fetch_market_data` → import OK
- `grep -c "asyncio.to_thread"` → 3 (yfinance call + type annotations)
- `grep -c "asyncio.Lock"` → 3 (dict type annotation + lock creation + usage)
- `grep "TaskGroup"` → asyncio.TaskGroup usage in fetch_market_data confirmed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ExtractedTicker not in types.py**
- **Found during:** Task 1 — `fetch_market_data` signature requires `ExtractedTicker` but it was absent from types.py
- **Issue:** Plan 01 did not add ExtractedTicker (it was in the interface spec but not in the Plan 01 task list)
- **Fix:** Added `ExtractedTicker(symbol, company_name, relevance)` frozen Pydantic model to `src/alphaswarm/types.py` immediately after `MarketDataSnapshot`
- **Files modified:** src/alphaswarm/types.py
- **Commit:** 056d56c

## Known Stubs

None. All 9 previously stubbed tests are now fully implemented and passing.

## Self-Check: PASSED
