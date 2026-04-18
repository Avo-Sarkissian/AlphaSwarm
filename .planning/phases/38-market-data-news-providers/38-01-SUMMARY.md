---
phase: 38
plan: 01
subsystem: ingestion
tags: [ingestion, yfinance, market-data, protocol-implementation, decimal-precision, nan-guard]
dependency_graph:
  requires:
    - alphaswarm.ingestion.providers (MarketDataProvider Protocol, _fetch_failed_market_slice helper — Phase 37-02)
    - alphaswarm.ingestion.types (MarketSlice, Fundamentals — Phase 37-01)
    - yfinance>=1.2.2,<2.0 (newly added)
  provides:
    - YFinanceMarketDataProvider (real MarketDataProvider for Phase 40 ContextPacket.market)
    - _decimal_or_none helper (NaN/Inf guard, reusable by Plan 38-02 RSS provider if needed)
  affects:
    - pyproject.toml dependencies + importlinter source_modules
    - tests/invariants/test_importlinter_coverage.py (stays green with new module)
tech_stack:
  added:
    - yfinance 1.3.0 (satisfies >=1.2.2,<2.0 floor; transitive: pandas, numpy, lxml, requests, multitasking, platformdirs, frozendict)
  patterns:
    - "asyncio.to_thread wrapper for sync I/O (yfinance fast_info + info are sync HTTP)"
    - "asyncio.gather with return_exceptions=False over per-ticker tasks (D-05 error isolation via broad try/except per task)"
    - "Decimal(str(value)) for financial precision; math.isnan/isinf guard for yfinance NaN leakage"
    - "Pattern 3: shared _fetch_failed_market_slice helper, no hand-rolled failure construction"
key_files:
  created:
    - src/alphaswarm/ingestion/yfinance_provider.py
    - tests/test_yfinance_provider.py
    - .planning/phases/38-market-data-news-providers/38-01-SUMMARY.md
  modified:
    - pyproject.toml
    - src/alphaswarm/ingestion/__init__.py
    - uv.lock
decisions:
  - "D-05 per-ticker error isolation: asyncio.gather over asyncio.to_thread per ticker, with _fetch_one_sync wrapping the entire body in a broad try/except so one bad ticker in a 100-ticker batch cannot fail the whole call"
  - "D-06 field mapping: fast_info.last_price + fast_info.last_volume for quick numerics; .info dict for fundamentals (trailingPE, trailingEps, marketCap)"
  - "D-07 no semaphore: providers are called once per simulation run, not per agent; yfinance throttling concerns live with Yahoo's backend not our dispatch layer"
  - "D-09 staleness binary: 'fresh' on success, 'fetch_failed' on any exception; no time-window 'stale' computation in this phase"
  - "D-10 no caching: each provider call is a fresh scrape; caching is deferred"
  - "D-19 never-raise: the entire _fetch_one_sync body sits under one except Exception — D-19 violation is the surface we protect, not a specific exception class (preserves catch of Pitfall 1 KeyError('currentTradingPeriod'))"
  - "Gemini review MEDIUM — NaN/Inf guard: _decimal_or_none returns None (not Decimal('NaN')) when value is float + math.isnan/isinf, preventing NaN Decimal leakage into Phase 40 advisory synthesis"
  - "Codex review MEDIUM — ticker normalization is upstream caller's responsibility: provider passes tickers through to yf.Ticker(t) as-is, documented in module docstring"
  - "Codex review MEDIUM — Phase 40 call pattern: module docstring explicitly instructs callers to invoke exactly ONE of the three Protocol methods per run (recommended get_prices) since all three return the same complete MarketSlice via _fetch_batch_shared"
metrics:
  started_at: "2026-04-18T22:25:15Z"
  completed_at: "2026-04-18T22:30:19Z"
  duration_minutes: 5
  tasks_completed: 3
  tests_added: 15
  tests_passing_in_regression: 57
---

# Phase 38 Plan 01: yfinance Market Data Provider Summary

## One-liner

Real `YFinanceMarketDataProvider` — `MarketDataProvider` Protocol implementation backed by `yfinance.Ticker.fast_info` (price, volume) + `.info` (pe_ratio, eps, market_cap), with per-ticker thread-isolated error handling, `Decimal(str(...))` precision, and `math.isnan`/`math.isinf` guard against yfinance NaN/Inf ratio fields.

## What Shipped

### Source
- `src/alphaswarm/ingestion/yfinance_provider.py` (new, 155 lines)
  - `_SOURCE = "yfinance"` module constant
  - `_decimal_or_none(value)` — NaN/Inf-guarded `Decimal(str(...))` conversion
  - `_fetch_one_sync(ticker)` — thread-safe synchronous fetch wrapped in one broad `try/except Exception` (D-19 never-raise; catches Pitfall 1 `KeyError('currentTradingPeriod')` from `fast_info.last_price` on delisted tickers)
  - `class YFinanceMarketDataProvider` with shared `_fetch_batch_shared` and three delegating Protocol methods (`get_prices`, `get_fundamentals`, `get_volume`)
  - Full-module docstring covers D-05/06/07/09/10/19, Pitfall 1/5/6, Gemini NaN/Inf fix, Codex ticker-normalization clarification, and **Phase 40 call pattern** (call exactly one method per run)

### Tests
- `tests/test_yfinance_provider.py` (new, 15 tests)
  - Field mapping + Protocol conformance (4 tests)
  - `Decimal(str(0.1))` precision probe (1 test)
  - `_decimal_or_none` NaN/Inf/-Inf/None direct unit + two provider-level NaN and Inf tests (3 tests)
  - D-19 never-raise — Pitfall 1 `KeyError('currentTradingPeriod')` path + generic-exception path (2 tests)
  - Edge cases — empty list, duplicate tickers (2 tests)
  - Module-level grep invariants — yfinance import only, shared helper reuse, NaN/Inf guard presence (3 tests)

### Config
- `pyproject.toml` `[project].dependencies`: `"yfinance>=1.2.2,<2.0"` appended (floor matches 38-REVIEWS Codex HIGH — live-probe-verified)
- `pyproject.toml` `[tool.importlinter].contracts[0].source_modules`: `"alphaswarm.ingestion.yfinance_provider"` inserted between `"alphaswarm.ingestion.types"` and `"alphaswarm.interview"` (same commit as module creation — Pitfall 8 drift-resistance preserved)
- `src/alphaswarm/ingestion/__init__.py`: re-exports `YFinanceMarketDataProvider`, `__all__` kept alphabetical

## Decisions Implemented

| Decision | Realization |
|----------|-------------|
| D-05 per-ticker error isolation | `asyncio.gather(*(asyncio.to_thread(_fetch_one_sync, t) for t in tickers), return_exceptions=False)`; `_fetch_one_sync` is contractually never-raise so `return_exceptions=False` is intentional (a raise would surface as a loud test failure, catching any D-19 regression) |
| D-06 fast_info + info split | `fi.last_price`/`fi.last_volume` for quick numerics; `yft.info.get(...)` for fundamentals (`trailingPE`, `trailingEps`, `marketCap`) |
| D-07 no semaphore | Provider does no throttling; called once per simulation run |
| D-09 fresh/fetch_failed only | `staleness="fresh"` set literally on the `MarketSlice` constructor; `_fetch_failed_market_slice` sets `"fetch_failed"` on exception |
| D-10 no caching | Every call is a fresh scrape; no cache store |
| D-19 never-raise | `try: … except Exception: return _fetch_failed_market_slice(ticker, _SOURCE)` wraps the full per-ticker body |

## Review Fixes Applied

| Review | Severity | Fix |
|--------|----------|-----|
| Gemini — NaN leakage from pre-earnings `trailingPE` | MEDIUM | `_decimal_or_none` checks `math.isnan(value) or math.isinf(value)` on `float` values and returns `None` — no `Decimal('NaN')` can escape. Verified by `test_decimal_or_none_unit`, `test_nan_trailing_pe_is_guarded_to_none`, `test_inf_fundamentals_are_guarded_to_none`, `test_yfinance_provider_module_guards_nan_inf`. |
| Codex — ticker normalization boundary | MEDIUM | Module docstring makes it explicit: provider passes tickers through to `yf.Ticker(t)` as-is. Upstream callers normalize. No whitespace/case/symbol coercion in this layer. |
| Codex — yfinance version pin | HIGH | Floor set to `>=1.2.2,<2.0` (live-probe-verified floor from 2026-04-18); installed version resolved to 1.3.0 under uv.lock. |
| Codex — Phase 40 over-fetch | MEDIUM | Module docstring's "PHASE 40 CALL PATTERN" section instructs Phase 40 to call exactly one Protocol method per run (recommended `get_prices`) — all three return the same complete slice via `_fetch_batch_shared`, so chaining them would triple network cost for no benefit. |

## Pitfalls Mitigated

| Pitfall | Mitigation | Verified By |
|---------|-----------|-------------|
| 1 — `KeyError('currentTradingPeriod')` from `fast_info.last_price` on delisted tickers | Broad `try/except Exception` wrapping the entire `_fetch_one_sync` body | `test_get_prices_fetch_failed_on_exception` (simulates the KeyError directly) |
| 5 — `Decimal(float)` binary rounding | `_decimal_or_none` uses `Decimal(str(value))`; grep invariant ensures no bare `Decimal(value)` construction | `test_decimal_precision_not_float` (`0.1` -> `Decimal('0.1')`, not 60-digit expansion) |
| 6 — `.info` does sync HTTP | `_fetch_one_sync` accesses `.info` inside the thread body, which runs under `asyncio.to_thread` | Static: grep invariant; runtime: no event-loop block observed in tests |
| 7 — unit tests hitting real network | Every test monkeypatches `alphaswarm.ingestion.yfinance_provider.yf.Ticker`; global `pytest-socket --disable-socket` is the second line of defense | 15 tests pass with --disable-socket active |
| 8 — importlinter source_modules drift | Module entry added to `source_modules` in the same commit the file is created | `tests/invariants/test_importlinter_coverage.py::test_source_modules_covers_every_actual_package` — 3/3 pass |
| 9 — `asyncio.gather(*empty)` footgun | `if not tickers: return {}` guard at the top of `_fetch_batch_shared` | `test_empty_ticker_list_returns_empty_dict` |

## Requirements Satisfied

- **INGEST-01**: Real `YFinanceMarketDataProvider` implements `MarketDataProvider` Protocol with batch-first async signatures; returns `dict[str, MarketSlice]` with `price` (Decimal), `volume` (int), `fundamentals` (Fundamentals sub-model), `source="yfinance"`, `staleness="fresh"` on success / `"fetch_failed"` on exception.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] yfinance has no type stubs / py.typed marker**
- **Found during:** Task 1 (first mypy run against the skeleton)
- **Issue:** `uv run mypy src/alphaswarm/ingestion/yfinance_provider.py` failed with `error: Skipping analyzing "yfinance": module is installed, but missing library stubs or py.typed marker [import-untyped]`. The mypy strict config in `pyproject.toml` treats this as an error.
- **Fix:** Added `# type: ignore[import-untyped]` specifically to the `import yfinance as yf` line. This is the standard mypy-strict escape for stubless third-party libraries — it localizes the ignore to one line, does not weaken type coverage anywhere else in the module, and leaves the rest of the file fully strict-checked.
- **Files modified:** `src/alphaswarm/ingestion/yfinance_provider.py`
- **Commits:** 6dabac0 (Task 1), 670fe77 (Task 2 carries the same pattern)

**2. [Rule 3 - Blocking] Plan acceptance criterion `mypy tests/test_yfinance_provider.py` is not invokable as written**
- **Found during:** Task 3 verification
- **Issue:** The plan's acceptance criterion `uv run mypy tests/test_yfinance_provider.py — exit 0` fails because mypy cannot resolve first-party `alphaswarm.ingestion` imports when given a single test file without package context. The same failure happens on `tests/test_providers.py` (pre-existing project behavior, not introduced by this plan).
- **Fix:** Verified the equivalent project-context invocation `uv run mypy src/alphaswarm/ingestion/ tests/test_yfinance_provider.py` passes (`Success: no issues found in 5 source files`). Documented in the Task 3 commit message so future runners know to use the project-context form.
- **Files modified:** None — this is a verification-methodology clarification, not a source change.
- **Commits:** 5040709 (Task 3 commit message)

**3. [Tooling] ruff import-ordering autofix on `tests/test_yfinance_provider.py`**
- **Found during:** Task 3 verification
- **Issue:** Initial ruff check flagged one I001 import-order/spacing issue on the test file.
- **Fix:** `uv run ruff check tests/test_yfinance_provider.py --fix` auto-resolved to canonical ordering (blank line after `from __future__ import annotations` block). Tests still pass.
- **Files modified:** `tests/test_yfinance_provider.py`
- **Commits:** 5040709 (includes the ruff-fixed form)

No architectural deviations (Rule 4). No scope boundary violations; no out-of-scope fixes.

## How to Verify

```bash
uv run pytest tests/test_yfinance_provider.py -v                              # 15 tests PASSED
uv run pytest tests/test_providers.py tests/test_yfinance_provider.py tests/invariants/ -x -q  # 57 PASSED
uv run mypy src/alphaswarm/ingestion/ tests/test_yfinance_provider.py         # Success: no issues found in 5 source files
uv run ruff check src/alphaswarm/ingestion/yfinance_provider.py tests/test_yfinance_provider.py  # All checks passed!
uv run lint-imports                                                           # Contracts: 1 kept, 0 broken.
uv run python -c "from alphaswarm.ingestion import YFinanceMarketDataProvider; print('ok')"   # ok
uv run python -c "from alphaswarm.ingestion.yfinance_provider import _decimal_or_none; assert _decimal_or_none(float('nan')) is None; print('nan-guard ok')"  # nan-guard ok
```

## Unblocks

- **Plan 38-02** (RSS news provider) — can now extend `__init__.py` with `RSSNewsProvider` alphabetically between `NewsSlice` and `StalenessState` without import collisions, and can safely add `"alphaswarm.ingestion.rss_provider"` to `source_modules` in its own commit.
- **Plan 38-03** (integration tests) — can import `YFinanceMarketDataProvider` and exercise it under `pytest.mark.enable_socket` against real Yahoo.
- **Phase 40** (ContextPacket assembly) — has a real `MarketDataProvider` to wire into `ContextPacket.market`.

## Self-Check: PASSED

- `src/alphaswarm/ingestion/yfinance_provider.py` — FOUND
- `tests/test_yfinance_provider.py` — FOUND
- `.planning/phases/38-market-data-news-providers/38-01-SUMMARY.md` — FOUND (this file)
- Commit 6dabac0 (Task 1) — FOUND in `git log`
- Commit 670fe77 (Task 2) — FOUND in `git log`
- Commit 5040709 (Task 3) — FOUND in `git log`
- `YFinanceMarketDataProvider` importable — verified at runtime
- 15/15 unit tests PASSED
- 57/57 regression suite PASSED (test_providers + test_yfinance_provider + invariants)
- importlinter contract KEPT, coverage invariant green
