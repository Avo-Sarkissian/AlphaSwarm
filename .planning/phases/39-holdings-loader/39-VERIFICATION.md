---
phase: 39-holdings-loader
verified: 2026-04-19T16:25:12Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 39: Holdings Loader Verification Report

**Phase Goal:** Implement a HoldingsLoader that reads a Schwab CSV export and exposes a GET /api/holdings endpoint backed by an eager-loaded PortfolioSnapshot.
**Verified:** 2026-04-19T16:25:12Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | HOLD-01: HoldingsLoader.load(path) reads Schwab CSV and returns a PortfolioSnapshot with Holding tuples | VERIFIED | `loader.py` fully implemented; `uv run python` confirms 34 holdings from real CSV; 22 unit tests pass including happy-path and edge cases |
| 2 | HOLD-02: Raw account labels hashed via sha256_first8 before storage — raw strings never appear on the type | VERIFIED | `loader.py` line 143: `sha256_first8("\|".join(sorted(account_labels)))` — `account_labels` never stored; `test_account_label_not_in_hash_output` passes; `test_account_hash` verifies exact digest |
| 3 | HOLD-03: GET /api/holdings returns 200 with serialized HoldingsResponse when snapshot is non-None | VERIFIED | `web/routes/holdings.py` implements `get_holdings`; 14 integration tests all pass including `test_get_holdings_200` |
| 4 | Eager startup load: PortfolioSnapshot loaded once at lifespan via asyncio.to_thread, never at request time | VERIFIED | `web/app.py` line 78: `await asyncio.to_thread(load_portfolio_snapshot, settings.holdings_csv_path)` — grep invariant test `test_web_app_uses_asyncio_to_thread_for_holdings_load` passes |
| 5 | HoldingsLoadError on failure never escapes lifespan — 503 returned when snapshot is None | VERIFIED | `load_portfolio_snapshot` narrows `except HoldingsLoadError` and returns None; `test_get_holdings_503_when_snapshot_none` passes; 503 body locked to generic shape — no path leak (T-39-06) |
| 6 | AppSettings.holdings_csv_path field bound to ALPHASWARM_HOLDINGS_CSV_PATH env var | VERIFIED | `config.py` line 95: `holdings_csv_path: Path = Path("Schwab/holdings.csv")` with existing `env_prefix="ALPHASWARM_"` |
| 7 | importlinter forbidden contract remains unbroken — only web.routes.holdings may import alphaswarm.holdings | VERIFIED | `uv run lint-imports` exits 0: 1 kept, 0 broken; `ignore_imports` exemption in pyproject.toml covers the whitelisted route module; app.py imports only from web.routes.holdings |
| 8 | Decimal precision: Decimal(string) used throughout — never Decimal(float) | VERIFIED | `loader.py` lines 124–125 use `Decimal(row["shares"])`, `Decimal(row["cost_basis_per_share"])`; grep shows no `float(row[`; `test_fractional_shares_preserve_decimal_precision` and source grep invariant tests both pass |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/holdings/loader.py` | HoldingsLoader class with classmethod load(path) and HoldingsLoadError domain exception | VERIFIED | 162 lines; fully implemented load(); REQUIRED_COLUMNS, BOM-safe open, empty-row guard, sha256_first8 hash, stat-based as_of |
| `src/alphaswarm/holdings/__init__.py` | Re-exports HoldingsLoader + HoldingsLoadError alongside Holding + PortfolioSnapshot | VERIFIED | `__all__ = ["Holding", "HoldingsLoadError", "HoldingsLoader", "PortfolioSnapshot"]` — alphabetically sorted |
| `tests/test_holdings_loader.py` | Unit tests for HoldingsLoader covering HOLD-01 + HOLD-02 behaviors; hermetic tmp_path fixtures | VERIFIED | 22 tests; all pass; no dependency on real CSV (docstring references only) |
| `src/alphaswarm/web/routes/holdings.py` | GET /api/holdings FastAPI route + HoldingsResponse + HoldingOut + load_portfolio_snapshot helper | VERIFIED | 161 lines; fully wired; router exported; Decimal-as-string serialization; 503 generic body |
| `src/alphaswarm/config.py` | AppSettings.holdings_csv_path field bound to ALPHASWARM_HOLDINGS_CSV_PATH | VERIFIED | Line 95 added; `from pathlib import Path` in stdlib imports |
| `src/alphaswarm/web/app.py` | Lifespan integration: asyncio.to_thread load + router registration | VERIFIED | Line 78 lifespan call; line 117 `app.include_router(holdings_router, prefix="/api")` |
| `tests/integration/test_holdings_route.py` | TestClient integration coverage for GET /api/holdings | VERIFIED | 14 tests; all pass; hermetic seeded lifespan; no CSV I/O |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/alphaswarm/holdings/loader.py` | `src/alphaswarm/holdings/types.py` | `from alphaswarm.holdings.types import Holding, PortfolioSnapshot` | WIRED | Line 37; used in load() return construction |
| `src/alphaswarm/holdings/loader.py` | `src/alphaswarm/security/hashing.py` | `from alphaswarm.security.hashing import sha256_first8` | WIRED | Line 38; called at line 143 for account_number_hash |
| `src/alphaswarm/web/app.py` | `src/alphaswarm/web/routes/holdings.py` | `from alphaswarm.web.routes.holdings import load_portfolio_snapshot, router as holdings_router` | WIRED | Line 20; both symbols used — load_portfolio_snapshot at line 78, holdings_router at line 117 |
| `src/alphaswarm/web/routes/holdings.py` | `src/alphaswarm/holdings/loader.py` | `from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError` | WIRED | Line 46; HoldingsLoader.load called in load_portfolio_snapshot; HoldingsLoadError caught |
| `src/alphaswarm/web/routes/holdings.py` | `src/alphaswarm/holdings/types.py` | `from alphaswarm.holdings import PortfolioSnapshot` | WIRED | Line 45; used in get_holdings type annotation and load_portfolio_snapshot return type |
| `src/alphaswarm/web/app.py` | `asyncio.to_thread` | `await asyncio.to_thread(load_portfolio_snapshot, settings.holdings_csv_path)` | WIRED | Line 78; single-line form (noqa: E501); grep invariant test pins it |
| `src/alphaswarm/config.py` | env var | pydantic-settings env_prefix maps holdings_csv_path → ALPHASWARM_HOLDINGS_CSV_PATH | WIRED | Line 95; existing env_prefix="ALPHASWARM_" applies automatically |
| `tests/integration/test_holdings_route.py` | `src/alphaswarm/web/routes/holdings.py` | FastAPI TestClient calling GET /api/holdings | WIRED | Line 94: `client.get("/api/holdings")` across 14 test functions |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `web/routes/holdings.py::get_holdings` | `snapshot` (PortfolioSnapshot) | `request.app.state.portfolio_snapshot` set at lifespan by `asyncio.to_thread(load_portfolio_snapshot, ...)` which calls `HoldingsLoader.load(csv_path)` reading real Schwab CSV via `csv.DictReader` | Yes — `uv run python` confirms 34 holdings from real CSV; `log.info("holdings_loaded", count=34)` emitted | FLOWING |
| `web/routes/holdings.py::HoldingOut` serialization | `h.ticker`, `h.qty`, `h.cost_basis` | Populated from Holding dataclass instances constructed by loader from CSV rows; qty from `Decimal(row["shares"])`; cost_basis from `qty * cost_per_share` | Yes — round-trip verified by `test_get_holdings_qty_is_string_not_float` and `test_get_holdings_cost_basis_is_string_not_float` | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| HoldingsLoader.load reads real CSV → 34 holdings, correct hash, correct first holding cost_basis | `uv run python -c "...assert len(snap.holdings) == 34 and snap.account_number_hash == sha256_first8('individual\|roth_ira') and snap.holdings[0].ticker == 'AAPL' and snap.holdings[0].cost_basis == Decimal('101.3071') * Decimal('165.5365')"` | `ok` printed | PASS |
| 22 unit tests all pass | `uv run pytest tests/test_holdings_loader.py -v` | 22 passed in 0.08s | PASS |
| 14 integration tests all pass | `uv run pytest tests/integration/test_holdings_route.py -v` | 14 passed in 0.54s | PASS |
| importlinter contract unbroken | `uv run lint-imports` | 1 kept, 0 broken | PASS |
| 16 invariant tests pass (importlinter coverage + holdings isolation canary) | `uv run pytest tests/invariants/ -x -q` | 16 passed in 0.33s | PASS |
| mypy clean on loader.py | `uv run mypy src/alphaswarm/holdings/loader.py` | Success: no issues found in 1 source file | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| HOLD-01 | 39-01 | HoldingsLoader.load(path) reads Schwab CSV and returns PortfolioSnapshot with Holding tuples | SATISFIED | `loader.py` fully implemented; real CSV produces 34 holdings; 22 unit tests cover all behaviors including edge cases (BOM, empty body, same-ticker multi-account, malformed CSV) |
| HOLD-02 | 39-01 | Raw account numbers hashed via sha256_first8 before storage in PortfolioSnapshot | SATISFIED | `loader.py` line 143; `test_account_hash`, `test_account_hash_is_sort_order_stable`, `test_account_label_not_in_hash_output` all pass |
| HOLD-03 | 39-02 | GET /api/holdings REST endpoint served by alphaswarm.web.routes.holdings (the only web module permitted by importlinter to import alphaswarm.holdings) | SATISFIED | `web/routes/holdings.py` implements the route; 14 integration tests pass; importlinter contract enforced via `ignore_imports` exemption; app.py D-04 indirection confirmed by grep and invariant test |

### Anti-Patterns Found

None. Scan of `loader.py`, `web/routes/holdings.py`, `config.py`, and `web/app.py` produced:
- Zero TODO/FIXME/PLACEHOLDER comments
- Zero NotImplementedError occurrences (skeleton replaced in Task 2)
- Zero Decimal(float) patterns
- Zero raw Holding field logging (ticker/qty/cost_basis in log calls)
- Zero hardcoded empty returns at request time

One documented deviation in Plan 02: `pyproject.toml` required `ignore_imports` to be added because importlinter's `as_packages=True` caused `alphaswarm.web.routes.holdings` to inherit the forbidden contract from its parent package. This was discovered at the HARD GATE verification step and fixed before further code was written. The final state (`lint-imports` exits 0) is correct.

### Human Verification Required

None.

All behaviors are verifiable programmatically:
- CSV parsing correctness is verified by running the loader against the real Schwab CSV
- Decimal precision is verified by string comparison of Decimal values
- Hash correctness is verified by comparing against the sha256_first8 helper directly
- Route serialization is verified by TestClient integration tests
- importlinter isolation is verified by `uv run lint-imports`
- No visual, real-time, or external service behaviors are in scope for Phase 39

### Gaps Summary

No gaps. All 8 must-have truths verified, all 7 artifacts exist and are substantive and wired, all key links are active, all 3 requirement IDs satisfied, all test suites pass, no anti-patterns, no human verification items.

The pyproject.toml deviation (adding `ignore_imports`) was an auto-corrected plan deviation discovered at the HARD GATE step — the final codebase state is correct and `lint-imports` exits 0.

---

_Verified: 2026-04-19T16:25:12Z_
_Verifier: Claude (gsd-verifier)_
