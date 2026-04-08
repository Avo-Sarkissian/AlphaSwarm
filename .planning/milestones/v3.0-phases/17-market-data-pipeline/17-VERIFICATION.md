---
phase: 17-market-data-pipeline
verified: 2026-04-07T01:22:00Z
status: gaps_found
score: 12/13 must-haves verified
gaps:
  - truth: "yfinance 1.2.0+ is declared in pyproject.toml dependencies"
    status: failed
    reason: "yfinance>=1.2.0 was added in commit 7ba7efa (Plan 01) but silently dropped in commit cf30e30 (Plan 03 Task 1). The package is installed in .venv and all tests pass today, but pyproject.toml no longer declares it. A fresh `uv sync` on another machine will not install yfinance, causing ImportError in market_data.py."
    artifacts:
      - path: "pyproject.toml"
        issue: "yfinance>=1.2.0 entry missing from [project.dependencies]"
    missing:
      - "Add \"yfinance>=1.2.0\" back to [project.dependencies] in pyproject.toml"
human_verification:
  - test: "Run simulation with a ticker rumor where yfinance fails and AV key is absent"
    expected: "Simulation proceeds with degraded snapshot; structlog WARNING emitted; CLI prints degraded-data banner before Round 1"
    why_human: "Requires a live simulation run; cannot verify degraded-warning CLI output programmatically without a real Ollama session"
  - test: "Run the same simulation twice within 1 hour"
    expected: "Second run logs cache_hit=True at INFO level for each ticker; no re-fetch occurs"
    why_human: "Requires two consecutive live runs to exercise cache TTL path in production"
---

# Phase 17: Market Data Pipeline Verification Report

**Phase Goal:** Enrich the simulation with real market data — fetch 90-day price history and financial fundamentals for every ticker extracted from the seed rumor, persist it in Neo4j, and surface degraded-data warnings in the CLI — before Round 1 begins.
**Verified:** 2026-04-07T01:22:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `MarketDataSnapshot` frozen Pydantic model exists with 18+ fields including `is_degraded` | VERIFIED | `src/alphaswarm/types.py` lines 100-127; 18 fields confirmed; `frozen=True` |
| 2 | `AppSettings.alpha_vantage_api_key: str \| None = None` in config | VERIFIED | `src/alphaswarm/config.py` line 91 |
| 3 | `market_data.py` exports all required functions | VERIFIED | All 6 functions importable; confirmed via `uv run python -c "from alphaswarm.market_data import ..."` |
| 4 | `asyncio.to_thread` used for blocking yfinance call | VERIFIED | `market_data.py` line 274: `data = await asyncio.to_thread(_fetch_yfinance_sync, symbol)` |
| 5 | `asyncio.TaskGroup` used for parallel ticker fetching | VERIFIED | `market_data.py` lines 345-347: `async with asyncio.TaskGroup() as tg:` |
| 6 | Per-ticker locks (`_ticker_locks` dict) prevent concurrent yfinance access | VERIFIED | `market_data.py` lines 23, 260-263 |
| 7 | 1-hour cache TTL (`CACHE_TTL_SECONDS = 3600`) | VERIFIED | `market_data.py` line 18 |
| 8 | `simulation.py` calls `fetch_market_data` after seed injection before Round 1 | VERIFIED | `simulation.py` lines 774-793; guard on `parsed_result.seed_event.tickers`; call precedes `run_round1()` at line 796 |
| 9 | `graph.py` has `create_ticker_with_market_data()` with UNWIND Cypher | VERIFIED | `graph.py` lines 260-354; UNWIND+MERGE pattern confirmed; HAS_TICKER and HAS_MARKET_DATA edges present |
| 10 | `cli.py` has `_print_market_data_summary()` with degraded-data warnings | VERIFIED | `cli.py` lines 106-139; WARNING banner with `!`-border printed when `degraded` list is non-empty |
| 11 | All 12 tests in `test_market_data.py` pass (0 skipped) | VERIFIED | Live run: `12 passed, 0 skipped in 0.08s` |
| 12 | Full test suite passes (533 passed, 0 failures) | VERIFIED | Live run: `533 passed, 5 warnings in 15.77s` |
| 13 | `yfinance>=1.2.0` declared in `pyproject.toml` | FAILED | Absent from current `pyproject.toml`; was present at commit 7ba7efa; dropped accidentally in cf30e30 |

**Score:** 12/13 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/market_data.py` | Async market data fetcher with cache and fallback | VERIFIED | 350 lines; all 6 functions substantive |
| `src/alphaswarm/types.py` | `MarketDataSnapshot` + `ExtractedTicker` frozen models | VERIFIED | Lines 100-134; 18 fields + `is_degraded` |
| `src/alphaswarm/config.py` | `alpha_vantage_api_key: str \| None = None` | VERIFIED | Line 91 |
| `src/alphaswarm/simulation.py` | `fetch_market_data()` call wired | VERIFIED | Lines 774-793 |
| `src/alphaswarm/graph.py` | `create_ticker_with_market_data()` method | VERIFIED | Lines 260-354 |
| `src/alphaswarm/cli.py` | `_print_market_data_summary()` with degraded warning | VERIFIED | Lines 106-139 |
| `tests/test_market_data.py` | 12 tests, 0 skipped | VERIFIED | 308 lines; all 12 passing |
| `pyproject.toml` | `yfinance>=1.2.0` in dependencies | STUB | Entry missing — dropped in commit cf30e30 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `market_data.py` | `types.py` | `from alphaswarm.types import MarketDataSnapshot` | WIRED | Line 13: `from alphaswarm.types import ExtractedTicker, MarketDataSnapshot` |
| `market_data.py` | `data/market_cache/` | `CACHE_DIR = Path("data/market_cache")` | WIRED | Line 17 |
| `simulation.py` | `market_data.py` | `from alphaswarm.market_data import fetch_market_data` | WIRED | Line 21 |
| `simulation.py` | `graph.py` | `graph_manager.create_ticker_with_market_data()` | WIRED | Line 788 |
| `cli.py` | `types.py` | `MarketDataSnapshot` in TYPE_CHECKING block | WIRED | Line 31 |
| `tests/test_market_data.py` | `market_data.py` | `from alphaswarm.market_data import ...` | WIRED | Lines 101, 119, 151, 221, 249, 267, 275, 292 |

---

## Data-Flow Trace (Level 4)

Not applicable. Phase 17 is a data-ingestion layer that writes to memory and Neo4j, not a rendering component. The `_print_market_data_summary()` function renders live data passed directly as a parameter from `run_simulation()` — no hidden hollow prop.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All market_data functions importable | `uv run python -c "from alphaswarm.market_data import fetch_market_data, _read_cache, _write_cache, _fetch_single_ticker, _fetch_alpha_vantage, _fetch_yfinance_sync; print('OK')"` | `All market_data functions importable: OK` | PASS |
| `GraphStateManager.create_ticker_with_market_data` exists | `uv run python -c "from alphaswarm.graph import GraphStateManager; print(hasattr(...))"` | `True` | PASS |
| `_print_market_data_summary` importable from cli | `uv run python -c "from alphaswarm.cli import _print_market_data_summary"` | `cli import OK` | PASS |
| `run_simulation` importable (no circular import) | `uv run python -c "from alphaswarm.simulation import run_simulation"` | `simulation import OK` | PASS |
| 12 market data tests pass | `uv run pytest tests/test_market_data.py -v` | `12 passed in 0.08s` | PASS |
| Full suite green | `uv run pytest tests/ -q --ignore=tests/test_graph_integration.py` | `533 passed in 15.77s` | PASS |
| yfinance 1.2.0 installed in venv | `uv run python -c "import yfinance; print(yfinance.__version__)"` | `1.2.0` | PASS |
| yfinance declared in pyproject.toml | `grep "yfinance" pyproject.toml` | No match | FAIL |

---

## Requirements Coverage

DATA-01 through DATA-04 are not listed in `.planning/REQUIREMENTS.md` (the current REQUIREMENTS.md covers only v1/v2 requirements for Phases 1-15 and does not include Phase 17 data requirements). These requirement IDs are referenced in the PLAN frontmatter only. Coverage is assessed against the PLAN must-haves instead.

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DATA-01 | 17-02-PLAN, 17-03-PLAN | yfinance fetch, 90-day OHLCV, financial fundamentals, `MarketDataSnapshot` model | SATISFIED | `_fetch_yfinance_sync` (market_data.py:31-123); `MarketDataSnapshot` 18 fields (types.py:100-127); 5 tests cover fetch behavior |
| DATA-02 | 17-02-PLAN, 17-03-PLAN | Alpha Vantage fallback, graceful degradation, never abort | SATISFIED | `_fetch_alpha_vantage` (market_data.py:141-187); degraded path (market_data.py:305-318); 3 fallback tests pass |
| DATA-03 | 17-03-PLAN | News headlines deferred to Phase 18; `headlines` field reserved | SATISFIED | `types.py` line 124: `headlines: list[str] = Field(default_factory=list)` — always empty list; comment documents Phase 18 deferral |
| DATA-04 | 17-02-PLAN, 17-03-PLAN | Disk cache with 1-hour TTL; cache-hit logged at INFO | SATISFIED | `_read_cache`/`_write_cache` (market_data.py:195-240); `CACHE_TTL_SECONDS = 3600`; structlog `cache_hit` event; 4 cache tests pass |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `pyproject.toml` | — | `yfinance>=1.2.0` missing from `[project.dependencies]` | BLOCKER | Fresh `uv sync` on another machine will not install yfinance; `import yfinance` in `market_data.py` will raise `ImportError` at runtime, breaking all market data fetches |
| `market_data.py` | 183-184 | `gross_margin_pct=None` and `debt_to_equity=None` hardcoded in AV path | INFO | Documented limitation: AV OVERVIEW does not provide these fields; comment makes it explicit; not a stub |
| `simulation.py` | 777 | `if parsed_result.seed_event.tickers:` guard means market data silently no-ops when tickers list is empty | INFO | Intentional design: the seed parser does not yet populate `SeedEvent.tickers`; market data fetch is a no-op in end-to-end flow today; documented in 17-03-SUMMARY Known Stubs section |

---

## Human Verification Required

### 1. Degraded-Data CLI Warning

**Test:** Run `uv run start` with a seed rumor containing tickers, with `ALPHASWARM_ALPHA_VANTAGE_API_KEY` unset and yfinance patched/broken (or use an invalid ticker symbol that guarantees failure).
**Expected:** Before Round 1 output appears, the CLI prints the `!`-border WARNING banner listing degraded ticker symbols. Simulation continues without abort.
**Why human:** Requires a live Ollama session and simulation run; the warning is printed to stdout during `run_simulation()`, which cannot be exercised without a running Ollama instance.

### 2. Cache-Hit Log on Second Run

**Test:** Run the same simulation twice within 1 hour with the same tickers in the seed rumor.
**Expected:** Second run logs `event='cache_hit', ticker='{SYMBOL}'` at INFO level for each ticker; no re-fetch occurs; run is noticeably faster.
**Why human:** Requires two consecutive live runs; the seed parser does not currently populate `SeedEvent.tickers` automatically, so the cache path is not exercised in normal end-to-end flow until Phase 18 wires up ticker extraction.

---

## Gaps Summary

One blocker gap was found:

**`yfinance>=1.2.0` dropped from `pyproject.toml`** (BLOCKER). The package was correctly added in commit `7ba7efa` (Plan 01, Task 1) but was inadvertently omitted when commit `cf30e30` (Plan 03, Task 1) rewrote/replaced `pyproject.toml`. The current working tree's `pyproject.toml` does not list yfinance. The package is present in `.venv` from the earlier `uv add`, so all tests pass locally today, but a fresh environment would fail at runtime with `ImportError` when `_fetch_yfinance_sync` is invoked.

`httpx` is used directly in `market_data.py` (`_fetch_alpha_vantage`) but is not declared as a direct dependency. It is available as a transitive dependency of `ollama>=0.6.1`, which IS declared. This is a minor implicit-dependency risk (if the `ollama` client ever drops httpx, market_data.py would break silently) but is not a current blocker.

The `SeedEvent.tickers` field being empty in the current seed parser means the market data pipeline is technically wired but effectively dormant until Phase 18 adds ticker extraction to the seed parsing prompt. This is a documented design decision (17-03-SUMMARY Known Stubs), not a gap.

---

_Verified: 2026-04-07T01:22:00Z_
_Verifier: Claude (gsd-verifier)_
