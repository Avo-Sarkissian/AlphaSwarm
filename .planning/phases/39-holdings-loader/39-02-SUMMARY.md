---
phase: 39
plan: 02
subsystem: holdings
tags: [holdings, fastapi, route, lifespan, pydantic, decimal, importlinter, tdd]
dependency_graph:
  requires:
    - src/alphaswarm/holdings/loader.py   # HoldingsLoader + HoldingsLoadError (Plan 39-01)
    - src/alphaswarm/holdings/types.py    # Holding + PortfolioSnapshot (Phase 37)
    - src/alphaswarm/config.py            # AppSettings base (Plan 39-02 adds field)
    - src/alphaswarm/web/app.py           # lifespan + create_app (Plan 39-02 extends)
    - tests/invariants/test_importlinter_coverage.py  # _KNOWN_NON_SOURCE whitelist (Phase 37)
  provides:
    - src/alphaswarm/web/routes/holdings.py  # GET /api/holdings + load_portfolio_snapshot
    - tests/integration/test_holdings_route.py  # 14 integration tests
  affects:
    - src/alphaswarm/config.py   # AppSettings.holdings_csv_path field added
    - src/alphaswarm/web/app.py  # lifespan load + router registration added
    - pyproject.toml             # importlinter ignore_imports exemption added (deviation)
tech_stack:
  added:
    - FastAPI APIRouter + HTTPException + Request (route surface)
    - pydantic BaseModel (HoldingOut + HoldingsResponse schemas)
    - asyncio.to_thread (offloads synchronous CSV parsing from event loop)
    - FastAPI TestClient (integration test harness)
  patterns:
    - D-04 whitelist indirection: web/app.py imports helper from web.routes.holdings,
      not from alphaswarm.holdings.* directly (importlinter forbidden contract)
    - Eager startup load: PortfolioSnapshot loaded once at lifespan, cached on app.state
    - Decimal-as-string serialization: str(decimal) never float(decimal) (Pitfall 1)
    - Hermetic TestClient pattern: custom lifespan seeds app.state directly (no CSV I/O)
key_files:
  created:
    - src/alphaswarm/web/routes/holdings.py
    - tests/integration/test_holdings_route.py
  modified:
    - src/alphaswarm/config.py
    - src/alphaswarm/web/app.py
    - pyproject.toml
decisions:
  - D-05: AppSettings.holdings_csv_path: Path = Path("Schwab/holdings.csv") bound to
    ALPHASWARM_HOLDINGS_CSV_PATH via env_prefix="ALPHASWARM_"
  - D-06: response shape = {account_number_hash, as_of, holdings: [{ticker, qty, cost_basis}]};
    Decimal fields as strings; as_of as ISO-8601 with +00:00 suffix
  - D-07: HoldingsLoader.load() called exactly once at lifespan startup via load_portfolio_snapshot,
    stored on app.state.portfolio_snapshot; handler reads only app.state at request time
  - D-08: HoldingsLoadError at startup captured by load_portfolio_snapshot helper (returns None);
    GET /api/holdings returns 503 with locked generic body {detail: {error, message}}; lifespan
    continues and broadcaster starts regardless
  - Deviation: pyproject.toml needs ignore_imports exemption because importlinter as_packages=True
    makes alphaswarm.web.routes.holdings a submodule of the forbidden source alphaswarm.web.routes
metrics:
  duration_minutes: 10
  completed_date: "2026-04-19"
  tasks_completed: 4
  files_changed: 5
requirements_closed: [HOLD-03]
---

# Phase 39 Plan 02: Holdings Route Wiring — SUMMARY

**One-liner:** GET /api/holdings FastAPI route backed by eager-loaded PortfolioSnapshot via asyncio.to_thread, with HoldingOut+HoldingsResponse pydantic schemas, D-04 importlinter indirection, and 14 hermetic TestClient integration tests.

## What Was Built

Four source/config changes and one new test file implementing the HOLD-03 requirement:

- **`src/alphaswarm/config.py`** — Added `holdings_csv_path: Path = Path("Schwab/holdings.csv")` field to `AppSettings` after `governor:`. The existing `env_prefix="ALPHASWARM_"` maps it to env var `ALPHASWARM_HOLDINGS_CSV_PATH`. Added `from pathlib import Path` to stdlib imports.

- **`src/alphaswarm/web/routes/holdings.py`** — New route module (on the D-04 `_KNOWN_NON_SOURCE` whitelist) providing:
  - `HoldingOut(BaseModel)` — `ticker: str`, `qty: str`, `cost_basis: str | None` (Decimal-as-string)
  - `HoldingsResponse(BaseModel)` — `account_number_hash: str`, `as_of: str`, `holdings: list[HoldingOut]`
  - `async def get_holdings(request: Request) -> HoldingsResponse` — reads `request.app.state.portfolio_snapshot`; returns 200 with D-06 shape or 503 with locked generic body `{"detail": {"error": "holdings_unavailable", "message": "..."}}` when snapshot is None (D-08)
  - `def load_portfolio_snapshot(csv_path: Path) -> PortfolioSnapshot | None` — synchronous lifespan helper that calls `HoldingsLoader.load()`, catches `HoldingsLoadError` narrowly, logs server-side, and returns None on failure; the D-04 whitelist indirection layer

- **`src/alphaswarm/web/app.py`** — Two additions:
  - Import: `from alphaswarm.web.routes.holdings import load_portfolio_snapshot, router as holdings_router` (between health and interview, alphabetical)
  - Lifespan: `app.state.portfolio_snapshot = await asyncio.to_thread(load_portfolio_snapshot, settings.holdings_csv_path)` placed after connection_manager assignments, before broadcaster_task (D-07, D-08, CLAUDE.md HC-1)
  - `create_app()`: `app.include_router(holdings_router, prefix="/api")` between interview_router and report_router

- **`pyproject.toml`** — Added `ignore_imports` exemption to the importlinter forbidden contract (see Deviations below).

- **`tests/integration/test_holdings_route.py`** — 14 hermetic TestClient tests under `tests/integration/` (auto-marked with `enable_socket`): 200 happy path, row order, account hash round-trip, Decimal-as-string (qty + cost_basis), cost_basis=None→null, as_of ISO-8601 +00:00, 503 on None snapshot, 503 body is detail-wrapped (Codex MEDIUM regression), 503 no-path-leak (T-39-06), 4 source-invariant grep tests (Pitfall 1 + 7 + asyncio.to_thread + no direct holdings import in web/app.py).

## Decisions Implemented

| Decision | Rationale |
|----------|-----------|
| D-05: AppSettings.holdings_csv_path: Path | pydantic-settings coerces string env to Path; env_prefix maps automatically |
| D-06: Decimal → str serialization | Preserves fractional share precision across JSON; round-trips exactly (Pitfall 1) |
| D-07: Eager lifespan load | CSV parsed once at startup, cached on app.state; handler has zero file I/O |
| D-08: None snapshot → 503 with generic locked body | Raw exception and path logged server-side only; client sees only "holdings_unavailable" inside detail dict |
| asyncio.to_thread: lifespan offload | csv.DictReader + Path.open are blocking I/O; CLAUDE.md Hard Constraint 1 prohibits blocking on the event loop |

## Review Closures

| Review | Closure |
|--------|---------|
| Codex HIGH — importlinter boundary | web/app.py imports only `load_portfolio_snapshot` + `holdings_router` from web.routes.holdings (D-04 whitelist); NEVER imports alphaswarm.holdings.* directly; lint-imports exit 0 verified as HARD GATE after import line added |
| Codex MEDIUM — asyncio.to_thread | `await asyncio.to_thread(load_portfolio_snapshot, settings.holdings_csv_path)` on single line in lifespan; grep invariant test `test_web_app_uses_asyncio_to_thread_for_holdings_load` pins it |
| Codex MEDIUM — 503 body FastAPI wrapping | HTTPException(detail={...}) produces {"detail": {...}} wire body; test `test_get_holdings_503_body_is_detail_wrapped` is the regression pin; test `test_get_holdings_503_when_snapshot_none` reads `r.json()["detail"]["error"]` |

## Pitfalls Mitigated

| Pitfall | Mitigation |
|---------|-----------|
| Pitfall 1: Decimal(float) loses precision | HoldingOut.qty and cost_basis are `str`; serialization uses str(h.qty)/str(h.cost_basis); grep invariant + round-trip test enforce |
| Pitfall 3: Blocking I/O in async handler | Handler reads only request.app.state; no file I/O; HoldingsLoader never called at request time |
| Pitfall 4: importlinter — web.routes.holdings must not be in source_modules | pyproject.toml source_modules unchanged; both invariant tests (covers + does_not_list) stay green |
| Pitfall 7: No Holding field logging | grep invariant `test_route_source_does_not_log_holding_field_values` forbids log.*(qty|ticker|cost_basis) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] importlinter `ignore_imports` required in pyproject.toml**

- **Found during:** Task 2 verification (HARD GATE lint-imports check)
- **Issue:** The plan stated "pyproject.toml receives ZERO edits" because `alphaswarm.web.routes.holdings` is on the `_KNOWN_NON_SOURCE` whitelist in the invariant test. However, the importlinter `forbidden` contract has `as_packages=True` by default, meaning `alphaswarm.web.routes` (listed in `source_modules`) covers ALL its submodules including `alphaswarm.web.routes.holdings`. The invariant test's `_KNOWN_NON_SOURCE` only prevents the invariant test from flagging the module as uncovered — it does NOT configure importlinter to ignore the forbidden import path.
- **Fix:** Added `ignore_imports` to the importlinter contract in `pyproject.toml`:
  ```toml
  ignore_imports = [
      "alphaswarm.web.routes.holdings -> alphaswarm.holdings",
      "alphaswarm.web.routes.holdings -> alphaswarm.holdings.loader",
  ]
  ```
  This is the correct importlinter v2.11 mechanism for exempting a specific whitelisted module from the forbidden rule.
- **Files modified:** `pyproject.toml`
- **Commit:** `ceb5242`

**2. [Rule 1 - Bug] asyncio.to_thread call must be on a single line for grep invariant**

- **Found during:** Task 4 test run — `test_web_app_uses_asyncio_to_thread_for_holdings_load` failed
- **Issue:** Task 3 wrote the to_thread call split across two lines (`asyncio.to_thread(\n        load_portfolio_snapshot, ...`). The plan's acceptance criteria and the test both grep for `asyncio.to_thread(load_portfolio_snapshot,` as a single string.
- **Fix:** Collapsed to a single line with `# noqa: E501` comment.
- **Files modified:** `src/alphaswarm/web/app.py`
- **Commit:** `82950a1`

## Known Stubs

None — GET /api/holdings is fully wired: `load_portfolio_snapshot` reads the real CSV at startup, `app.state.portfolio_snapshot` is a real `PortfolioSnapshot | None`, and the handler serializes it through pydantic. No mock data, no placeholder responses.

## Threat Flags

No new network endpoints, auth paths, or schema changes beyond what the plan's threat model covers. The GET /api/holdings endpoint was the intended new surface; all T-39-08 through T-39-17 mitigations are implemented as specified.

## Self-Check

- [x] `src/alphaswarm/config.py` — modified (holdings_csv_path field + pathlib import)
- [x] `src/alphaswarm/web/routes/holdings.py` — created
- [x] `src/alphaswarm/web/app.py` — modified (import + lifespan + router registration)
- [x] `tests/integration/test_holdings_route.py` — created (14 tests)
- [x] `pyproject.toml` — modified (ignore_imports deviation fix)
- [x] Commit `cf3b86a` — Task 1: AppSettings.holdings_csv_path
- [x] Commit `ceb5242` — Task 2: route module + importlinter fix
- [x] Commit `b579f09` — Task 3: lifespan wiring + router registration
- [x] Commit `82950a1` — Task 4: integration tests + to_thread line fix
- [x] 14 integration tests pass, 0 failures
- [x] 16 invariant tests pass
- [x] mypy clean (src/alphaswarm/config.py, web/routes/holdings.py, web/app.py)
- [x] ruff clean (web/routes/holdings.py; config.py and web/app.py have pre-existing violations not caused by this plan)
- [x] lint-imports exit 0 (1 kept, 0 broken)
- [x] route_registered verified: `/api/holdings` in create_app() routes
- [x] fallback_none_ok verified: load_portfolio_snapshot returns None for missing CSV
- [x] HOLD-03 satisfied

## Self-Check: PASSED
