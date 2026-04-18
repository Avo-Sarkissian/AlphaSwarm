---
phase: 37
plan: 02
subsystem: ingestion
tags: [typing-protocol, async, batch-first, fakes, isol-05, staleness, never-raise]

requires:
  - phase: 37-plan-01
    provides: MarketSlice, NewsSlice, StalenessState, Fundamentals, ContextPacket frozen types

provides:
  - alphaswarm.ingestion.providers — MarketDataProvider/NewsProvider Protocols + FakeMarketDataProvider/FakeNewsProvider test fakes
  - ingestion __init__.py extended to re-export all 4 provider symbols alongside types

affects:
  - 37-04 (importlinter canary needs FakeMarketDataProvider/FakeNewsProvider for sentinel ContextPacket)
  - 38-market-data-providers (yfinance/RSS real providers implement against these Protocols)

tech-stack:
  added: []
  patterns:
    - typing.Protocol (not ABC) for structural subtyping — no @runtime_checkable (Pitfall 8)
    - batch-first async signatures: list[str] -> dict[str, Slice] (D-17/D-18)
    - StalenessState typed Literal annotation on module-level _FETCH_FAILED constant
    - fixture_source callback wrapped in try/except -> fetch_failed slice (D-19 never-raise)
    - Pure in-memory dict lookup — zero network imports, zero asyncio.sleep (Pitfall 5)

key-files:
  created:
    - src/alphaswarm/ingestion/providers.py
    - tests/test_providers.py
  modified:
    - src/alphaswarm/ingestion/__init__.py

key-decisions:
  - "D-17 implemented: two Protocols only — MarketDataProvider + NewsProvider; no per-query-type splits"
  - "D-18 implemented: batch-first async signatures — list[str] -> dict[str, Slice] for all methods"
  - "D-19 implemented: providers never raise — unknown keys, empty lists, duplicate tickers, and fixture_source exceptions all return fetch_failed slices"
  - "D-20 implemented: Fakes live in providers.py alongside Protocols so Phase 38 is test-first from day one"
  - "REVIEW MEDIUM closed (Gemini/Codex async-explicit): all Protocol+Fake methods are explicitly async def; grep-verified and inspect.iscoroutinefunction runtime-verified"
  - "REVIEW MEDIUM closed (Codex staleness typed literal): _FETCH_FAILED: StalenessState = 'fetch_failed' — typed annotation prevents unconstrained string drift"
  - "REVIEW MEDIUM closed (Codex never-raise coverage): 4 test paths added — empty list, duplicate tickers, fixture_source exception, unknown key"

metrics:
  duration: ~5min
  completed: "2026-04-18"
  tasks: 2
  files_created: 2
  files_modified: 1
---

# Phase 37 Plan 02: Ingestion Provider Protocols + In-Memory Fakes Summary

**Two `typing.Protocol` classes (`MarketDataProvider`, `NewsProvider`) with batch-first `async def` signatures, StalenessState-typed failure slices, and fixture-driven in-memory fakes with full never-raise coverage (unknown/empty/duplicate/exception paths)**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-18T16:34:58Z
- **Completed:** 2026-04-18T16:40:00Z
- **Tasks:** 2 (Task 1: providers.py + __init__.py, Task 2: test_providers.py)
- **Files created:** 2 new, 1 modified

## Accomplishments

- Created `src/alphaswarm/ingestion/providers.py` with two `typing.Protocol` classes and two in-memory fakes implementing ISOL-05
- `MarketDataProvider(Protocol)` defines `async def get_prices`, `async def get_fundamentals`, `async def get_volume` — all batch-first `list[str] -> dict[str, MarketSlice]`
- `NewsProvider(Protocol)` defines `async def get_headlines(entities, *, max_age_hours=72) -> dict[str, NewsSlice]`
- `FakeMarketDataProvider` — fixture-dict + optional `fixture_source` callback; exceptions in callback become `fetch_failed` slices (D-19); supports `SNTL_CANARY_TICKER` sentinel
- `FakeNewsProvider` — fixture-dict; unknown entities return `fetch_failed` slices
- Updated `src/alphaswarm/ingestion/__init__.py` to re-export all 4 provider symbols alongside existing types (now exports 9 names total including `Fundamentals`)
- Wrote 26 unit tests covering structural conformance, async-signature enforcement, fetch_failed paths (unknown/empty/duplicate/exception), StalenessState typed-literal, sentinel ticker, and 4 module-level meta-tests
- Closed all 3 REVIEW MEDIUM concerns from cross-AI review (Gemini/Codex)

## Files Created/Modified

- `src/alphaswarm/ingestion/providers.py` — ISOL-05: Protocol definitions + FakeMarketDataProvider/FakeNewsProvider; `_FETCH_FAILED: StalenessState = "fetch_failed"` typed constant; no network imports; no `asyncio.sleep`
- `tests/test_providers.py` — 26 tests: structural conformance (mypy probe functions), async-signature (inspect.iscoroutinefunction), fetch_failed (4 paths), StalenessState literal set, sentinel ticker, module meta-tests
- `src/alphaswarm/ingestion/__init__.py` — extended with 4 provider re-exports; `__all__` lists 9 names

## Decisions Made

- **No `@runtime_checkable`:** mypy structural checking is sufficient; `isinstance(obj, Protocol)` at runtime is costly and not needed (Pitfall 8). Asserted by `test_providers_module_has_no_runtime_checkable`.
- **`fixture_source` exception path:** The D-19 "never raise" contract must hold even for programmer-error fixture callbacks. Wrapped in `try/except Exception` with `# noqa: BLE001` — deliberate broad catch per the contract spec.
- **Docstring wording:** Removed `@runtime_checkable` literal from module docstring to prevent false positive in meta-test `test_providers_module_has_no_runtime_checkable` (which does a simple `in` string check).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring contained @runtime_checkable literal triggering meta-test false positive**
- **Found during:** Task 1 GREEN phase (first test run)
- **Issue:** Module docstring contained `No @runtime_checkable — mypy strict is sufficient` — the meta-test `test_providers_module_has_no_runtime_checkable` uses a simple `in` string check, so the docstring text triggered a false failure
- **Fix:** Rewrote docstring phrase to `No runtime_checkable decorator — mypy strict is sufficient`
- **Files modified:** `src/alphaswarm/ingestion/providers.py`
- **Commit:** bc46181

## Known Stubs

None — all Protocol methods and Fake implementations are fully functional. No placeholder return paths.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. The fakes are process-internal; `alphaswarm.ingestion.__init__` re-exports them (T-37-11 risk accepted per plan threat register).

## Verification

```
uv run pytest tests/test_providers.py -v
# 26 passed in 0.08s

uv run mypy src/alphaswarm/ingestion/providers.py tests/test_providers.py
# Success: no issues found in 2 source files

uv run python -c "from alphaswarm.ingestion import MarketDataProvider, NewsProvider, FakeMarketDataProvider, FakeNewsProvider, StalenessState, Fundamentals; print('ok')"
# ok

uv run python -c "import inspect; from alphaswarm.ingestion import FakeMarketDataProvider, FakeNewsProvider; fm=FakeMarketDataProvider(); fn=FakeNewsProvider(); assert all(inspect.iscoroutinefunction(m) for m in (fm.get_prices, fm.get_fundamentals, fm.get_volume, fn.get_headlines)); print('async ok')"
# async ok
```

## Self-Check: PASSED

- `src/alphaswarm/ingestion/providers.py` — FOUND
- `tests/test_providers.py` — FOUND
- `src/alphaswarm/ingestion/__init__.py` — FOUND (modified)
- Commit `0d4bb93` (test RED) — FOUND
- Commit `bc46181` (feat GREEN) — FOUND

## Next Phase Readiness

- Plan 37-03 (PII redaction) unblocked: provider Protocols stable; no dependency on providers.py
- Plan 37-04 (importlinter canary) unblocked: `FakeMarketDataProvider` + `FakeNewsProvider` available for sentinel `ContextPacket` construction
- Phase 38 (real market data providers) unblocked: `MarketDataProvider` / `NewsProvider` Protocols define the typed contract; `FakeMarketDataProvider` provides sentinel canary support

---
*Phase: 37-isolation-foundation-provider-scaffolding*
*Completed: 2026-04-18*
