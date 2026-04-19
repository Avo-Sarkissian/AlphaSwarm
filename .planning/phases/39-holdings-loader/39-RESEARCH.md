# Phase 39: Holdings Loader - Research

**Researched:** 2026-04-18
**Domain:** Python CSV parsing, FastAPI REST endpoint, stdlib dataclasses, importlinter wiring
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Target file is `Schwab/holdings.csv` — 4-column format (`account, symbol, shares, cost_basis_per_share`), headers at row 1, no preamble. Two accounts: `individual` and `roth_ira`.

**D-02:** `Holding.cost_basis` = total position cost computed at parse time: `Decimal(shares) * Decimal(cost_basis_per_share)`. CSV stores per-share basis; total is needed for advisory ranking.

**D-03:** Multi-account file → single merged `PortfolioSnapshot`. All holdings from both accounts collapsed into one `holdings` tuple.

**D-04:** All positions included. SWYXX money-market passes through as a `Holding` like any equity.

**D-05:** CSV path configured via `AppSettings` env var `ALPHASWARM_HOLDINGS_CSV_PATH`. Default: `Schwab/holdings.csv`. Overridable via `.env` file.

**D-06:** `GET /api/holdings` returns a full serialized `PortfolioSnapshot`: `account_number_hash`, `as_of` (ISO-8601), `holdings` list with `ticker`, `qty` (Decimal-as-string), `cost_basis` (Decimal-as-string).

**D-07:** Eager load at FastAPI lifespan startup — `HoldingsLoader.load(path)` called once in `lifespan()`, result stored on `app.state.portfolio_snapshot`. GET serializes cached snapshot; no disk I/O per request.

**D-08:** Missing or malformed CSV → log structured error, store `None` on `app.state.portfolio_snapshot`. GET returns structured 503. No exception propagates to the WebSocket loop.

### Claude's Discretion

- `as_of` timestamp source: file mtime via `Path.stat().st_mtime` converted to UTC, or `datetime.now(UTC)` at load time
- `account_number_hash` derivation: hash a deterministic string from the account labels present (e.g., `sha256_first8("individual|roth_ira")`)
- Whether `HoldingsLoader` is a class with a `load()` classmethod or a standalone function
- 503 response body structure for missing/malformed CSV

### Deferred Ideas (OUT OF SCOPE)

- Loading the raw Schwab position export files (`Individual-Positions-2026-04-09-154713.csv`) — these have preamble rows and many more columns
- Hot-reload of CSV without server restart
- Per-account breakdown endpoint
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HOLD-01 | `HoldingsLoader.load(path)` reads Schwab CSV and returns `PortfolioSnapshot` with `Holding` tuples | stdlib `csv.DictReader` on verified CSV shape; `Decimal` multiply for cost_basis |
| HOLD-02 | Raw account numbers hashed via `sha256_first8` before storage in `PortfolioSnapshot` | `sha256_first8` already implemented and tested; CSV uses label strings not raw Schwab numbers |
| HOLD-03 | `GET /api/holdings` REST endpoint served by `alphaswarm.web.routes.holdings` (only permitted importer) | importlinter contract already enforces this; route file doesn't yet exist |
</phase_requirements>

---

## Summary

Phase 39 is a focused three-deliverable phase: a CSV loader, a REST endpoint, and confirmation that the importlinter isolation invariant holds at the route level. The domain is well-understood (Python stdlib CSV parsing, FastAPI, pydantic-settings) with no external network calls, no async I/O, and no new libraries required. Everything needed exists in the codebase already.

The CSV shape is known and simple: 35 data rows, 4 columns, no preamble, two account labels. `HoldingsLoader` reads it once at server startup and stores the result on `app.state`. The GET endpoint serializes the cached snapshot using Decimal-as-string to avoid float precision loss. When the file is missing or malformed, a 503 is returned — the WebSocket loop is never disrupted.

The isolation invariant (ISOL-07 canary) is already scaffolded from Phase 37 and trivially passes at Phase 39 because the REST handler only reads and serializes the cached snapshot — it never touches simulation, Neo4j, WebSocket broadcaster, or agent prompts.

**Primary recommendation:** Implement `HoldingsLoader` as a class with a `load()` classmethod, derive `account_number_hash` from sorted account labels joined with `|`, and use `Path.stat().st_mtime` for `as_of`. This keeps the loader pure (no I/O beyond the one CSV read) and deterministic.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `csv` (stdlib) | Python 3.11 | CSV parsing via `DictReader` | Zero deps; handles quoted fields; project uses stdlib types for holdings (ISOL-01) |
| `decimal` (stdlib) | Python 3.11 | Lossless numeric arithmetic | `Holding.qty` and `Holding.cost_basis` are `Decimal`; never float |
| `pathlib` (stdlib) | Python 3.11 | File path handling and stat | Already used throughout codebase; `Path.stat().st_mtime` for `as_of` |
| `datetime` (stdlib) | Python 3.11 | UTC timestamp for `as_of` | `PortfolioSnapshot.as_of: datetime` field type |
| `fastapi` | existing | APIRouter, HTTPException, Request, status | Already installed; matches route pattern in `report.py` |
| `pydantic` | existing | `BaseModel` for response schema | Already used in all route modules |
| `pydantic-settings` | existing | `AppSettings` env var for CSV path | `AppSettings` already uses `BaseSettings` with `ALPHASWARM_` prefix |
| `structlog` | existing | Structured error logging | CLAUDE.md mandates structlog; `log = structlog.get_logger(component=...)` |

[VERIFIED: codebase grep — all libraries already installed and used]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sha256_first8` (internal) | Phase 37 | Hash account label string to `account_number_hash` | HOLD-02: called once at parse time before `PortfolioSnapshot` is constructed |

[VERIFIED: `src/alphaswarm/security/hashing.py` read directly]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `csv.DictReader` | `pandas.read_csv` | pandas is not installed; adds ~50MB dependency for 35 rows; ruled out |
| `csv.DictReader` | `aiofiles` + async CSV read | Async CSV read is complex with no gain; load happens once at lifespan startup, not in a hot path |
| `Path.stat().st_mtime` for `as_of` | `datetime.now(UTC)` | `st_mtime` is more meaningful (reflects when the portfolio data was last updated); either is valid per D discretion |

**Installation:** No new packages needed. All required libraries are stdlib or already installed.

---

## Architecture Patterns

### Recommended Project Structure

```
src/alphaswarm/
└── holdings/
    ├── __init__.py          # existing — exports Holding, PortfolioSnapshot
    ├── types.py             # existing — frozen dataclasses
    └── loader.py            # NEW — HoldingsLoader class

src/alphaswarm/web/routes/
└── holdings.py              # NEW — GET /api/holdings route

src/alphaswarm/config.py     # EDIT — add holdings_csv_path field to AppSettings
src/alphaswarm/web/app.py    # EDIT — import loader + register router + lifespan wiring

tests/
├── test_holdings_loader.py  # NEW — unit tests for HoldingsLoader
└── integration/
    └── test_holdings_route.py  # NEW — integration test for GET /api/holdings
```

### Pattern 1: HoldingsLoader as a Class with a `load()` Classmethod

**What:** `HoldingsLoader` is a stateless class whose single public method is `load(path: Path) -> PortfolioSnapshot`. It raises `HoldingsLoadError` (a domain exception) on parse failure; the lifespan catches this and stores `None`.

**When to use:** Classmethods suit stateless factory operations; a class form allows easy mocking in tests and is consistent with potential future constructor arguments (e.g., encoding, delimiter).

**Example:**
```python
# src/alphaswarm/holdings/loader.py
from __future__ import annotations

import csv
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog

from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.security.hashing import sha256_first8

log = structlog.get_logger(component="holdings.loader")

REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"account", "symbol", "shares", "cost_basis_per_share"}
)


class HoldingsLoadError(Exception):
    """Raised when the CSV cannot be parsed into a PortfolioSnapshot."""


class HoldingsLoader:
    """Loads a Schwab CSV export into a PortfolioSnapshot (HOLD-01, HOLD-02)."""

    @classmethod
    def load(cls, path: Path) -> PortfolioSnapshot:
        """Read `path` and return a merged PortfolioSnapshot.

        Raises:
            HoldingsLoadError: if file missing, unreadable, or column-invalid.
        """
        ...
```

[VERIFIED: matches existing code conventions in `src/alphaswarm/web/routes/report.py` and `src/alphaswarm/security/hashing.py`]

### Pattern 2: CSV Parsing with `csv.DictReader`

**What:** `csv.DictReader` maps each row to a dict using the header row. Column validation is done once after opening the file.

**Example:**
```python
# Source: Python 3.11 stdlib docs [VERIFIED: ASSUMED training knowledge — stdlib API is stable]
try:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise HoldingsLoadError("CSV is empty — no header row")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise HoldingsLoadError(f"CSV missing columns: {missing}")
        rows = list(reader)
except FileNotFoundError:
    raise HoldingsLoadError(f"CSV not found: {path}")
except OSError as exc:
    raise HoldingsLoadError(f"Cannot read CSV: {exc}") from exc
```

**When to use:** Always — `DictReader` is the idiomatic stdlib approach for named-column CSVs.

### Pattern 3: Decimal Arithmetic for cost_basis (D-02)

**What:** Multiply `Decimal(shares_str) * Decimal(cost_basis_per_share_str)` at parse time. Never pass float through.

**Example:**
```python
try:
    qty = Decimal(row["shares"])
    cost_per_share = Decimal(row["cost_basis_per_share"])
    cost_basis = qty * cost_per_share
except InvalidOperation as exc:
    raise HoldingsLoadError(
        f"Invalid numeric value in row {row!r}: {exc}"
    ) from exc
```

[VERIFIED: `Decimal` constructor accepts numeric strings directly — stdlib behavior]

### Pattern 4: account_number_hash Derivation (HOLD-02, Claude's Discretion)

**What:** The CSV uses label strings (`individual`, `roth_ira`) not raw Schwab account numbers. HOLD-02 is satisfied by hashing a deterministic string formed from the sorted set of account labels present in the file.

**Recommendation:** `sha256_first8("|".join(sorted(account_labels)))` where `account_labels` is the set of unique values in the `account` column.

**Why sorted:** Ensures the hash is stable regardless of row order. With the known CSV content this will always be `sha256_first8("individual|roth_ira")`.

**Edge case — empty file with header only:** No account labels → `account_labels` is empty → `sha256_first8("")` raises `TypeError`. Guard: raise `HoldingsLoadError("CSV has no data rows")` before computing the hash.

[VERIFIED: `sha256_first8` raises TypeError on empty string — confirmed by reading `src/alphaswarm/security/hashing.py` directly]

### Pattern 5: `as_of` Timestamp (Claude's Discretion)

**Recommendation:** Use `Path.stat().st_mtime` converted to UTC.

**Rationale:** Reflects the age of the actual data, not the server start time. More meaningful for Phase 41 advisory synthesis (the consumer).

**Example:**
```python
stat = path.stat()
as_of = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
```

**Fallback note:** `path.stat()` can raise `OSError` after the file was successfully opened (race condition, NFS, etc.). Catch and fall back to `datetime.now(UTC)` rather than propagating the error.

[VERIFIED: `PortfolioSnapshot.as_of: datetime` — read from `types.py`]

### Pattern 6: AppSettings Field for CSV Path (D-05)

**What:** Add a `Path`-typed field to `AppSettings` with the env var name `ALPHASWARM_HOLDINGS_CSV_PATH`.

**Example:**
```python
# src/alphaswarm/config.py — inside AppSettings class
from pathlib import Path

holdings_csv_path: Path = Path("Schwab/holdings.csv")
```

**How env var is derived:** `AppSettings` uses `env_prefix = "ALPHASWARM_"` and `env_nested_delimiter = "__"`. A flat field `holdings_csv_path` becomes `ALPHASWARM_HOLDINGS_CSV_PATH`. pydantic-settings coerces string env values to `Path` automatically.

[VERIFIED: `src/alphaswarm/config.py` read directly — `SettingsConfigDict(env_prefix="ALPHASWARM_", ...)` confirmed]

### Pattern 7: Lifespan Wiring (D-07, D-08)

**What:** In the existing `lifespan()` function in `web/app.py`, after constructing other state objects, load the portfolio snapshot and store on `app.state`. This mirrors how `replay_manager`, `sim_manager`, and `connection_manager` are stored.

**Example:**
```python
# Inside lifespan(), after existing state setup:
from alphaswarm.holdings.loader import HoldingsLoader, HoldingsLoadError

try:
    app.state.portfolio_snapshot = HoldingsLoader.load(settings.holdings_csv_path)
    log.info("holdings_loaded", path=str(settings.holdings_csv_path))
except HoldingsLoadError as exc:
    log.error("holdings_load_failed", error=str(exc), path=str(settings.holdings_csv_path))
    app.state.portfolio_snapshot = None
```

[VERIFIED: `src/alphaswarm/web/app.py` read directly — lifespan pattern confirmed]

### Pattern 8: Route Module (HOLD-03)

**What:** `src/alphaswarm/web/routes/holdings.py` follows exactly the same shape as `report.py` — `APIRouter`, `BaseModel` response schema, `Request` for `app.state` access.

**Example:**
```python
# src/alphaswarm/web/routes/holdings.py
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.holdings.types import Holding, PortfolioSnapshot

log = structlog.get_logger(component="web.holdings")

router = APIRouter()


class HoldingOut(BaseModel):
    ticker: str
    qty: str          # Decimal serialized as string (D-06)
    cost_basis: str | None  # Decimal-as-string or null


class HoldingsResponse(BaseModel):
    account_number_hash: str
    as_of: str        # ISO-8601
    holdings: list[HoldingOut]


@router.get("/holdings", response_model=HoldingsResponse)
async def get_holdings(request: Request) -> HoldingsResponse:
    ...
```

**503 response body (Claude's Discretion — recommendation):**
```python
raise HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail={
        "error": "holdings_unavailable",
        "message": "Holdings file could not be loaded at startup",
    },
)
```

[VERIFIED: `src/alphaswarm/web/routes/report.py` read directly — pattern confirmed]

### Pattern 9: Router Registration (HOLD-03)

**What:** One line added to `create_app()` in `web/app.py`.

```python
from alphaswarm.web.routes.holdings import router as holdings_router
...
app.include_router(holdings_router, prefix="/api")
```

[VERIFIED: `create_app()` in `web/app.py` read directly — `include_router(x, prefix="/api")` pattern confirmed for all existing routers]

### Anti-Patterns to Avoid

- **Float for Decimal fields:** `float(row["shares"])` loses precision. Always `Decimal(row["shares"])`.
- **Blocking I/O in async route handler:** The GET handler must not call `HoldingsLoader.load()` at request time — it reads from the pre-loaded `app.state.portfolio_snapshot` only. This satisfies CLAUDE.md Hard Constraint 1 (no blocking I/O on the main event loop).
- **Storing `PortfolioSnapshot` in Neo4j or logging its fields:** Holdings data must never enter the simulation sinks. The isolation invariant (ISOL-07) will catch this if violated.
- **Using `Holding.cost_basis` as-is for JSON serialization:** `json.dumps(Decimal(...))` raises `TypeError`. Always serialize as `str(cost_basis)`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV column parsing | Manual `str.split(",")` | `csv.DictReader` | Handles quoted fields, empty values, trailing whitespace |
| Decimal-as-string serialization | Custom encoder | `str(decimal_value)` in Pydantic `BaseModel` field typed as `str` | Pydantic validates the type; no custom JSON encoder needed |
| Env var config | Manual `os.getenv` | pydantic-settings `AppSettings` field | Already in place; handles `.env`, type coercion, prefix |
| Path validation | Manual `os.path.exists` | `FileNotFoundError` from `open()` | Let stdlib raise; catch in `HoldingsLoader.load()` |

**Key insight:** The holdings domain is pure Python stdlib — no async, no network, no third-party libraries needed.

---

## Common Pitfalls

### Pitfall 1: Decimal from String vs. Float
**What goes wrong:** `float(row["shares"])` passes but loses precision for fractional shares like `101.3071` (AAPL in the actual CSV). `Holding.qty` is typed `Decimal` so mypy catches it, but only if types are checked.
**Why it happens:** `csv.DictReader` returns all values as strings; devs sometimes convert to float first.
**How to avoid:** Always `Decimal(row["shares"])` — never intermediate float.
**Warning signs:** mypy error `Argument 1 to "Holding" has incompatible type "float"; expected "Decimal"`.

### Pitfall 2: sha256_first8 Called with Empty String
**What goes wrong:** If the CSV has a header row but no data rows, `account_labels` is an empty set, `"|".join(sorted(set()))` is `""`, and `sha256_first8("")` raises `TypeError`.
**Why it happens:** The actual CSV has 34 data rows, so this won't occur in production, but a test with an empty-body CSV will hit it.
**How to avoid:** Guard before hashing: `if not account_labels: raise HoldingsLoadError("CSV has no data rows")`.
**Warning signs:** `TypeError: sha256_first8 requires non-empty string` during lifespan startup.

### Pitfall 3: Blocking the Event Loop at Load Time
**What goes wrong:** `HoldingsLoader.load()` does synchronous file I/O. This is acceptable inside `lifespan()` (runs once at startup, before the server accepts requests) but would block the event loop if accidentally called inside an async route handler.
**Why it happens:** D-07 requires eager load; someone might try to refresh it inside the GET handler.
**How to avoid:** GET handler reads only `request.app.state.portfolio_snapshot` — no `load()` call.
**Warning signs:** CLAUDE.md Hard Constraint 1 violation; test performance degradation under load.

### Pitfall 4: importlinter — `alphaswarm.holdings.loader` Must NOT be in source_modules
**What goes wrong:** `alphaswarm.holdings.loader` is a submodule of `alphaswarm.holdings`. The coverage test (`test_importlinter_coverage.py`) explicitly allows submodules of `alphaswarm.holdings.*` to escape `source_modules` (line 101: `if pkg.startswith("alphaswarm.holdings."):`). So adding `loader.py` to `holdings/` requires no pyproject.toml change.
**Why it happens:** Developers unfamiliar with the coverage test logic might try to add `alphaswarm.holdings.loader` to source_modules, which would break `test_source_modules_does_not_list_whitelisted_packages`.
**How to avoid:** Do NOT add `alphaswarm.holdings.loader` to `source_modules`. The existing coverage test handles it correctly.
**Warning signs:** `test_source_modules_covers_every_actual_package` failing.

### Pitfall 5: Cost Basis is Per-Share in CSV, Total in Holding
**What goes wrong:** The CSV column is named `cost_basis_per_share`. A developer reading the column name might store per-share cost directly.
**Why it happens:** Naming ambiguity in the raw CSV.
**How to avoid:** D-02 is explicit — multiply at parse time: `Decimal(shares) * Decimal(cost_basis_per_share)`.
**Warning signs:** Phase 41 advisory ranking will be off by a factor of position size.

### Pitfall 6: as_of Timezone Awareness
**What goes wrong:** `datetime.fromtimestamp(mtime)` returns a naive datetime (no tzinfo). `PortfolioSnapshot.as_of: datetime` accepts both, but ISO-8601 output without timezone is ambiguous.
**Why it happens:** `datetime.fromtimestamp` default is local time, not UTC.
**How to avoid:** Always `datetime.fromtimestamp(mtime, tz=UTC)` — explicit UTC.
**Warning signs:** `as_of` in GET response missing `+00:00` suffix.

### Pitfall 7: Isolation — Don't Log Holding Field Values
**What goes wrong:** `log.info("holdings_loaded", holdings=app.state.portfolio_snapshot.holdings)` would dump ticker/qty/cost_basis into structlog output, causing the ISOL-07 canary to detect a leak.
**Why it happens:** Helpful debug logging.
**How to avoid:** Log only non-sensitive metadata: `count=len(snapshot.holdings)`, `path=str(path)`. Never log `Holding` field values directly.
**Warning signs:** `test_sentinels_do_not_appear_in_logs` in `test_holdings_isolation.py` fails.

---

## Code Examples

### CSV Actual Shape (Verified)

```
account,symbol,shares,cost_basis_per_share
individual,AAPL,101.3071,165.5365
individual,AMZN,48,208.03
...
individual,SWYXX,10000,1
roth_ira,CRDO,31,111.3952
roth_ira,MRVL,48,79.86
roth_ira,QQQ,6.0283,422.8024
```

34 data rows, 4 columns, 2 account labels. Fractional shares present (AAPL: 101.3071, HON: 18.0907, etc.). SWYXX has integer cost_basis_per_share (1). All values are valid Decimal strings.

[VERIFIED: `Schwab/holdings.csv` read directly]

### Existing PortfolioSnapshot Constructor Signature

```python
# src/alphaswarm/holdings/types.py
@dataclasses.dataclass(frozen=True)
class PortfolioSnapshot:
    holdings: tuple[Holding, ...]
    as_of: datetime
    account_number_hash: str
```

`holdings` is a `tuple` (immutable). The loader must pass `tuple(holdings_list)`.

[VERIFIED: `src/alphaswarm/holdings/types.py` read directly]

### Existing sha256_first8 Signature

```python
# src/alphaswarm/security/hashing.py
def sha256_first8(value: str) -> str:
    # Raises TypeError on None or empty string
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
```

[VERIFIED: `src/alphaswarm/security/hashing.py` read directly]

### Test App Pattern (from test_web_report.py)

Route integration tests build a minimal FastAPI app with a custom lifespan that avoids Ollama/Neo4j:

```python
@asynccontextmanager
async def _holdings_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = AppSettings(_env_file=None)
    # Set app.state.portfolio_snapshot to a known PortfolioSnapshot
    app.state.portfolio_snapshot = <test_snapshot>
    yield

def _make_holdings_test_app(snapshot) -> FastAPI:
    from alphaswarm.web.routes.holdings import router as holdings_router
    app = FastAPI(lifespan=...)
    app.include_router(holdings_router, prefix="/api")
    return app
```

[VERIFIED: `tests/test_web_report.py` read directly — `_make_report_test_app` pattern]

---

## Environment Availability

Step 2.6: SKIPPED — Phase 39 has no external dependencies. All dependencies are stdlib or already installed Python packages. No external services (Neo4j, Ollama) are required for the holdings loader or its unit tests. The GET endpoint integration test uses `TestClient` (in-process, no real server).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.0 + pytest-asyncio 0.24 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_holdings_loader.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

`asyncio_mode = "auto"` is project-wide — async test functions need no decorator. `--disable-socket --allow-unix-socket` is global, so no network calls are needed in unit tests.

[VERIFIED: `pyproject.toml` read directly]

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HOLD-01 | `HoldingsLoader.load(path)` returns correct `PortfolioSnapshot` from real CSV | unit | `uv run pytest tests/test_holdings_loader.py -x` | Wave 0 |
| HOLD-01 | `load()` with missing file raises `HoldingsLoadError` | unit | `uv run pytest tests/test_holdings_loader.py::test_load_missing_file -x` | Wave 0 |
| HOLD-01 | `load()` with malformed/missing column raises `HoldingsLoadError` | unit | `uv run pytest tests/test_holdings_loader.py::test_load_malformed_csv -x` | Wave 0 |
| HOLD-01 | cost_basis is total (shares × per_share), not per-share | unit | `uv run pytest tests/test_holdings_loader.py::test_cost_basis_is_total -x` | Wave 0 |
| HOLD-01 | All 34 rows loaded including SWYXX money-market (D-04) | unit | `uv run pytest tests/test_holdings_loader.py::test_all_rows_included -x` | Wave 0 |
| HOLD-02 | `account_number_hash` is sha256_first8 of sorted labels | unit | `uv run pytest tests/test_holdings_loader.py::test_account_hash -x` | Wave 0 |
| HOLD-02 | Raw account label strings do not appear in `account_number_hash` | unit | `uv run pytest tests/test_holdings_loader.py::test_account_label_not_in_hash -x` | Wave 0 |
| HOLD-03 | `GET /api/holdings` 200 returns valid `HoldingsResponse` | unit (TestClient) | `uv run pytest tests/integration/test_holdings_route.py::test_get_holdings_200 -x` | Wave 0 |
| HOLD-03 | `GET /api/holdings` 503 when `portfolio_snapshot` is None | unit (TestClient) | `uv run pytest tests/integration/test_holdings_route.py::test_get_holdings_503 -x` | Wave 0 |
| HOLD-03 | importlinter contract passes after route file created | invariant | `uv run lint-imports` | Existing test |
| SC-3 | ISOL-07 canary still passes after Phase 39 wiring | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py -x` | Existing scaffold |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_holdings_loader.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** `uv run pytest tests/ -x && uv run lint-imports`

### Wave 0 Gaps

- [ ] `tests/test_holdings_loader.py` — unit tests for `HoldingsLoader.load()` covering HOLD-01, HOLD-02
- [ ] `tests/integration/test_holdings_route.py` — TestClient tests for `GET /api/holdings` covering HOLD-03

*(No new framework install needed — pytest + pytest-asyncio already configured)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Holdings endpoint is internal, no auth required in v6.0 |
| V3 Session Management | no | Stateless REST; snapshot cached on app.state |
| V4 Access Control | no | No user-specific access control in v6.0 scope |
| V5 Input Validation | yes | CSV column validation via `REQUIRED_COLUMNS` check; `InvalidOperation` guard on Decimal parse |
| V6 Cryptography | yes | SHA256 used for account label hashing (HOLD-02); `sha256_first8` already implemented |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed CSV with very large numeric strings causing Decimal memory explosion | Tampering | `InvalidOperation` from `Decimal()` catches non-numeric; add row limit guard if needed |
| Holdings data leaking into simulation sinks | Information Disclosure | Isolation invariant (ISOL-07 canary); loader never touches simulation/Neo4j/WS/prompt paths |
| Float precision loss in JSON response | Tampering | Decimal fields serialized as strings in `HoldingOut` Pydantic model |
| Path traversal via env var | Tampering | `settings.holdings_csv_path` is a `Path` type; file is opened read-only; only one configured path used |

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 39 |
|-----------|-------------------|
| 100% async — no blocking I/O on main event loop | CSV load must happen in `lifespan()` (startup, not request time); GET handler reads only cached state |
| Local first — no cloud APIs | Holdings loader is pure local file I/O; no network calls |
| Memory safety via psutil | Holdings loader is a one-shot operation; 34-row CSV has negligible memory impact |
| WebSocket cadence — never block simulation loop | 503 response from GET handler must not propagate exceptions to WS broadcaster |
| Python 3.11+ strict typing | All new code must be fully typed; mypy strict mode required |
| `uv` package manager | Install commands use `uv run` |
| `structlog` for logging | `log = structlog.get_logger(component="holdings.loader")` and `component="web.holdings"` |
| FastAPI + uvicorn, native WebSocket | Route module follows existing `APIRouter` pattern |
| `pydantic` + `pydantic-settings` | Response schema uses `BaseModel`; AppSettings field for CSV path |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `csv.DictReader` fieldnames are available before iterating rows when the file has a header | Architecture Patterns — Pitfall 2 | Extremely low; stdlib behavior for 30+ years. Would cause `AttributeError` at column validation step |
| A2 | `Path.stat().st_mtime` is available and reflects the last write time of the CSV on macOS (Apple M1) | Pattern 5 | Very low; standard POSIX stat behavior. Fallback to `datetime.now(UTC)` is trivial |
| A3 | pydantic-settings coerces string env var to `pathlib.Path` automatically | Pattern 6 — AppSettings field | Low; pydantic-settings v2 supports `Path` field coercion. Verified indirectly by existing `Path`-typed usage patterns in the project |

**All other claims were verified by reading actual source files in this session.**

---

## Open Questions

1. **`as_of` timestamp source (Claude's Discretion)**
   - What we know: D-07 says "eager load at lifespan startup"; CONTEXT.md leaves `as_of` source to planner
   - What's unclear: whether `st_mtime` (data age) or `datetime.now(UTC)` (load time) better serves Phase 41 advisory synthesis
   - Recommendation: `Path.stat().st_mtime` converted to UTC — more semantically correct (when the portfolio was last exported). Fallback to `datetime.now(UTC)` if stat fails.

2. **503 response body for missing/malformed CSV (Claude's Discretion)**
   - Recommendation: `{"error": "holdings_unavailable", "message": "Holdings file could not be loaded at startup"}` — matches the dict-valued `detail` pattern used in all existing routes (report.py, simulation.py).

3. **HoldingsLoader: class vs. function (Claude's Discretion)**
   - Recommendation: class with `load()` classmethod — easier to mock in tests (`patch("alphaswarm.holdings.loader.HoldingsLoader.load")`), consistent with Phase 41 extending the class with a `validate()` or `reload()` method.

---

## Sources

### Primary (HIGH confidence)
- `Schwab/holdings.csv` — read directly; 34 data rows, 4 columns, 2 account labels confirmed
- `src/alphaswarm/holdings/types.py` — `Holding`, `PortfolioSnapshot` field signatures confirmed
- `src/alphaswarm/security/hashing.py` — `sha256_first8` signature and empty-string behavior confirmed
- `src/alphaswarm/web/app.py` — lifespan pattern, router registration pattern confirmed
- `src/alphaswarm/web/routes/report.py` — route module pattern confirmed
- `src/alphaswarm/config.py` — `AppSettings`, `SettingsConfigDict`, env_prefix confirmed
- `pyproject.toml` — importlinter contract, source_modules list, pytest config confirmed
- `tests/invariants/test_holdings_isolation.py` — ISOL-07 canary structure confirmed
- `tests/invariants/test_importlinter_coverage.py` — `_KNOWN_NON_SOURCE` already contains `alphaswarm.web.routes.holdings` confirmed
- `tests/invariants/conftest.py` — sentinel fixtures and capture infrastructure confirmed
- `tests/test_web_report.py` — `_make_report_test_app` TestClient pattern confirmed
- `tests/conftest.py` — `AppSettings(_env_file=None)` test pattern confirmed

### Secondary (MEDIUM confidence)
- None required — all critical claims verified from source files.

### Tertiary (LOW confidence)
- A3: pydantic-settings `Path` field coercion — not explicitly verified via docs; assessed from pydantic-settings v2 patterns [ASSUMED]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified from existing codebase
- Architecture: HIGH — patterns verified from reading actual source files
- Pitfalls: HIGH — derived from real code (sha256_first8 behavior, importlinter coverage test logic, existing type signatures)

**Research date:** 2026-04-18
**Valid until:** 2026-05-18 (stable domain — stdlib CSV, FastAPI patterns unchanged)
