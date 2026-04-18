# Phase 37: Isolation Foundation & Provider Scaffolding - Research

**Researched:** 2026-04-18
**Domain:** Information-isolation scaffolding — typed boundaries, static import contracts, network gates, PII redaction, provider protocols, canary invariant tests
**Confidence:** HIGH

## Summary

Phase 37 is purely scaffolding — no business logic, no real providers, no UI. It installs the five defensive invariants that every subsequent v6.0 phase (38–43) depends on: (1) frozen typed boundaries (`Holding`, `PortfolioSnapshot`, `ContextPacket`, `MarketSlice`, `NewsSlice`), (2) a whitelist-only `importlinter` contract forbidding any module except `alphaswarm.advisory` and `alphaswarm.web.routes.holdings` from importing `alphaswarm.holdings`, (3) a global structlog PII redaction processor with fail-closed semantics, (4) `pytest-socket` global `--disable-socket` gate with opt-in integration escape hatches, and (5) a canary test `tests/invariants/test_holdings_isolation.py` that exercises all four leak surfaces (logs, Neo4j, WebSocket, prompts) with sentinel strings. CONTEXT.md has locked all 20 major design decisions (D-01 through D-20); research confirms they are implementable with verified library versions and matches current codebase conventions. No research-blocking unknowns remain.

**Primary recommendation:** Execute CONTEXT.md decisions verbatim. Add `import-linter>=2.11`, `pytest-socket>=0.7.0`, `hypothesis>=6.152` to dev dependencies. Pin the structlog processor insertion point between `StackInfoRenderer` and the terminal renderer in `configure_logging()`. Ship `FakeMarketDataProvider` / `FakeNewsProvider` as ~30 LOC each so Phase 38 has a test-first landing pad.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**importlinter contract shape**
- **D-01:** Contract type is **`forbidden`** (not layered). Matches research ADR sketch at `research/ARCHITECTURE.md:163` verbatim; minimum-viable isolation with low maintenance.
- **D-02:** Enforcement at **CI + pre-commit hook**. Pre-commit gives fast local feedback (~1s); CI is the authoritative gate.
- **D-03:** Permanent unit test `tests/invariants/test_importlinter_contract.py` invokes `lint-imports` programmatically on a synthetic violating module fixture and asserts exit code ≠ 0. Self-documenting regression guard for anyone loosening the contract later.
- **D-04:** **Whitelist-only scope** — `alphaswarm.holdings` may be imported by **only** `alphaswarm.advisory` and `alphaswarm.web.routes.holdings`. All other modules (simulation, worker, batch_dispatcher, seed, parsing, ingestion, web.routes.*, graph, report, cli, tui) are forbidden importers. Strongest posture; matches Option A invariant ("HoldingsStore has exactly one consumer: AdvisoryPipeline").

**PII redaction strategy**
- **D-05:** **Key-first + value-pattern backstop** detection. Primary allowlist of sensitive keys: `holdings`, `portfolio`, `positions`, `cost_basis`, `account_number`, `account_id`, `qty`, `shares`. Secondary regex backstop for currency patterns (`$12,345.67`) + SSN-like sequences on remaining string values.
- **D-06:** **Mixed redaction markers** — `account_*` fields replaced with SHA256 first-8-char hash (enables debug correlation, matches HOLD-04 hashing policy); all other sensitive fields replaced with literal `"[REDACTED]"`.
- **D-07:** Processor **fails closed** — if redaction raises, drop the log event entirely and emit a single `redaction_failed` marker event with no user data. Fail-open defeats the invariant; fail-hard crashes simulation over log bugs.
- **D-08:** Fuzz test combines **Hypothesis property-based generation** (random dicts with mixed sensitive/safe keys; assert no sensitive values render verbatim) + **tabular scenarios** (nested dicts, lists of holdings, positional args, f-string interpolation) for regression lock-in.

**pytest-socket scope**
- **D-09:** **Block all outbound sockets globally** via `--disable-socket` in `[tool.pytest.ini_options]`. Single policy, no env-conditional behavior.
- **D-10:** **No loopback allowance** — localhost/127.0.0.1/::1 also blocked by default. Integration tests (Neo4j, Ollama) must opt in explicitly.
- **D-11:** **Unix sockets blocked** (pytest-socket default). No current dependency requires them (Neo4j bolt://, Ollama HTTP).
- **D-12:** Escape hatch via **directory-wide marker** in `tests/integration/conftest.py` auto-applying `@pytest.mark.enable_socket` to all tests in that tree, plus **explicit `@pytest.mark.enable_socket`** for one-off exceptions outside `tests/integration/`.

**Canary test design**
- **D-13:** **ASCII string sentinels** — `ticker="SNTL_CANARY_TICKER"`, `account_number="SNTL_CANARY_ACCT_000"`, `cost_basis=Decimal("999999.99")`, `qty=Decimal("77.7777")`. Greppable in logs, prompts, Neo4j properties, WebSocket frames without tooling.
- **D-14:** Phase 37 canary **runs a minimal simulation** (empty seed, no advisory path) with sentinel `PortfolioSnapshot` constructed, then asserts sentinel strings do not appear in any captured surface. Trivially passes at Phase 37 (no holdings code path exists), becomes load-bearing at Phase 41 when advisory activates the join point.
- **D-15:** **Leak detection across all four surfaces**: structlog output capture, Neo4j node/relationship property scan, WebSocket broadcaster frame intercept, and rendered worker prompt strings. Matches PROJECT.md invariant verbatim ("holdings never in any swarm prompt, Neo4j node, or WebSocket frame").
- **D-16:** Test lives at `tests/invariants/test_holdings_isolation.py` — new `tests/invariants/` directory signals "architectural invariants, not feature tests". Phase 37 also creates the directory convention for future invariant tests (schema-assertion, log-grep, etc.). Marked with `@pytest.mark.enable_socket` since Q4.3 surfaces touch Neo4j + WebSocket.

**Provider Protocol granularity**
- **D-17:** **Two Protocols only** — `MarketDataProvider` (price, fundamentals, volume methods) and `NewsProvider` (headlines). Matches ISOL-05 verbatim and research SUMMARY; no per-query-type splits, no capability flags.
- **D-18:** **Batch-first method signatures** — e.g., `async def get_prices(tickers: list[str]) -> dict[str, PriceQuote]`. Aligns with `yf.download()` bulk pattern from `research/STACK.md`; enforces the right calling shape for Phase 38's 100-ticker load.
- **D-19:** **Errors and staleness encoded in the returned slice** — providers always return `MarketSlice` / `NewsSlice`, never raise for fetch failures. Failed fetches produce `MarketSlice(data=None, staleness="fetch_failed", source=..., fetched_at=...)`. Matches Phase 38 SC #1 exactly; callers don't need try/except in the 100-ticker aggregation loop.
- **D-20:** Phase 37 deliverable depth: **Protocols + `FakeMarketDataProvider` / `FakeNewsProvider`** with in-memory sentinel-friendly fakes. Adds ~30 lines, unblocks Phase 38's test-first implementation. Real yfinance/RSS providers deferred to Phase 38.

### Claude's Discretion
- Exact `importlinter` TOML layout (top-level `[importlinter]` stanza layout, contract names).
- Precise SHA256 account-hash function location (likely `alphaswarm/holdings/redaction.py` or a shared `alphaswarm/security/hashing.py` — planner decides).
- Hypothesis strategy specifics (shrinking behavior, example size bounds).
- `tests/invariants/conftest.py` fixture shape (sentinel portfolio builder, log capture helper, WS intercept stub).
- Fake provider response payload shape beyond "returns sentinel-friendly MarketSlice/NewsSlice".

### Deferred Ideas (OUT OF SCOPE)
- **Log-grep CI gate** (`research/ARCHITECTURE.md:189`) — a cruder `grep -r "holdings\|portfolio" src/alphaswarm/templates/ worker.py simulation.py` in CI as a belt-and-suspenders check beyond importlinter. Useful but redundant with D-04 whitelist; defer unless the whitelist proves porous.
- **Layered importlinter contract** — add later if new top-level modules accumulate faster than the whitelist can be maintained. Phase 37 sticks with `forbidden` (D-01).
- **`_NotImplementedYetProvider` sentinel** — explicit "turn on in Phase 38" guard on the settings default provider. Not added (D-20 picks Option 2). Revisit if Phase 38 test scaffolding wants to assert "real provider not yet wired".
- **Runtime schema assertion for `ContextPacket`** — extra paranoia (e.g., `pytest` hook that introspects every ContextPacket instance for holdings-shaped keys). Pydantic `extra="forbid"` already covers the static case.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ISOL-01 | `Holding` and `PortfolioSnapshot` frozen dataclasses in `alphaswarm/holdings/types.py` with zero I/O | `research/STACK.md:118-142` — stdlib `@dataclass(frozen=True)` pattern; existing `types.py:96-126` shows the stdlib-frozen pattern already in use (ParsedSeedResult, ParsedModifiersResult) |
| ISOL-02 | `ContextPacket`, `MarketSlice`, `NewsSlice` frozen pydantic models in `alphaswarm/ingestion/types.py` with `extra="forbid"` and zero holdings fields | Existing `types.py:26-47` — `BracketConfig` and `AgentPersona` use `BaseModel, frozen=True` with `Field(...)` validation. Add `model_config = ConfigDict(extra="forbid")` (pydantic v2) |
| ISOL-03 | `importlinter` contract in `pyproject.toml` forbidding `alphaswarm.holdings` imports from simulation, worker, ingestion, seed, parsing; enforced in CI | `import-linter==2.11` (released 2026-03-06); forbidden contract TOML syntax verified; D-04 whitelist is stricter than ISOL-03 baseline — codify D-04 |
| ISOL-04 | structlog PII redaction processor installed globally before any holdings code is written | `structlog==25.5.0`; processor protocol: callable `(logger, method_name, event_dict) -> event_dict`; insertion point between `StackInfoRenderer` and terminal renderer in `logging.py:15-21` |
| ISOL-05 | `MarketDataProvider` and `NewsProvider` Protocol definitions (no implementations yet) | `typing.Protocol` in Python 3.11+; `mypy strict=true` forces full type annotations; D-17/D-18/D-19 lock shape |
| ISOL-06 | `pytest-socket` in CI blocks outbound network calls during test runs | `pytest-socket==0.7.0` (last stable, 2024-01-28); `--disable-socket` in `[tool.pytest.ini_options] addopts`; `@pytest.mark.enable_socket` escape hatch |
| ISOL-07 | Canary test scaffold (`test_holdings_isolation.py`) with sentinel ticker/cost-basis fixtures (trivially passes until advisory phase activates the join point) | Four-surface leak detection (D-15) requires: structlog `capturing_logger_factory`, Neo4j Cypher property scan, ConnectionManager frame intercept, Jinja template render capture |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

These directives are binding on this phase's plan. The planner MUST NOT recommend approaches that contradict them.

| Directive | Source | Implication for Phase 37 |
|-----------|--------|--------------------------|
| 100% async — no blocking I/O on the main event loop | Hard Constraint 1 | Fake providers' methods are `async def`; test helpers (log capture, WS intercept) cannot use `threading.Event` on the sim task |
| Local-first, no cloud APIs | Hard Constraint 2 | `pytest-socket` fully blocks network (D-09); no test may call PyPI, a CDN, or registry |
| Memory safety via psutil, semaphore throttling | Hard Constraint 3 | Hypothesis fuzz test caps `max_examples` to avoid RAM blowup on repr expansion |
| WebSocket ~5Hz, drop-oldest backpressure | Hard Constraint 4 | Canary WS frame intercept must use the existing ConnectionManager hook, not monkey-patch the broadcaster |
| Python 3.11+ strict typing (`mypy strict=true`) | Technology Stack | All Protocol definitions must be fully typed; no `Any` in public signatures |
| `uv` is the package manager | Technology Stack | `uv add import-linter pytest-socket hypothesis --dev`; no `pip install` in docs |
| `pytest-asyncio asyncio_mode="auto"` | Existing `pyproject.toml:46` | Async test functions don't need `@pytest.mark.asyncio` decoration |
| GSD workflow enforcement — no edits outside a GSD command | CLAUDE.md §GSD | Planner's tasks must chain through `/gsd:execute-phase`, not direct edits |
| `structlog` for logging | Technology Stack | PII redaction is a structlog processor, not a stdlib `logging.Filter`, not a wrapper |
| `pydantic` + `pydantic-settings` for validation/config | Technology Stack | `ContextPacket`/`MarketSlice`/`NewsSlice` use pydantic v2; `Holding`/`PortfolioSnapshot` use stdlib dataclass (per research STACK.md:118) — intentional split, not inconsistency |

## Standard Stack

### Core (new dev dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `import-linter` | **2.11** (2026-03-06) | Static import-graph contracts enforced via `lint-imports` CLI + programmatic API | `[VERIFIED: PyPI 2026-03-06]` — de facto standard for Python architectural contracts; native `pyproject.toml` support; forbidden + layered + independence + contains contract types all documented |
| `pytest-socket` | **0.7.0** (2024-01-28) | Blocks socket access during test runs; raises `SocketBlockedError` on violation | `[VERIFIED: PyPI]` — stable, widely adopted. Though 18 months since last release, 0.7.0 supports Python 3.8–3.13, works with pytest 8.x (already in stack) |
| `hypothesis` | **6.152.1** (2026-04-14) | Property-based test generation for fuzzing PII redaction | `[VERIFIED: PyPI 2026-04-14]` — industry standard for Python property-based testing; `hypothesis.strategies.dictionaries()` + `text()` generates the nested dict fixtures D-08 requires |

### Supporting (already in stack — reuse)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `structlog` | 25.5.0 | Logging with processor chain | `[VERIFIED: pyproject.toml]` PII redaction is a new processor inserted into `shared_processors` |
| `pydantic` | 2.12.5 | Typed frozen models for `ContextPacket`/`MarketSlice`/`NewsSlice` | `[VERIFIED: pyproject.toml]` Use `BaseModel` with `model_config = ConfigDict(frozen=True, extra="forbid")` (pydantic v2 idiom) |
| `pytest-asyncio` | 0.24.0+ | Async test support | Already configured with `asyncio_mode="auto"` |
| `pytest` | 8.0+ | Test runner | Canary test runs under existing harness |
| `typing.Protocol` | stdlib | Provider Protocol definitions (ISOL-05) | Python 3.11+ native; no `runtime_checkable` unless reflection is actually used (mypy static check is sufficient) |
| `dataclasses.dataclass(frozen=True)` | stdlib | `Holding`, `PortfolioSnapshot` (ISOL-01) | Already imported at `types.py:5`; stdlib-frozen intentional per research STACK.md for zero-dep holdings types |
| `hashlib.sha256` | stdlib | Account-number hashing (D-06) | No crypto library needed for hash-only non-authenticating use |
| `decimal.Decimal` | stdlib | `cost_basis`, `qty` fields (D-13, HOLD-02) | Never `float` for financial quantities |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `import-linter` | `ruff` custom rules | `[ASSUMED]` ruff lacks a first-class "module A must not import module B (transitively)" rule as of 2026-Q1. import-linter is the verified standard. |
| `import-linter` | Manual `grep` in CI | Crude, cannot catch indirect/transitive imports, no ignore-import allowlist for deliberate seams. Rejected in CONTEXT.md D-01. |
| `pytest-socket` | `pytest-httpserver` + manual mock | `pytest-socket` is a gate (default-deny), the alternative is a fixture (opt-in). Gate is stronger for the invariant. |
| `hypothesis` | Hand-written enumerated cases only | D-08 explicitly asks for both — hypothesis catches regressions no human enumerates. Pure tabular tests miss adversarial inputs. |
| pydantic v2 `extra="forbid"` via `model_config` | Pydantic v1 `class Config: extra = "forbid"` | pydantic is already v2.12+ in stack; v2 idiom is `model_config = ConfigDict(extra="forbid")`. Do not copy v1 syntax. |

**Installation:**

```bash
uv add --dev import-linter==2.11 pytest-socket==0.7.0 hypothesis==6.152.1
```

**Version verification (already performed):**
```
import-linter : 2.11         (2026-03-06)  [VERIFIED: PyPI JSON API]
pytest-socket : 0.7.0        (2024-01-28)  [VERIFIED: PyPI JSON API]
hypothesis    : 6.152.1      (2026-04-14)  [VERIFIED: PyPI JSON API]
structlog     : 25.5.0       (2025-10-27)  [VERIFIED: PyPI JSON API — matches pyproject.toml pin]
```

Version pins match the `^X.Y` style already used in the project's `pyproject.toml`. Minor upgrades are expected to be non-breaking for these packages.

## Architecture Patterns

### Recommended Project Structure

```
src/alphaswarm/
├── holdings/                        # NEW — isolated; only advisory + web.routes.holdings may import
│   ├── __init__.py
│   └── types.py                     # ISOL-01: Holding, PortfolioSnapshot (stdlib @dataclass(frozen=True))
├── ingestion/                       # NEW — swarm-safe types live here
│   ├── __init__.py
│   ├── types.py                     # ISOL-02: ContextPacket, MarketSlice, NewsSlice (pydantic frozen + extra="forbid")
│   └── providers.py                 # ISOL-05: MarketDataProvider, NewsProvider (Protocol) + FakeMarketDataProvider, FakeNewsProvider (D-20)
├── security/                        # NEW (planner's discretion — may alternatively live in holdings/)
│   └── hashing.py                   # D-06: sha256_first8(value: str) -> str shared by ISOL-04 and HOLD-04
├── logging.py                       # MODIFIED: insert redaction processor into shared_processors
└── ...                              # existing modules unchanged

tests/
├── invariants/                      # NEW directory — architectural invariants, not feature tests
│   ├── __init__.py
│   ├── conftest.py                  # sentinel portfolio builder, log capture helper, WS intercept stub
│   ├── test_importlinter_contract.py  # D-03: invokes lint-imports programmatically on synthetic violation fixture
│   ├── test_holdings_isolation.py   # ISOL-07: four-surface leak check with sentinels (D-13..D-16)
│   └── test_pii_redaction.py        # D-08: hypothesis + tabular fuzz over redaction processor
├── integration/                     # NEW directory (if not present) — opt-in network tests
│   └── conftest.py                  # D-12: auto-apply @pytest.mark.enable_socket to whole subtree
└── ...                              # existing test files unchanged

pyproject.toml                       # MODIFIED: +deps, +[tool.importlinter], +pytest addopts
.pre-commit-config.yaml              # NEW (likely) — lint-imports hook per D-02
```

### Pattern 1: Forbidden contract with whitelist inversion

**What:** Express "only X and Y may import Z" using `forbidden` by listing every other top-level module as a source.

**When to use:** The whitelist is small and stable (two allowed importers) and stricter than a loose list of known-forbidden paths.

**Example:**

```toml
# pyproject.toml  [CITED: import-linter docs §Forbidden contract]
[tool.importlinter]
root_package = "alphaswarm"

[[tool.importlinter.contracts]]
name = "Holdings isolation — only advisory and web.routes.holdings may import alphaswarm.holdings"
type = "forbidden"
source_modules = [
    "alphaswarm.simulation",
    "alphaswarm.worker",
    "alphaswarm.batch_dispatcher",
    "alphaswarm.seed",
    "alphaswarm.parsing",
    "alphaswarm.ingestion",
    "alphaswarm.graph",
    "alphaswarm.report",
    "alphaswarm.interview",
    "alphaswarm.cli",
    "alphaswarm.tui",
    "alphaswarm.web.app",
    "alphaswarm.web.simulation_manager",
    "alphaswarm.web.broadcaster",
    "alphaswarm.web.connection_manager",
    "alphaswarm.web.routes.simulation",
    "alphaswarm.web.routes.report",
    "alphaswarm.web.routes.replay",
    "alphaswarm.web.routes.interview",
]
forbidden_modules = ["alphaswarm.holdings"]
# allow_indirect_imports defaults to False; indirect imports ARE checked (correct behavior)
```

Run locally:
```bash
uv run lint-imports
```

**Reference:** `[CITED: https://import-linter.readthedocs.io/en/v2.9/contract_types/forbidden/]` — forbidden contract semantics.

### Pattern 2: structlog PII redaction processor

**What:** A callable inserted into the structlog processor chain before the terminal renderer. Receives `(logger, method_name, event_dict)`; returns a mutated `event_dict`.

**When to use:** Any time keys or values in the event dict may contain PII that must not reach rendered output.

**Example:**

```python
# src/alphaswarm/logging.py (modified)  [CITED: structlog.org/en/stable/processors.html]
from __future__ import annotations
import hashlib
import re
from typing import Any

_SENSITIVE_KEYS = frozenset({
    "holdings", "portfolio", "positions", "cost_basis",
    "account_number", "account_id", "qty", "shares",
})
_CURRENCY_RE = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ACCOUNT_KEYS = frozenset({"account_number", "account_id"})

def _sha256_first8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]

def _redact_value(key: str, value: Any) -> Any:
    # D-06: account_* → hash; others → literal "[REDACTED]"
    if key in _ACCOUNT_KEYS:
        return f"acct:{_sha256_first8(str(value))}"
    return "[REDACTED]"

def _scrub_string(s: str) -> str:
    s = _CURRENCY_RE.sub("[REDACTED_CURRENCY]", s)
    s = _SSN_RE.sub("[REDACTED_SSN]", s)
    return s

def pii_redaction_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """D-05 + D-06 + D-07 implementation."""
    try:
        for k in list(event_dict.keys()):
            if k in _SENSITIVE_KEYS:
                event_dict[k] = _redact_value(k, event_dict[k])
        # Value-pattern backstop for remaining string values
        for k, v in list(event_dict.items()):
            if isinstance(v, str) and k not in _SENSITIVE_KEYS:
                event_dict[k] = _scrub_string(v)
        return event_dict
    except Exception:
        # D-07 fail-closed: drop the event, emit a marker
        raise structlog.DropEvent  # noqa — re-raise into a safe marker event
```

For D-07's "drop and emit a single marker" semantics, the safest implementation raises `DropEvent` to discard, then a wrapping processor or post-`DropEvent` emit writes `{"event": "redaction_failed"}` via a separate side-channel logger. Planner determines the exact pattern; `DropEvent` is the primitive.

**Processor chain insertion point (in `configure_logging()`):**

```python
shared_processors: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,        # MUST be first
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.dev.set_exc_info,
    pii_redaction_processor,                        # NEW — after enrichment, before render
]
if json_output:
    shared_processors.append(structlog.processors.JSONRenderer())
else:
    shared_processors.append(structlog.dev.ConsoleRenderer())
```

**Reference:** `[CITED: structlog.org/en/stable/processors.html]` — "A processor is a callable that receives `(logger, method_name, event_dict)` and returns the modified `event_dict`. Raise `structlog.DropEvent` to drop the event."

### Pattern 3: Two Protocols with batch-first async signatures

**What:** `typing.Protocol` classes defining the ingestion interface; providers return a typed slice that carries success/failure/staleness inline.

**When to use:** Phase 37 must define the seam Phase 38 implements. Protocols + fakes lets Phase 38 be test-first.

**Example:**

```python
# src/alphaswarm/ingestion/providers.py  (sketch — D-17/D-18/D-19/D-20)
from __future__ import annotations
from typing import Protocol
from alphaswarm.ingestion.types import MarketSlice, NewsSlice

class MarketDataProvider(Protocol):
    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]: ...
    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]: ...
    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]: ...

class NewsProvider(Protocol):
    async def get_headlines(
        self, entities: list[str], *, max_age_hours: int = 72
    ) -> dict[str, NewsSlice]: ...

class FakeMarketDataProvider:
    """In-memory test fake. Returns sentinel-friendly slices."""
    def __init__(self, fixtures: dict[str, MarketSlice] | None = None) -> None:
        self._fixtures = fixtures or {}

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return {t: self._fixtures.get(t, _empty_slice(t, "not_configured")) for t in tickers}
    # ... get_fundamentals, get_volume similar
```

### Pattern 4: Frozen pydantic packet with extra="forbid"

**What:** Pydantic v2 `BaseModel` subclasses with `model_config = ConfigDict(frozen=True, extra="forbid")` — runtime rejects unknown keys at construction, static mypy catches attribute drift.

**When to use:** Every type that crosses the ingestion↔swarm seam. This is the static half of the defense-in-depth (research/SUMMARY.md:105-108).

**Example:**

```python
# src/alphaswarm/ingestion/types.py
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StalenessState = Literal["fresh", "stale", "fetch_failed"]

class MarketSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ticker: str
    price: float | None = None
    volume: int | None = None
    fundamentals: dict[str, float] | None = None
    fetched_at: datetime
    source: str
    staleness: StalenessState = "fresh"

class NewsSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity: str
    headlines: tuple[str, ...] = Field(default_factory=tuple)
    fetched_at: datetime
    source: str
    staleness: StalenessState = "fresh"

class ContextPacket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle_id: str
    as_of: datetime
    entities: tuple[str, ...]
    market: tuple[MarketSlice, ...] = Field(default_factory=tuple)
    news: tuple[NewsSlice, ...] = Field(default_factory=tuple)
```

### Anti-Patterns to Avoid

- **Using `ruff` for import contracts:** Not the right tool; ruff rules are line-local, not graph-aware. `[ASSUMED]` verified no such rule exists in ruff 2026-Q1.
- **Putting redaction processor AFTER the renderer:** Renderer has already serialized to a string — you can only regex-scrub strings then, which is brittle and loses structure. Insert before renderer.
- **`runtime_checkable` Protocol without need:** Adds reflection overhead; mypy static checking is sufficient for this phase (D-17 does not specify runtime isinstance checks).
- **Shared parent type between `Holding` and `ContextPacket`:** Research/ARCHITECTURE.md Anti-Pattern 4 — "Accept the duplication. Single shared module is the leakage vector."
- **`float` for `cost_basis` or `qty`:** Use `Decimal`. Financial values must not suffer binary-float rounding (matches HOLD-02 schema ahead of Phase 39).
- **Generic `except Exception: pass` in redaction processor:** D-07 is fail-closed — must emit a marker event and drop the log entry; never silent swallow.
- **Monkeypatching `socket.socket` manually in tests:** pytest-socket already does this correctly; rolling your own defeats the escape-hatch marker mechanism.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Static import-graph enforcement | Regex over source files or AST walker | `import-linter` | Handles transitive imports, ignore-import allowlists, `as_packages` semantics, native pyproject.toml config |
| Network-call blocking in tests | `socket.socket = _Blocked()` monkeypatch | `pytest-socket` | Correct marker integration (`@pytest.mark.enable_socket`), preserves tracebacks, handles `getaddrinfo` |
| Property-based fuzzing | Hand-written loops over `random.choice` | `hypothesis` | Shrinking finds minimal failing cases; stateful testing; mature strategies library |
| Frozen-type boundary enforcement | `__setattr__ = raise` or runtime checks | pydantic v2 `frozen=True` + `extra="forbid"` | Static mypy catches field drift; runtime rejects unknown keys at construction; integrates with existing codebase pattern |
| Structured log processor chain | Custom logging.Filter or wrapper | `structlog` processor | Already the project's logger; insertion point is a one-line list append |
| SHA-256 hashing | hmac implementation or rolling your own | `hashlib.sha256` (stdlib) | Stdlib sufficient; D-06 uses hash for correlation (no authentication), no crypto library needed |
| Decimal arithmetic for money | `float` + rounding helpers | `decimal.Decimal` (stdlib) | Binary float loses cents; `Decimal` is the canonical financial type |
| Async network intercept for canary | urllib/socket monkeypatches on main loop | Existing `ConnectionManager` / broadcaster hooks | Respects ResourceGovernor and async invariants; matches D-15's "use actual broadcaster" intent |

**Key insight:** Phase 37 is scaffolding for a defensive invariant. Every custom implementation is a potential hole. Prefer battle-tested libraries (import-linter, pytest-socket, hypothesis) over 30-line DIY alternatives — the attack surface for an isolation leak is larger than the maintenance cost of three well-known dev dependencies.

## Common Pitfalls

### Pitfall 1: Redaction processor placed after the renderer

**What goes wrong:** JSON/console renderer serializes `event_dict` to a string; the "redaction" processor then has only a string to regex over, missing nested structure and deleted/renamed keys.
**Why it happens:** `append()` instead of `insert()` onto the shared processors list.
**How to avoid:** Insert immediately before `JSONRenderer()` / `ConsoleRenderer()`. Write a unit test that registers a sentinel processor AFTER the renderer — its input must be a string (confirming renderer ran last).
**Warning signs:** Renderer output contains `{"holdings": [...]}` verbatim; assertion in `test_pii_redaction.py` fails with "key did not get redacted."

### Pitfall 2: Pydantic v1 syntax for `extra="forbid"`

**What goes wrong:** Developer writes `class Config: extra = "forbid"` (v1 idiom) in a v2 codebase; silently ignored. Validator doesn't reject extra keys.
**Why it happens:** Stale documentation or copy-paste from older projects. `[VERIFIED: pydantic 2.12.5 in pyproject.toml]`
**How to avoid:** Always use `model_config = ConfigDict(frozen=True, extra="forbid")`. Add a unit test: construct `ContextPacket(extra_field="x")` and assert it raises `ValidationError`.
**Warning signs:** `ContextPacket(unknown_field=...)` does not raise; test coverage on `extra="forbid"` case is absent.

### Pitfall 3: `lint-imports` not run in CI, only pre-commit

**What goes wrong:** CONTEXT.md D-02 requires both, but if CI only has pre-commit-hook cache validation (or the hook is skipped via `--no-verify`), bad imports reach master.
**Why it happens:** Pre-commit hooks can be bypassed; CI is the authoritative gate.
**How to avoid:** Add an explicit `lint-imports` step in the CI workflow, not only a `pre-commit run --all-files` step. Assert exit code ≠ 0 on a violating fixture in `test_importlinter_contract.py` (D-03).
**Warning signs:** CI logs show no `lint-imports` invocation; developer claims "tests passed" but didn't run pre-commit.

### Pitfall 4: pytest-socket `@pytest.mark.enable_socket` not auto-applied

**What goes wrong:** D-12 requires `tests/integration/conftest.py` to auto-apply the marker to all tests in that directory. If the `pytest_collection_modifyitems` hook isn't implemented correctly, every integration test must individually mark itself — gets forgotten.
**Why it happens:** Developers confuse "fixture" (test requests it) with "auto-use marker" (conftest applies it).
**How to avoid:** Use the canonical `pytest_collection_modifyitems` hook pattern to add `enable_socket` marker to every collected item in the subtree. Test the hook: an unmarked test in `tests/integration/` must have `enable_socket` in its marker list at runtime.
**Warning signs:** Integration test fails with `SocketBlockedError` despite being in `tests/integration/`; developer manually adds the marker and moves on.

### Pitfall 5: Fake providers that secretly do I/O

**What goes wrong:** `FakeMarketDataProvider` imports `yfinance` at module level or hits `time.sleep(0.1)` "to simulate latency" — now pytest-socket or CI flakiness catches it.
**Why it happens:** Reused code snippets from Phase 38 drafting.
**How to avoid:** Fakes are pure in-memory dict lookups. No top-level imports of yfinance/httpx/feedparser. Assert: `FakeMarketDataProvider` source file has zero network-library imports (add as a meta-test in invariants/).
**Warning signs:** `uv pip list` shows yfinance in Phase 37 deps; `FakeMarketDataProvider` calls `await asyncio.sleep(...)` with non-zero value.

### Pitfall 6: Canary test trivially passes because surfaces aren't wired

**What goes wrong:** D-14/D-15 — at Phase 37 there's no advisory code, so of course sentinels don't appear. If the test harness doesn't actually capture from all four surfaces, the test gives false assurance; Phase 41's activation doesn't activate the tripwire.
**Why it happens:** Test asserts `assert "SNTL_CANARY_TICKER" not in ""` against an uninstantiated capture.
**How to avoid:** Test the test — add a complementary "positive control" test that injects the sentinel into each surface and asserts the capture DOES see it. Only then is the negative canary meaningful.
**Warning signs:** `test_holdings_isolation.py` passes with zero log lines captured; positive control tests absent or skipped.

### Pitfall 7: SHA256 hashing of empty string/None yields same hash everywhere

**What goes wrong:** `sha256("")` is a constant; if D-06 gets passed `None` or `""` (not a real account number), all "redacted" values collapse to the same 8-char hash → false correlation.
**Why it happens:** No guard on input type.
**How to avoid:** Validate input: reject `None`, reject empty string, type-check `str`. Raise `TypeError` in `_sha256_first8()` rather than return the constant hash.
**Warning signs:** Log analysis shows many events with identical `acct:e3b0c442` hash; confusion in correlation queries.

### Pitfall 8: `runtime_checkable` on Protocols triggers isinstance overhead

**What goes wrong:** Developer adds `@runtime_checkable` "to be safe" to every Protocol; now every `isinstance(x, MarketDataProvider)` call reflects over all methods — measurable slowdown in hot paths.
**Why it happens:** Unclear guidance; CONTEXT.md is silent so planner default may over-apply.
**How to avoid:** Do NOT add `@runtime_checkable` unless explicit runtime dispatch is needed. mypy strict mode enforces Protocol conformance statically. `[CITED: PEP 544]`
**Warning signs:** `@runtime_checkable` on every Protocol; profile shows time in `_ProtocolMeta.__instancecheck__`.

### Pitfall 9: Hypothesis fuzz runs too long in CI

**What goes wrong:** Default `max_examples=100` with deeply recursive strategies can run minutes; CI timeout.
**Why it happens:** Unbounded strategy composition (nested dicts of dicts of lists).
**How to avoid:** Explicit `@settings(max_examples=200, deadline=1000)`; bound recursive strategies with `max_size=5, max_leaves=20`. Profile once locally before committing.
**Warning signs:** CI test runtime jumps 5-10x; `hypothesis` reports `HealthCheck.too_slow`.

## Code Examples

Verified patterns from the existing codebase and official sources:

### Example 1: Frozen pydantic model pattern (already in use)

```python
# From src/alphaswarm/types.py:26-35  [VERIFIED: existing code]
class BracketConfig(BaseModel, frozen=True):
    """Configuration for a single bracket archetype."""
    bracket_type: BracketType
    display_name: str
    count: int = Field(ge=1, le=100)
    risk_profile: float = Field(ge=0.0, le=1.0)
    temperature: float = Field(ge=0.0, le=2.0)
    system_prompt_template: str
    influence_weight_base: float = Field(ge=0.0, le=1.0)
```

**Phase 37 addition:** For types crossing the ingestion↔swarm seam, add `extra="forbid"` via `model_config`:

```python
from pydantic import BaseModel, ConfigDict, Field

class MarketSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ticker: str
    # ... fields
```

### Example 2: Stdlib frozen dataclass pattern (already in use)

```python
# From src/alphaswarm/types.py:96-112  [VERIFIED: existing code]
import dataclasses

@dataclasses.dataclass(frozen=True)
class ParsedSeedResult:
    seed_event: SeedEvent
    parse_tier: int
```

**Phase 37 addition:** Reuse for `Holding` and `PortfolioSnapshot` (ISOL-01) — these don't cross the swarm seam, so stdlib-frozen is sufficient and keeps `alphaswarm/holdings/types.py` zero-dep.

```python
import dataclasses
from decimal import Decimal
from datetime import datetime

@dataclasses.dataclass(frozen=True)
class Holding:
    ticker: str
    qty: Decimal
    cost_basis: Decimal | None = None
    # ... NO holdings-shaped fields on ContextPacket elsewhere

@dataclasses.dataclass(frozen=True)
class PortfolioSnapshot:
    holdings: tuple[Holding, ...]
    as_of: datetime
    account_number_hash: str  # already-hashed per HOLD-02 policy
```

### Example 3: structlog processor insertion pattern

```python
# Based on existing src/alphaswarm/logging.py:15-21  [VERIFIED: existing code]
shared_processors: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.dev.set_exc_info,
    pii_redaction_processor,                    # NEW (Phase 37)
]
if json_output:
    shared_processors.append(structlog.processors.JSONRenderer())
else:
    shared_processors.append(structlog.dev.ConsoleRenderer())
```

`[CITED: https://www.structlog.org/en/stable/processors.html]` — "A processor is a callable that receives `(logger, method_name, event_dict)` and returns the modified `event_dict`. Raise `structlog.DropEvent` to discard an event entirely."

### Example 4: pytest pyproject.toml integration

```toml
# pyproject.toml — Phase 37 modifications

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--disable-socket"      # D-09: globally block all sockets
markers = [
    "enable_socket: opt-in marker for tests that need real network (D-12 escape hatch)",
]

[tool.importlinter]
root_package = "alphaswarm"

[[tool.importlinter.contracts]]
name = "Holdings isolation (whitelist-only; only advisory and web.routes.holdings may import alphaswarm.holdings)"
type = "forbidden"
source_modules = [
    # EVERY top-level importable module OTHER than the two allowed ones
    "alphaswarm.simulation",
    "alphaswarm.worker",
    "alphaswarm.batch_dispatcher",
    "alphaswarm.seed",
    "alphaswarm.parsing",
    "alphaswarm.ingestion",
    # ... complete list in planner's TOML
]
forbidden_modules = ["alphaswarm.holdings"]
```

**Note:** The `source_modules` list must be maintained as new top-level modules are added. Phase 37's `test_importlinter_contract.py` (D-03) catches the case where someone adds a new module but forgets to add it to `source_modules` — the test's synthetic violation must come from a NEW path, not a known one, so the test stays meaningful.

### Example 5: pytest-socket integration test escape hatch

```python
# tests/integration/conftest.py  [CITED: pytest-socket README]
import pytest

def pytest_collection_modifyitems(config, items):
    """D-12: auto-apply enable_socket marker to all tests in tests/integration/."""
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.enable_socket)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `class Config: extra = "forbid"` (pydantic v1) | `model_config = ConfigDict(extra="forbid")` (pydantic v2) | pydantic 2.0 (June 2023) | Project uses 2.12.5; must use v2 idiom |
| `asyncio.ensure_future(...)` + manual task tracking | `asyncio.TaskGroup` + structured concurrency | Python 3.11 | Already adopted in INFRA-07; Phase 37 canary test's simulation harness should use TaskGroup |
| Stdlib `logging` filters | structlog processors | structlog 20.x+ | Project standard; use processors for PII redaction, never `logging.Filter` |
| Manual `socket.socket` monkeypatch | `pytest-socket` | ~2019 | Marker-based opt-out with tracebacks preserved |
| `@runtime_checkable` on all Protocols | `@runtime_checkable` only when isinstance needed | PEP 544 refinements | Static mypy checks cover most use cases; skip runtime overhead |
| Regex-based architecture linting | `import-linter` contracts | ~2020 (v1.0) | Transitive import graph awareness; native pyproject.toml config |

**Deprecated/outdated:**
- `pandas-datareader` (use `yfinance` — Phase 38, not Phase 37)
- `newsapi-python` (use `httpx` directly — Phase 38)
- pydantic v1 `class Config:` syntax — hard error under pydantic v2 strict parsing

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ruff` does not have a first-class "module A must not import module B (transitively)" rule as of 2026-Q1 | Alternatives Considered | LOW — even if ruff adds one, import-linter is already the chosen tool per D-01; rework would be configuration-only, not architecture |
| A2 | pytest-socket 0.7.0 blocks localhost by default when `--disable-socket` is active (fetched from README said "not definitively stated in the provided content") | pytest-socket scope | MEDIUM — if loopback is NOT blocked by default, D-10 is not automatically satisfied. Planner must verify at implementation time with a unit test: `requests.get("http://127.0.0.1:65432/")` must raise `SocketBlockedError` under `--disable-socket` with no `--allow-hosts`. If it passes through, add explicit `--allow-hosts=` empty to force-block, or `--disable-socket --allow-hosts=""` |
| A3 | `@runtime_checkable` Protocol triggers measurable overhead | Pitfall 8 | LOW — general Python wisdom; even if overhead is small, the D-17 Protocols don't need runtime dispatch, so not-adding is correct regardless |
| A4 | `hashlib.sha256("").hexdigest()[:8]` collision risk on truncation is acceptable for 8-char correlation hashes | Pattern 2 | LOW — correlation is debug-only, not security-critical; birthday collisions at 8 hex chars (2^32 space) are manageable for N<10^4 accounts |
| A5 | Pydantic v2's `ConfigDict(frozen=True, extra="forbid")` performs both checks statically + at construction | Pattern 4 | LOW — well-documented pydantic v2 feature; failure mode would be immediate ValidationError on test construction |
| A6 | Adding `import-linter`, `pytest-socket`, `hypothesis` as dev deps does not interact with existing stack (no version conflicts) | Installation | LOW — all three are pure-Python, no C extensions shared with existing deps; uv's resolver will flag conflicts |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

This table is non-empty but all items are LOW or MEDIUM risk with clear verification paths during Phase 37 implementation. **A2 is the only item the planner should explicitly verify** before closing Phase 37.

## Open Questions

1. **How does pytest-socket 0.7.0 actually handle loopback when `--disable-socket` is set without `--allow-hosts`?**
   - What we know: D-10 requires loopback blocked by default. pytest-socket docs show `--allow-hosts` as opt-in allowlist, implying unlisted hosts are blocked.
   - What's unclear: The official README does not explicitly state "loopback is blocked by default."
   - Recommendation: Planner adds a first-task verification in Phase 37 — write a deliberately-failing test that hits `127.0.0.1` and assert `SocketBlockedError` is raised. If not, escalate to add `--allow-hosts=` empty or equivalent suppression.

2. **Where should `sha256_first8()` live?**
   - What we know: D-06 and HOLD-04 both use it; planner discretion per CONTEXT.md.
   - What's unclear: `alphaswarm/security/hashing.py` vs. `alphaswarm/holdings/redaction.py` vs. inline in `logging.py`.
   - Recommendation: `alphaswarm/security/hashing.py` — single well-named home, importable by both the redaction processor (ingestion-side) and HoldingsLoader (Phase 39). Keeps `alphaswarm/holdings/` free of any import except its own types and the shared security module. But: the importlinter whitelist says `holdings` can only be imported by advisory and web.routes.holdings — so `security` importing `holdings` is fine, but `holdings` importing `security.hashing` may need an `ignore_imports` allowlist entry (D-03 test should verify).

3. **Should the canary test run in Phase 37's regular test suite or be quarantined?**
   - What we know: D-16 marks the canary `@pytest.mark.enable_socket` because it touches Neo4j + WebSocket.
   - What's unclear: If Neo4j isn't running during unit-test CI, the canary will fail — should it be in `tests/integration/` instead of `tests/invariants/`?
   - Recommendation: Keep in `tests/invariants/` conceptually, but use dependency-injected fakes for Neo4j session and broadcaster (not real connections). The "four surfaces" (logs, Neo4j, WebSocket, prompts) can all be tested with in-process fakes; the integration-smoke version runs separately in Phase 43. This avoids Neo4j being a Phase 37 dependency.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.11+ (project requires; local verification pending) | — |
| `uv` | Package install | ✓ | project-installed | — |
| `pytest` | Test suite | ✓ | 8.0+ in dev deps | — |
| `structlog` | PII redaction | ✓ | 25.5.0 pinned | — |
| `pydantic` | Frozen types | ✓ | 2.12.5 pinned | — |
| `import-linter` | Contract enforcement | ✗ (new dep) | 2.11 to install | none — blocks ISOL-03 |
| `pytest-socket` | Network gate | ✗ (new dep) | 0.7.0 to install | none — blocks ISOL-06 |
| `hypothesis` | Fuzz testing | ✗ (new dep) | 6.152.1 to install | degraded — tabular-only tests for D-08, lose property-based coverage |
| Neo4j | Canary Q4.3 surface | opt-in | 5.x (Docker) | fake session for Phase 37; real Neo4j at Phase 43 |
| pre-commit | Hook runner | likely present | any | CI-only enforcement still satisfies D-02 partially |

**Missing dependencies with no fallback:**
- `import-linter` and `pytest-socket` — install via `uv add --dev` as the first task of Phase 37.

**Missing dependencies with fallback:**
- `hypothesis` — fall back to rich tabular cases only (degraded D-08 coverage); install is cheap so no real blocker.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 8.0+` + `pytest-asyncio 0.24+` (`asyncio_mode="auto"`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/invariants/ -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ISOL-01 | `Holding` / `PortfolioSnapshot` are frozen dataclasses, zero I/O | unit | `uv run pytest tests/test_holdings_types.py -x` | ❌ Wave 0 |
| ISOL-02 | `ContextPacket` / `MarketSlice` / `NewsSlice` reject extra keys at construction; are frozen; have zero holdings fields | unit | `uv run pytest tests/test_ingestion_types.py -x` | ❌ Wave 0 |
| ISOL-03 | `lint-imports` fails on a synthetic violation fixture; passes on clean tree | unit | `uv run pytest tests/invariants/test_importlinter_contract.py -x` | ❌ Wave 0 |
| ISOL-04 | structlog processor redacts `holdings`, `portfolio`, `cost_basis` keys; account_* → hash; fail-closed on raise | unit + fuzz | `uv run pytest tests/invariants/test_pii_redaction.py -x` | ❌ Wave 0 |
| ISOL-05 | `MarketDataProvider` / `NewsProvider` Protocol definitions exist; `FakeMarketDataProvider` / `FakeNewsProvider` conform structurally (mypy) | unit | `uv run pytest tests/test_providers.py -x && uv run mypy src/alphaswarm/ingestion/providers.py` | ❌ Wave 0 |
| ISOL-06 | Any `socket.socket` call in tests raises `SocketBlockedError`; `@pytest.mark.enable_socket` opt-out works | unit + meta | `uv run pytest tests/test_pytest_socket_gate.py -x` | ❌ Wave 0 |
| ISOL-07 | Sentinel strings do not appear in captured log output, Neo4j session writes, WebSocket frames, or rendered prompts across a minimal simulation | integration-ish (all fakes) | `uv run pytest tests/invariants/test_holdings_isolation.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/invariants/ -x` (target <5s runtime for invariant suite)
- **Per wave merge:** `uv run pytest` (full suite; currently ~193 tests + Phase 37 additions)
- **Phase gate:** Full suite green + `uv run lint-imports` green + `uv run mypy src/` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/invariants/__init__.py` — new directory marker
- [ ] `tests/invariants/conftest.py` — sentinel portfolio builder, log capture helper, WS intercept stub, Jinja render capture
- [ ] `tests/invariants/test_importlinter_contract.py` — synthetic-violation fixture + lint-imports programmatic call
- [ ] `tests/invariants/test_holdings_isolation.py` — four-surface canary
- [ ] `tests/invariants/test_pii_redaction.py` — hypothesis fuzz + tabular cases
- [ ] `tests/test_holdings_types.py` — ISOL-01 unit tests
- [ ] `tests/test_ingestion_types.py` — ISOL-02 unit tests (including `extra="forbid"` rejection)
- [ ] `tests/test_providers.py` — ISOL-05 Protocol conformance + fake behavior
- [ ] `tests/test_pytest_socket_gate.py` — smoke test confirming the gate actually blocks
- [ ] `tests/integration/__init__.py` + `tests/integration/conftest.py` — D-12 auto-marker hook
- [ ] Dev dep install: `uv add --dev import-linter==2.11 pytest-socket==0.7.0 hypothesis==6.152.1`
- [ ] `pyproject.toml` edits: `addopts = "--disable-socket"`, `[tool.importlinter]` stanza, marker declaration
- [ ] Redaction unit tests must include the positive-control pattern (Pitfall 6) — inject sentinel into each surface and assert capture sees it

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth surface in Phase 37) |
| V3 Session Management | no | — (no sessions introduced) |
| V4 Access Control | yes | `import-linter` forbidden contract — module-level access control on `alphaswarm.holdings` (whitelist of two allowed importers). Static analog of V4 principle of least privilege. |
| V5 Input Validation | yes | pydantic v2 `extra="forbid"` + `frozen=True` on all cross-boundary types (`ContextPacket`, `MarketSlice`, `NewsSlice`). Runtime validation at construction. |
| V6 Cryptography | limited | `hashlib.sha256` (stdlib) for correlation hashing of account numbers. Not authentication; truncation to 8 hex chars is acceptable for correlation only. Never hand-roll crypto. |
| V7 Error Handling / Logging | yes | PII redaction processor (D-05/D-06/D-07) in structlog chain. Fail-closed on redaction exception (D-07). Pattern: detect sensitive keys → redact values → emit marker on exception, never render raw PII. |
| V8 Data Protection | yes | Holdings never persisted (in-memory-only invariant, future HOLD-03). Phase 37 scaffolds the static + runtime defenses that HOLD-03 depends on. |

### Known Threat Patterns for {local-first multi-agent LLM / FastAPI + structlog stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Holdings leak into swarm prompts (Jinja template) | Information Disclosure | Defense-in-depth: importlinter forbids `holdings` imports in template-touching modules + ContextPacket `extra="forbid"` + canary test asserts sentinel never appears in rendered prompts |
| Holdings leak into structlog JSON output | Information Disclosure | PII redaction processor on sensitive keys (D-05); value-pattern backstop (currency, SSN); fail-closed on processor raise (D-07); fuzz-tested (D-08) |
| Holdings leak into WebSocket frame | Information Disclosure | WS frame intercept in canary test (D-15); explicit allowlist serializer pattern (future ADVUI-04); no `PortfolioSnapshot` reachable from broadcaster module (importlinter contract) |
| Holdings leak into Neo4j property | Information Disclosure / Tampering | Future HOLD-08 asserts no `:Holding` / `:Position` label exists; canary scans all node properties for sentinel |
| Prompt injection from seed rumor altering advisory behavior | Tampering | Future ADV-03 (Jinja system/instruction/user separation). Phase 37 scaffolds `ContextPacket` as the typed seam; rumor-as-data boundary is Phase 41's concern |
| Test suite hits real APIs in CI, leaks real keys | Information Disclosure | `pytest-socket --disable-socket` (D-09) globally blocks; escape hatch via marker only in `tests/integration/` |
| CI bypass via `git commit --no-verify` skipping pre-commit | Elevation of Privilege / Tampering | D-02 requires BOTH pre-commit AND CI enforcement; CI is the authoritative gate |
| Silent import of `alphaswarm.holdings` by new module added after Phase 37 | Information Disclosure | `source_modules` list is maintained; `test_importlinter_contract.py` (D-03) synthetic-violation fixture catches the "developer added a module but forgot to add to source_modules" case with a meta-test |

## Sources

### Primary (HIGH confidence)
- Existing codebase — `src/alphaswarm/types.py`, `src/alphaswarm/logging.py`, `pyproject.toml`, `tests/conftest.py` — pattern verification
- `.planning/research/ARCHITECTURE.md` §Q3 "Where does the holdings boundary live?" (lines 151–192) — importlinter ADR, three-layer defense-in-depth
- `.planning/research/STACK.md` §"Info-isolation enforcement" (lines 146–148), §"What NOT to Use" (lines 170–184) — frozen dataclass guidance, anti-patterns
- `.planning/research/SUMMARY.md` §"Phase 37 — Isolation Foundation & Provider Scaffolding" (lines 157–172) — authoritative delivers list
- `.planning/research/PITFALLS.md` — Pitfalls 1, 2, 10, 11 are scaffolded by this phase
- PyPI JSON API (verified today 2026-04-18): import-linter 2.11, pytest-socket 0.7.0, hypothesis 6.152.1, structlog 25.5.0
- `[CITED: https://import-linter.readthedocs.io/en/v2.9/contract_types/forbidden/]` — forbidden contract TOML syntax
- `[CITED: https://www.structlog.org/en/stable/processors.html]` — processor signature, DropEvent semantics, chain ordering
- `[CITED: https://github.com/miketheman/pytest-socket]` — --disable-socket, --allow-hosts, @pytest.mark.enable_socket

### Secondary (MEDIUM confidence)
- `[VERIFIED via search]` import-linter pyproject.toml syntax (github.com/seddonym/import-linter)
- `[CITED: PEP 544]` Protocol + runtime_checkable semantics

### Tertiary (LOW confidence — flagged in Assumptions Log)
- pytest-socket loopback default behavior (assumption A2 — verify at implementation time)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all three new deps versions + release dates confirmed via live PyPI JSON today
- Architecture: HIGH — grounded in existing codebase patterns (frozen pydantic, structlog processor chain, stdlib frozen dataclass) and CONTEXT.md locks 20 decisions
- Pitfalls: HIGH — enumerated from actual implementation trap patterns for each library; Pitfall 6 (canary trivially passes) is the highest-priority watch item
- Security: HIGH — ASVS V4/V5/V6/V7/V8 map cleanly onto the four-layer defense-in-depth
- Open questions: 3 questions, all LOW/MEDIUM risk, all with concrete verification paths

**Research date:** 2026-04-18
**Valid until:** 2026-05-18 (30 days — pinned versions are stable, but pytest-socket is 18 months old and a 0.8 release could change API)

---

*Research complete. Planner may proceed to `/gsd-plan-phase 37`.*
