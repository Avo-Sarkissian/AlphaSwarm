# Phase 37: Isolation Foundation & Provider Scaffolding - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the frozen type boundaries, import contracts, network gates, PII redaction, and canary test scaffold that every downstream v6.0 phase inherits — before any ingestion, holdings, or advisory code exists. No business logic, no provider implementations, no UI work. Outputs: type modules, `importlinter` contract, `pytest-socket` gate, structlog PII redaction processor, Protocol definitions, Fake providers for tests, and the canary invariant test.

</domain>

<decisions>
## Implementation Decisions

### importlinter contract shape
- **D-01:** Contract type is **`forbidden`** (not layered). Matches research ADR sketch at `research/ARCHITECTURE.md:163` verbatim; minimum-viable isolation with low maintenance.
- **D-02:** Enforcement at **CI + pre-commit hook**. Pre-commit gives fast local feedback (~1s); CI is the authoritative gate.
- **D-03:** Permanent unit test `tests/invariants/test_importlinter_contract.py` invokes `lint-imports` programmatically on a synthetic violating module fixture and asserts exit code ≠ 0. Self-documenting regression guard for anyone loosening the contract later.
- **D-04:** **Whitelist-only scope** — `alphaswarm.holdings` may be imported by **only** `alphaswarm.advisory` and `alphaswarm.web.routes.holdings`. All other modules (simulation, worker, batch_dispatcher, seed, parsing, ingestion, web.routes.*, graph, report, cli, tui) are forbidden importers. Strongest posture; matches Option A invariant ("HoldingsStore has exactly one consumer: AdvisoryPipeline").

### PII redaction strategy
- **D-05:** **Key-first + value-pattern backstop** detection. Primary allowlist of sensitive keys: `holdings`, `portfolio`, `positions`, `cost_basis`, `account_number`, `account_id`, `qty`, `shares`. Secondary regex backstop for currency patterns (`$12,345.67`) + SSN-like sequences on remaining string values.
- **D-06:** **Mixed redaction markers** — `account_*` fields replaced with SHA256 first-8-char hash (enables debug correlation, matches HOLD-04 hashing policy); all other sensitive fields replaced with literal `"[REDACTED]"`.
- **D-07:** Processor **fails closed** — if redaction raises, drop the log event entirely and emit a single `redaction_failed` marker event with no user data. Fail-open defeats the invariant; fail-hard crashes simulation over log bugs.
- **D-08:** Fuzz test combines **Hypothesis property-based generation** (random dicts with mixed sensitive/safe keys; assert no sensitive values render verbatim) + **tabular scenarios** (nested dicts, lists of holdings, positional args, f-string interpolation) for regression lock-in.

### pytest-socket scope
- **D-09:** **Block all outbound sockets globally** via `--disable-socket` in `[tool.pytest.ini_options]`. Single policy, no env-conditional behavior.
- **D-10:** **No loopback allowance** — localhost/127.0.0.1/::1 also blocked by default. Integration tests (Neo4j, Ollama) must opt in explicitly.
- **D-11:** **Unix sockets blocked** (pytest-socket default). No current dependency requires them (Neo4j bolt://, Ollama HTTP).
- **D-12:** Escape hatch via **directory-wide marker** in `tests/integration/conftest.py` auto-applying `@pytest.mark.enable_socket` to all tests in that tree, plus **explicit `@pytest.mark.enable_socket`** for one-off exceptions outside `tests/integration/`.

### Canary test design
- **D-13:** **ASCII string sentinels** — `ticker="SNTL_CANARY_TICKER"`, `account_number="SNTL_CANARY_ACCT_000"`, `cost_basis=Decimal("999999.99")`, `qty=Decimal("77.7777")`. Greppable in logs, prompts, Neo4j properties, WebSocket frames without tooling.
- **D-14:** Phase 37 canary **runs a minimal simulation** (empty seed, no advisory path) with sentinel `PortfolioSnapshot` constructed, then asserts sentinel strings do not appear in any captured surface. Trivially passes at Phase 37 (no holdings code path exists), becomes load-bearing at Phase 41 when advisory activates the join point.
- **D-15:** **Leak detection across all four surfaces**: structlog output capture, Neo4j node/relationship property scan, WebSocket broadcaster frame intercept, and rendered worker prompt strings. Matches PROJECT.md invariant verbatim ("holdings never in any swarm prompt, Neo4j node, or WebSocket frame").
- **D-16:** Test lives at `tests/invariants/test_holdings_isolation.py` — new `tests/invariants/` directory signals "architectural invariants, not feature tests". Phase 37 also creates the directory convention for future invariant tests (schema-assertion, log-grep, etc.). Marked with `@pytest.mark.enable_socket` since Q4.3 surfaces touch Neo4j + WebSocket.

### Provider Protocol granularity
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project invariants
- `.planning/PROJECT.md` — v6.0 Option A architecture lock; information isolation invariant; hardware + async constraints
- `.planning/REQUIREMENTS.md` §ISOL-01 through §ISOL-07 — the seven acceptance-tracked requirements this phase satisfies
- `.planning/ROADMAP.md` §"Phase 37: Isolation Foundation & Provider Scaffolding" — goal, success criteria, complexity note

### Architecture & research
- `.planning/research/ARCHITECTURE.md` §"Q3. Where does the holdings boundary live?" (lines 151–189) — importlinter ADR sketch, invariant test contract, log-grep CI gate rationale
- `.planning/research/STACK.md` §"Info-isolation enforcement" (lines 146–148) + §"Pitfalls" (line 179) — frozen dataclass guidance, Neo4j-holdings anti-pattern
- `.planning/research/SUMMARY.md` §"Phase 37 — Isolation Foundation & Provider Scaffolding" (lines 157–172) — authoritative delivers list, pitfalls cross-reference
- `.planning/research/PITFALLS.md` — Pitfalls 1, 2, 10, 11 are scaffolded by this phase

### Existing codebase (integration points)
- `src/alphaswarm/logging.py` — structlog `configure_logging()` processor chain; PII redaction must insert before the terminal renderer (JSONRenderer / ConsoleRenderer on lines 24–26)
- `src/alphaswarm/types.py` — existing frozen pydantic `BaseModel(frozen=True)` pattern (BracketConfig, AgentPersona); reuse the convention for `ContextPacket`, `MarketSlice`, `NewsSlice`
- `pyproject.toml` — dependency additions (`import-linter`, `pytest-socket`, `hypothesis`), `[tool.pytest.ini_options]` changes, `[tool.importlinter]` stanza

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **structlog processor chain** (`src/alphaswarm/logging.py:15–21`): `shared_processors` list is the insertion point for the PII redaction processor. Must slot after `merge_contextvars` and `add_log_level` but before the terminal renderer (`JSONRenderer` / `ConsoleRenderer`).
- **Frozen pydantic pattern** (`src/alphaswarm/types.py:26–47`): `BracketConfig`, `AgentPersona` use `BaseModel, frozen=True` with `Field(...)` validation. Re-use for `ContextPacket`, `MarketSlice`, `NewsSlice` (`extra="forbid"` is the v6.0 addition).
- **Stdlib `@dataclass(frozen=True)` import** (`src/alphaswarm/types.py:5`): already imported; ISOL-01 `Holding` / `PortfolioSnapshot` use stdlib frozen dataclasses (research STACK.md:119–146 sketch).
- **pytest-asyncio configured** (`pyproject.toml:[tool.pytest.ini_options] asyncio_mode = "auto"`): async fixtures and tests work without per-test decoration.
- **mypy strict** (`pyproject.toml:[tool.mypy] strict = true`): all new Protocol definitions must be fully typed; Protocol runtime_checkable only if reflection is actually used.

### Established Patterns
- **Module naming**: top-level modules under `src/alphaswarm/{module}.py` (flat) or `src/alphaswarm/{subpackage}/` (subpackage). v6.0 introduces new subpackages: `alphaswarm/holdings/`, `alphaswarm/ingestion/`, `alphaswarm/advisory/`.
- **Test layout**: `tests/test_{module}.py` for units, `tests/test_{module}_integration.py` for integration (e.g., `test_graph_integration.py`). Phase 37 introduces `tests/invariants/` as a new category.
- **Error types**: centralized in `src/alphaswarm/errors.py` — add new exception classes there, not scattered.
- **Config**: `src/alphaswarm/config.py` (pydantic-settings). New isolation/provider config sections added here.

### Integration Points
- `alphaswarm/holdings/types.py` (new) — `Holding`, `PortfolioSnapshot` stdlib frozen dataclasses. Zero I/O; pure types.
- `alphaswarm/ingestion/types.py` (new) — `ContextPacket`, `MarketSlice`, `NewsSlice` pydantic `BaseModel(frozen=True, extra="forbid")`. Zero holdings fields.
- `alphaswarm/ingestion/providers.py` (new) — `MarketDataProvider`, `NewsProvider` `typing.Protocol` definitions + `FakeMarketDataProvider`, `FakeNewsProvider` test fakes.
- `alphaswarm/logging.py` (modified) — insert PII redaction processor into `shared_processors` list before the terminal renderer.
- `pyproject.toml` (modified) — add `import-linter`, `pytest-socket`, `hypothesis` to dev deps; add `[tool.importlinter]` stanza; add `--disable-socket` to pytest options.
- `.pre-commit-config.yaml` (likely new) — add `lint-imports` hook.
- `tests/invariants/` (new directory) — `__init__.py`, `conftest.py` (sentinel fixtures + capture helpers), `test_importlinter_contract.py`, `test_holdings_isolation.py`.
- `tests/integration/` (may be new directory if not already present) — `conftest.py` auto-applying `enable_socket` marker.

</code_context>

<specifics>
## Specific Ideas

- "Whitelist-only" importlinter scope (D-04) is the strongest expression of the Option A architecture — only `advisory` and `web.routes.holdings` may touch `alphaswarm.holdings`. This is stricter than the research ADR sketch's forbidden-modules list; a deliberate strengthening.
- The canary test (`tests/invariants/test_holdings_isolation.py`) must exercise **all four leak surfaces** — logs, Neo4j, WebSocket, rendered prompts — even at Phase 37 when it trivially passes. Building the detection machinery now makes Phase 41's join-point activation a one-line change.
- PII redaction account-number hashing (D-06) must use the same SHA256 function Phase 39's HOLD-04 will use — extract it into shared infrastructure (likely `alphaswarm/security/hashing.py`) during Phase 37 so Phase 39 inherits it.
- `FakeMarketDataProvider` / `FakeNewsProvider` (D-20) should accept canary-sentinel tickers and return sentinel-friendly responses so Phase 37's invariant test can exercise the full provider → ContextPacket → worker prompt path without network.

</specifics>

<deferred>
## Deferred Ideas

- **Log-grep CI gate** (`research/ARCHITECTURE.md:189`) — a cruder `grep -r "holdings\|portfolio" src/alphaswarm/templates/ worker.py simulation.py` in CI as a belt-and-suspenders check beyond importlinter. Useful but redundant with D-04 whitelist; defer unless the whitelist proves porous.
- **Layered importlinter contract** — add later if new top-level modules accumulate faster than the whitelist can be maintained. Phase 37 sticks with `forbidden` (D-01).
- **`_NotImplementedYetProvider` sentinel** — explicit "turn on in Phase 38" guard on the settings default provider. Not added (D-20 picks Option 2). Revisit if Phase 38 test scaffolding wants to assert "real provider not yet wired".
- **Runtime schema assertion for `ContextPacket`** — extra paranoia (e.g., `pytest` hook that introspects every ContextPacket instance for holdings-shaped keys). Pydantic `extra="forbid"` already covers the static case.

</deferred>

---

*Phase: 37-isolation-foundation-provider-scaffolding*
*Context gathered: 2026-04-18*
