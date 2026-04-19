# Phase 39: Holdings Loader - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Load `Schwab/holdings.csv` into a `PortfolioSnapshot` with SHA256 account hashing (HOLD-02), expose holdings via `GET /api/holdings` FastAPI endpoint, and wire `web.routes.holdings` into the importlinter whitelist. Phase 39 confirms route-level isolation via the ISOL-07 canary (scaffolded in Phase 37). Full advisory join-point activation is Phase 41.

Holdings data path: CSV → HoldingsLoader → PortfolioSnapshot → REST endpoint only. Holdings never enter the simulation swarm, agent prompts, Neo4j, or WebSocket frames.

</domain>

<decisions>
## Implementation Decisions

### CSV format
- **D-01:** Target file is `Schwab/holdings.csv` — a clean 4-column format (`account, symbol, shares, cost_basis_per_share`) with headers at row 1, no preamble. Two accounts in one file: `individual` and `roth_ira`.
- **D-02:** `Holding.cost_basis` = total position cost computed at parse time: `Decimal(shares) * Decimal(cost_basis_per_share)`. The CSV stores per-share basis; the advisory pipeline needs total position cost for ranking.
- **D-03:** Multi-account file → single merged `PortfolioSnapshot`. All holdings from `individual` and `roth_ira` collapsed into one `holdings` tuple.
- **D-04:** All positions included — no money-market filtering. SWYXX passes through as a `Holding` like any equity.

### CSV path wiring
- **D-05:** CSV path configured via `AppSettings` env var `ALPHASWARM_HOLDINGS_CSV_PATH`. Default: `Schwab/holdings.csv` (relative to project root). Overridable via `.env` file.

### Endpoint response shape
- **D-06:** `GET /api/holdings` returns a full serialized `PortfolioSnapshot`: `account_number_hash`, `as_of` (ISO-8601), and a `holdings` list with `ticker`, `qty` (Decimal-as-string), `cost_basis` (Decimal-as-string). Decimal fields serialized as strings to avoid float precision loss.

### Loading strategy
- **D-07:** Eager load at FastAPI lifespan startup — `HoldingsLoader.load(path)` called once in `lifespan()`, result stored on `app.state.portfolio_snapshot`. `GET /api/holdings` serializes the cached snapshot; no disk I/O per request.
- **D-08:** Missing or malformed CSV → log a structured error, store `None` on `app.state.portfolio_snapshot`. `GET /api/holdings` returns a structured 503 response. No exception propagates to the WebSocket loop (Phase 39 success criterion 4).

### Claude's Discretion
- `as_of` timestamp source: file mtime via `Path.stat().st_mtime` converted to UTC, or `datetime.now(UTC)` at load time — planner decides
- `account_number_hash` derivation: the CSV has no raw Schwab account numbers (account column is `individual`/`roth_ira` labels). Hash a deterministic string from the account labels present (e.g., `sha256_first8("individual|roth_ira")`). HOLD-02 compliance is achieved since no raw account number ever enters the type.
- Whether `HoldingsLoader` is a class with a `load()` classmethod or a standalone function
- 503 response body structure for missing/malformed CSV

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Holdings types (Phase 37 outputs)
- `src/alphaswarm/holdings/types.py` — `Holding` and `PortfolioSnapshot` frozen stdlib dataclasses; `account_number_hash` is pre-hashed; `holdings` is `tuple[Holding, ...]`
- `src/alphaswarm/holdings/__init__.py` — exports `Holding`, `PortfolioSnapshot`

### Hashing
- `src/alphaswarm/security/hashing.py` — `sha256_first8(value: str) -> str`; raises `TypeError` on empty string; use this for `account_number_hash`

### Importlinter contract + coverage
- `pyproject.toml` §[tool.importlinter] — `alphaswarm.web.routes.holdings` is NOT in `source_modules` (pre-whitelisted); creating the module is sufficient — no pyproject.toml edit needed for the route itself
- `tests/invariants/test_importlinter_coverage.py` — `_KNOWN_NON_SOURCE` already contains `alphaswarm.web.routes.holdings`; coverage test will pass automatically when the file is created

### Web app lifespan + router registration pattern
- `src/alphaswarm/web/app.py` — lifespan pattern for eager state init; router registration via `app.include_router()`; add holdings router + `app.state.portfolio_snapshot` here

### Isolation canary
- `tests/invariants/test_holdings_isolation.py` — ISOL-07 canary; Phase 39 confirms route-level isolation (GET /api/holdings doesn't emit holdings into WebSocket, logs, Neo4j, or prompts); full advisory activation is Phase 41

### Requirements
- `.planning/REQUIREMENTS.md` §HOLD-01, §HOLD-02, §HOLD-03 — three acceptance-tracked requirements this phase closes
- `.planning/ROADMAP.md` §"Phase 39: Holdings Loader" — goal, success criteria, plan split

### Source CSV
- `Schwab/holdings.csv` — actual target file; 4 columns: `account, symbol, shares, cost_basis_per_share`; 35 rows; no preamble; mixed `individual`/`roth_ira` accounts

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sha256_first8` (`src/alphaswarm/security/hashing.py`): already exists; documented for Phase 39 HOLD-02 use in its module docstring
- FastAPI lifespan pattern (`src/alphaswarm/web/app.py`): `sim_manager`, `replay_manager`, `connection_manager` all constructed once in `lifespan()` and stored on `app.state`; `app.state.portfolio_snapshot` follows the same pattern
- Router registration (`src/alphaswarm/web/app.py:create_app()`): `app.include_router(holdings_router, prefix="/api")` — one line, mirrors existing routers
- `Holding`, `PortfolioSnapshot` (`src/alphaswarm/holdings/types.py`): frozen stdlib dataclasses with `Decimal` fields; no I/O; construction is pure

### Established Patterns
- `asyncio_mode = "auto"` project-wide — async test functions and fixtures need no decorator
- `pytest-socket --disable-socket` global gate — route integration tests must be under `tests/integration/` for `enable_socket` auto-marker
- Existing route modules (`src/alphaswarm/web/routes/report.py`, `simulation.py`) use `from fastapi import APIRouter, HTTPException, Request` + `from pydantic import BaseModel` for response schema; holdings route follows the same shape
- mypy strict mode — all new code must be fully typed

### Integration Points
- `src/alphaswarm/web/app.py` — add `HoldingsLoader` import + `app.state.portfolio_snapshot = HoldingsLoader.load(path)` in `lifespan()` + register holdings router
- `src/alphaswarm/config.py` — add `holdings_csv_path: Path = Path("Schwab/holdings.csv")` field to `AppSettings`
- `pyproject.toml` — no importlinter changes needed; `alphaswarm.web.routes.holdings` is pre-whitelisted
- `tests/invariants/test_holdings_isolation.py` — Phase 39 does NOT fully activate the advisory join-point assertions; confirms the load+route path doesn't leak

</code_context>

<specifics>
## Specific Ideas

- Architecture invariant: holdings flow only one direction — CSV → loader → REST endpoint. They never enter the simulation path. This is the invariant Phase 39 establishes at the REST layer; Phase 41 enforces it at the advisory join point.
- The CSV has no raw Schwab account numbers (the "Individual-Positions-2026-04-09-154713.csv" raw export has them in the preamble, but `holdings.csv` uses labels). HOLD-02 hashing applies to the label set used as account identifier.
- `cost_basis` is total not per-share — matches how Phase 41 advisory synthesis will rank positions (compare total cost basis against consensus signal magnitude).

</specifics>

<deferred>
## Deferred Ideas

- Loading the raw Schwab position export files (`Individual-Positions-2026-04-09-154713.csv`) — these have preamble rows and many more columns; `holdings.csv` is the designed target for Phase 39
- Hot-reload of CSV without server restart (lazy per-request loading) — deferred; not needed for v6.0
- Per-account breakdown endpoint (separate `PortfolioSnapshot` per account label) — deferred; advisory needs merged view

</deferred>

---

*Phase: 39-holdings-loader*
*Context gathered: 2026-04-18*
