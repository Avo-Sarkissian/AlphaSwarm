---
phase: 37-isolation-foundation-provider-scaffolding
plan: 01
subsystem: types
tags: [pydantic, dataclasses, immutability, decimal, sha256, holdings-isolation, isol-01, isol-02]

requires:
  - phase: 36-report-viewer
    provides: stable v5.0 Web UI codebase baseline for v6.0 Option A isolation work

provides:
  - alphaswarm.holdings.types — Holding and PortfolioSnapshot stdlib frozen dataclasses (ISOL-01)
  - alphaswarm.ingestion.types — ContextPacket, MarketSlice, NewsSlice, Fundamentals pydantic frozen models with extra=forbid (ISOL-02)
  - alphaswarm.security.hashing — sha256_first8 correlation hasher (D-06)
  - pyproject.toml dev deps: import-linter==2.11, pytest-socket==0.7.0, hypothesis==6.152.1
  - 33 unit tests asserting all REVIEW HIGH and REVIEW MEDIUM invariants

affects:
  - 37-02 (provider protocols need ContextPacket, MarketSlice, NewsSlice, StalenessState)
  - 37-03 (PII redaction processor needs sha256_first8 from alphaswarm.security.hashing)
  - 37-04 (importlinter canary needs all six new types for schema assertions)
  - 38-market-data-providers (yfinance provider implements MarketDataProvider protocol returning MarketSlice)
  - 39-holdings-loader (HoldingsLoader produces PortfolioSnapshot, uses sha256_first8 for HOLD-02)
  - 41-advisory-pipeline (join point between holdings and swarm — types must be stable)

tech-stack:
  added:
    - import-linter==2.11 (static import boundary enforcement, Plan 04)
    - pytest-socket==0.7.0 (global network gate, Plan 03)
    - hypothesis==6.152.1 (PII redaction fuzz tests, Plan 03)
  patterns:
    - pydantic v2 ConfigDict(frozen=True, extra="forbid") for swarm-side types (ISOL-02)
    - stdlib @dataclasses.dataclass(frozen=True) for holdings-side types (ISOL-01)
    - tuple[...] for ALL collection fields (not list[...]) to prevent shallow-immutability bypass
    - nested frozen BaseModel sub-models instead of dict[str, float] for deep immutability
    - Decimal (not float) for all financial quantities
    - sha256_first8 in alphaswarm/security/ (not alphaswarm/holdings/) so importlinter-restricted modules can still access it

key-files:
  created:
    - src/alphaswarm/holdings/__init__.py
    - src/alphaswarm/holdings/types.py
    - src/alphaswarm/ingestion/__init__.py
    - src/alphaswarm/ingestion/types.py
    - src/alphaswarm/security/__init__.py
    - src/alphaswarm/security/hashing.py
    - tests/test_holdings_types.py
    - tests/test_ingestion_types.py
    - tests/test_security_hashing.py
  modified:
    - pyproject.toml (added 3 dev deps)
    - uv.lock (updated lockfile)

key-decisions:
  - "D-06 implemented: sha256_first8 placed in alphaswarm/security/hashing.py (not alphaswarm/holdings/) so modules forbidden from touching holdings can still access the hasher"
  - "REVIEW HIGH closed: all collection fields use tuple[...] throughout — frozen=True alone does not deep-freeze list contents"
  - "REVIEW HIGH closed: MarketSlice.fundamentals is nested frozen Fundamentals sub-model, not dict[str, float] — dict.update() bypasses frozen semantics"
  - "REVIEW MEDIUM closed: MarketSlice.price is Decimal (not float) for binary-float rounding protection"
  - "REVIEW MEDIUM closed: StalenessState = Literal['fresh', 'stale', 'fetch_failed'] typed alias exported from alphaswarm.ingestion"

patterns-established:
  - "Isolation boundary: holdings-side types use stdlib only (zero pydantic/httpx/yfinance); swarm-side types use pydantic v2 with extra=forbid"
  - "Deep immutability: tuple collections + nested frozen sub-models (not list/dict) on all frozen types"
  - "Security hasher location: shared utilities go in alphaswarm/security/ to avoid importlinter contract violations by importers of those utilities"

requirements-completed: [ISOL-01, ISOL-02]

duration: 25min
completed: 2026-04-18
---

# Phase 37 Plan 01: Frozen Type Boundaries + Dev Dependencies Summary

**Frozen stdlib dataclasses (Holding, PortfolioSnapshot) and pydantic v2 frozen+forbid models (ContextPacket, MarketSlice, NewsSlice, Fundamentals) with deep immutability via tuple-only collections and nested sub-models, plus sha256_first8 hasher and three new dev deps**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-18T16:06:00Z
- **Completed:** 2026-04-18T16:31:05Z
- **Tasks:** 2 (Task 1: scaffold + deps, Task 2: unit tests)
- **Files modified:** 10 new files, 2 modified (pyproject.toml, uv.lock)

## Accomplishments

- Created `alphaswarm.holdings` subpackage with `Holding` and `PortfolioSnapshot` stdlib frozen dataclasses — ISOL-01 boundary established
- Created `alphaswarm.ingestion` subpackage with `ContextPacket`, `MarketSlice`, `NewsSlice`, `Fundamentals` pydantic v2 frozen models with `extra="forbid"` — ISOL-02 boundary established
- Created `alphaswarm.security` subpackage with `sha256_first8` hasher — placed outside holdings so D-06 consumers (Plan 03 PII processor, Phase 39 HoldingsLoader) can import it without triggering importlinter violations
- Added 3 pinned dev dependencies: `import-linter==2.11`, `pytest-socket==0.7.0`, `hypothesis==6.152.1`
- Wrote 33 unit tests across 3 test files covering all frozenness, extra=forbid, tuple-only collection, zero-holdings-field, Decimal precision, StalenessState literal, and sha256_first8 invariants
- Closed REVIEW HIGH #1 (shallow immutability): every collection field is `tuple[...]`; `Fundamentals` is a nested frozen `BaseModel` not `dict[str, float]`
- Closed REVIEW MEDIUM: `MarketSlice.price` is `Decimal | None`; `StalenessState` is a `Literal[...]` typed alias

## Files Created/Modified

- `src/alphaswarm/holdings/__init__.py` — subpackage marker, re-exports Holding, PortfolioSnapshot
- `src/alphaswarm/holdings/types.py` — ISOL-01: frozen dataclasses with tuple holdings, Decimal qty/cost_basis
- `src/alphaswarm/ingestion/__init__.py` — subpackage marker, re-exports all 5 swarm-side types
- `src/alphaswarm/ingestion/types.py` — ISOL-02: pydantic frozen+forbid models, tuple collections, nested Fundamentals, Decimal price, StalenessState literal
- `src/alphaswarm/security/__init__.py` — subpackage marker, re-exports sha256_first8
- `src/alphaswarm/security/hashing.py` — sha256_first8 with TypeError guard on empty/None inputs (D-06, Pitfall 7)
- `tests/test_holdings_types.py` — 7 tests: frozenness, Decimal fields, tuple holdings, stdlib-only import guard
- `tests/test_ingestion_types.py` — 20 tests: extra=forbid, frozen, zero sensitive fields, tuple collections, nested Fundamentals immutability, Decimal price, StalenessState literal
- `tests/test_security_hashing.py` — 6 tests: 8-hex-char output, determinism, distinct outputs, empty/None/non-str rejection
- `pyproject.toml` — added import-linter==2.11, pytest-socket==0.7.0, hypothesis==6.152.1 to dev group

## Decisions Made

- **sha256_first8 placed in alphaswarm/security/** — D-06 specifies this is a shared utility; if placed in alphaswarm/holdings/ then the PII redaction processor (Plan 03) and other modules not permitted to import holdings would be blocked from using it. Separate security subpackage is the correct location.
- **REVIEW HIGH: tuple collections throughout** — `frozen=True` on pydantic models and frozen dataclasses prevents attribute reassignment but does NOT prevent in-place mutation of list contents (e.g., `model.market.append(...)` calls the list's own method). Tuple fields close this surface.
- **REVIEW HIGH: nested Fundamentals BaseModel** — `dict.update()` and subscript assignment bypass `frozen=True` on the enclosing model. Named Decimal fields on a nested frozen `BaseModel` produce a truly immutable value graph.

## Deviations from Plan

None — plan executed exactly as written. All REVIEW HIGH and REVIEW MEDIUM concerns from 37-REVIEWS.md were already incorporated into the plan spec before execution.

## Known Stubs

None — this plan creates pure type scaffolding with no data paths, provider implementations, or UI. Types are fully wired and functional.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. All new surface is type construction (process-internal).

## Verification

```
uv run pytest tests/test_holdings_types.py tests/test_ingestion_types.py tests/test_security_hashing.py -v
# 33 passed in 0.10s

uv run mypy src/alphaswarm/holdings/ src/alphaswarm/ingestion/ src/alphaswarm/security/
# Success: no issues found in 6 source files

uv run ruff check src/alphaswarm/holdings/ src/alphaswarm/ingestion/ src/alphaswarm/security/ tests/test_holdings_types.py tests/test_ingestion_types.py tests/test_security_hashing.py
# All checks passed!
```

## Next Phase Readiness

- Plan 37-02 (provider protocols) unblocked: `ContextPacket`, `MarketSlice`, `NewsSlice`, `StalenessState` ready for Protocol return types
- Plan 37-03 (PII redaction) unblocked: `sha256_first8` available at `alphaswarm.security.hashing`
- Plan 37-04 (importlinter + canary) unblocked: all six types available for schema assertions in `tests/invariants/`

---
*Phase: 37-isolation-foundation-provider-scaffolding*
*Completed: 2026-04-18*
