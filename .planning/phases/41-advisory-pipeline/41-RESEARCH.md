# Phase 41: Advisory Pipeline — Research

**Researched:** 2026-04-19
**Domain:** Post-simulation orchestrator synthesis joining portfolio holdings to bracket consensus; FastAPI async 202/polling endpoint; Vue 3 full-screen modal; ISOL-07 canary activation
**Confidence:** HIGH

## Summary

Phase 41 is the capstone of the v6.0 milestone. The engineering problem is small and well-constrained: compose six pieces that already exist in the codebase (Phase 36 report async pattern, Phase 15 Neo4j read tools, Phase 39 `PortfolioSnapshot`, Phase 37 importlinter whitelist + canary, Phase 36 ReportViewer Vue modal, Phase 40 ContextPacket tickers) into a single new vertical. CONTEXT.md locks 20 of 25 decisions; the planner's job is near-mechanical stitching plus three pieces of synthesis work (LLM prompt template, structured JSON schema, and the canary flip).

The single open technical risk is **structured output reliability**. The orchestrator must produce JSON in a specific shape (ranked `AdvisoryItem` list + `portfolio_outlook` narrative) containing Decimal-string values. Ollama `>=0.5` supports pydantic-derived JSON Schema in the `format=` parameter, and the existing `OllamaClient.chat(format=...)` signature already passes `str | dict` through. This is the first place in the codebase to use schema-mode rather than plain `format="json"` — the planner must decide whether to adopt schema mode here or stay with `format="json"` + pydantic post-validation retry (cheaper to implement, one fewer moving part).

**Primary recommendation:** Execute CONTEXT.md D-01 through D-20 verbatim. Use plain `format="json"` with a strict pydantic `BaseModel(frozen=True)` parse on the response content; on ValidationError, retry once with the error embedded in the user message, then fail the synthesis task (done_callback captures). Mirror `web/routes/report.py` line-for-line for the endpoint shape — do not reinvent the 202/polling/done_callback pattern. For the canary flip, swap `_minimal_simulation_body` for a thin harness that calls `synthesize()` with the sentinel `PortfolioSnapshot` against in-memory captures (no real Neo4j, no real Ollama — the canary is about code paths, not service integration).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Ticker-Entity Correlation**
- **D-01:** Match holdings tickers against ContextPacket tickers first (the tickers explicitly fetched by `YFinanceMarketDataProvider` during the simulation run). If `app.state.market_context_tickers` (or equivalent stored set) is available post-simulation, use it as the primary scope signal.
- **D-02:** Fallback for unmatched holdings (ticker not in ContextPacket scope): apply the global Round 3 consensus signal (BUY/SELL/HOLD counts from `read_consensus_summary`) as the signal. Position still appears in the advisory output with lower confidence.
- **D-03:** Final impact determination is delegated to the orchestrator LLM — not a programmatic rule. The LLM receives the full swarm context + portfolio and decides which holdings are genuinely affected by the simulation's seed rumor. Positions the LLM determines as unaffected are omitted from the ranked output.

**Synthesis Approach**
- **D-04:** Pre-fetch all swarm data programmatically from Neo4j before the LLM call: `bracket_summary`, `entity_impact`, `bracket_narratives`, `round_timeline`, seed rumor text.
- **D-05:** Single orchestrator LLM call — one prompt containing all prefetched swarm data + serialized portfolio holdings (ticker, qty, cost_basis). LLM outputs (1) a list of `AdvisoryItem` records for affected holdings (structured JSON) and (2) a `portfolio_outlook` narrative paragraph (1-3 paragraphs). Unaffected holdings simply absent from the JSON.
- **D-06:** `AdvisoryItem` schema:
  - `ticker: str`
  - `consensus_signal: "BUY" | "SELL" | "HOLD"`
  - `confidence: float (0.0–1.0)`
  - `rationale_summary: str` (1-2 sentences)
  - `position_exposure: Decimal` (total cost_basis for this holding)
- **D-07:** Ranking: `score = confidence × (position_exposure / total_portfolio_cost_basis)`. Highest combined signal strength + portfolio weight ranks first.
- **D-08:** Orchestrator lifecycle: `load_model → synthesis → unload_model` in a `finally` block. Matches the report pattern exactly. Advisory synthesis must never run concurrently with agent interviews or report generation (ADVIS-02 serialization requirement). Check `app.state.report_task` and any active `interview` before spawning the advisory task.

**Endpoint Response Pattern**
- **D-09:** `POST /api/advisory/{cycle_id}` → 202 Accepted immediately. Spawns background asyncio Task (same pattern as `POST /api/report/{cycle_id}/generate`). Returns `{"status": "accepted", "cycle_id": cycle_id}`.
- **D-10:** `GET /api/advisory/{cycle_id}` → reads `advisory/{cycle_id}_advisory.json` from disk. Returns 200 with advisory payload, 404 if not generated yet, 500 if background task failed (done_callback pattern from Phase 36).
- **D-11:** Advisory JSON written to `advisory/{cycle_id}_advisory.json`. Directory created if absent. Persistent across server restarts (no regeneration required on refresh).
- **D-12:** `_CYCLE_ID_RE` path traversal guard (reuse from `web/routes/report.py`) applied to both endpoints.
- **D-13:** Done-callback on the advisory asyncio Task captures failures into `app.state.advisory_generation_error[cycle_id]` (same pattern as `app.state.report_generation_error`). GET endpoint surfaces 500 on recorded failure so the frontend can stop polling.

**Advisory Panel Layout (Vue)**
- **D-14:** Full-screen modal — same chrome as `ReportViewer.vue` (backdrop + centered modal, Escape/backdrop-click to close). Modal size: 80vw × 80vh, capped at 1200px × 900px.
- **D-15:** ControlBar trigger: "Advisory" button in the `isComplete` template block alongside the existing "Report" button. Button style: same as `.control-bar__btn--report`. Emits `open-advisory-panel` event; App.vue owns the `showAdvisoryPanel` ref.
- **D-16:** Modal content layout (top to bottom): Header ("Advisory — {cycle_id[:8]}" + Analyze button + × close), narrative block (`portfolio_outlook`), 1px divider, ranked table (TICKER | SIGNAL | CONF | EXPOSURE | RATIONALE), footer ("N of M positions affected" + Analyze button).
- **D-17:** Only affected holdings in the table. Footer shows "{N} of {total_holdings} positions affected by this simulation."
- **D-18:** Signal cell color coding: BUY → `var(--color-accent)`, SELL → `var(--color-destructive)`, HOLD → `var(--color-text-secondary)`.
- **D-19:** Advisory panel has independent `viewState` and `isAnalyzing` flags (REVISION-1 pattern from ReportViewer — never conflate generation status with view rendering state).

**ISOL-07 Canary Activation**
- **D-20:** Phase 41 replaces `tests/invariants/test_holdings_isolation.py::_minimal_simulation_body` stub with a real `synthesize()` call using the sentinel `PortfolioSnapshot` (SNTL_CANARY_TICKER, SNTL_CANARY_ACCT_000, etc.). The canary asserts sentinel values do NOT appear in logs, Neo4j properties, WebSocket frames, or agent prompts after advisory synthesis runs.

### Claude's Discretion
- Exact Cypher query shape for prefetching `entity_impact` and `bracket_narratives` (reuse existing graph methods from `report.py` tool registry)
- LLM prompt template for the advisory synthesis call (system + user message structure)
- JSON parsing/validation of the LLM's structured advisory output (Pydantic model or dataclass)
- Exact `portfolio_outlook` display typography in the modal (font-size, line-height — follow existing `ReportViewer` prose styles)
- Whether `advisory_task` is stored on `app.state` or a separate dict keyed by `cycle_id`

### Deferred Ideas (OUT OF SCOPE)
- Per-bracket advisory breakdown (e.g., "Quants say SELL, Whales say BUY on NVDA")
- Advisory history across multiple cycles (compare how recommendations changed over time)
- Export advisory to PDF or CSV
- Re-fetch live market prices at advisory synthesis time for fresh prices — Phase 40's ContextPacket prices already recent enough
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADVIS-01 | `alphaswarm.advisory.synthesize(cycle_id, portfolio)` joins final-round bracket consensus signals against holdings tickers, returns ranked `AdvisoryItem` list | Integration Points section; Neo4j prefetch composition via existing `graph.read_consensus_summary / read_entity_impact / read_bracket_narratives / read_round_timeline`; ranking formula D-07. Plan 41-01. |
| ADVIS-02 | `POST /api/advisory/{cycle_id}` triggers synthesis; uses orchestrator model with lifecycle serialization (no concurrent interviews/report generation) | Web app patterns section; mirror `_run_report_generation` load/unload finally block; 409 guard checking `app.state.report_task` + active interviews; done_callback pattern for failure capture. Plan 41-02. |
| ADVIS-03 | Vue `AdvisoryPanel.vue` renders advisory post-simulation; ISOL-07 canary activates confirming zero holdings leakage through all four surfaces | Vue front-end patterns section (REVISION-1 dual-flag); canary flip in `tests/invariants/test_holdings_isolation.py`. Plans 41-02 (canary) and 41-03 (Vue). |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Async-only:** All synthesis I/O, disk I/O, and LLM calls via asyncio — no blocking calls in the event loop (Hard Constraint 1). `aiofiles` for disk, `OllamaClient.chat()` for inference, Neo4j async driver for reads.
- **Local inference only:** Orchestrator model tag is `app_state.settings.ollama.orchestrator_model_alias`. No cloud APIs.
- **Max 2 models loaded:** Advisory must unload the orchestrator in `finally` (matches report pattern). Serialization with report generation (D-08) enforces the 2-model ceiling under simultaneous user actions.
- **Memory safety:** Advisory synthesis is a single-shot LLM call (no ReACT loop), so it does not hold model resources beyond the one inference. No additional governor changes needed.
- **WebSocket cadence:** Advisory generation does NOT broadcast WS frames — that's intentional. ISOL-07 depends on it.
- **Strict typing (mypy strict):** All new types fully typed. `AdvisoryItem` MUST be frozen (pydantic `BaseModel(frozen=True)` per D-06 and existing codebase conventions).
- **Conventions:** Project uses `structlog` (component-scoped logger), `pytest-asyncio` `asyncio_mode = "auto"`, `pytest-socket --disable-socket` global gate (advisory unit tests MUST use Fakes).

## Standard Stack

### Core (already installed; no new dependencies)
| Library | Version (from `uv.lock`) | Purpose | Why Standard |
|---------|--------------------------|---------|--------------|
| `pydantic` | 2.12.5 [VERIFIED: uv.lock:1212] | `AdvisoryItem` / `AdvisoryReport` frozen typed JSON boundary | Matches ISOL-02 pattern (`ContextPacket`); `BaseModel(frozen=True, extra="forbid")` gives drift barrier |
| `ollama` (python client) | 0.6.1 [VERIFIED: uv.lock:1040] | Orchestrator LLM call via existing `OllamaClient` wrapper | `format` param accepts `str \| dict \| None` — plain `"json"` mode already used in `worker.py:102` and `seed.py:69` |
| `neo4j` (async driver) | ≥5.28 <6.0 [VERIFIED: pyproject.toml:13] | Prefetch bracket / entity / timeline / narratives | Already wired via `app_state.graph_manager`; four read methods exist and return plain `dict` / `list[dict]` |
| `aiofiles` | ≥25.1.0 [VERIFIED: pyproject.toml:16] | Async write of `advisory/{cycle_id}_advisory.json`; async existence/stat checks | Already used in `report.py:write_report` and `web/routes/report.py` for non-blocking I/O (T-36-14) |
| `fastapi` | ≥0.115.0 [VERIFIED: pyproject.toml:17] | `APIRouter` with POST/GET advisory endpoints | Exact parity with `web/routes/report.py` |
| `structlog` | ≥25.5.0 [VERIFIED: pyproject.toml:9] | Component-scoped logging (`component="advisory"`) | Project-wide convention; PII redaction processor auto-applies |
| Vue 3 + TypeScript | per `frontend/package.json` | `AdvisoryPanel.vue` full-screen modal | Direct pattern reuse from `ReportViewer.vue` |

### Supporting (code reuse, no new packages)
| Existing Module | Purpose | When to Use |
|-----------------|---------|-------------|
| `alphaswarm.holdings` | `PortfolioSnapshot`, `Holding` frozen types | ONLY importable from `alphaswarm.advisory` per importlinter whitelist |
| `alphaswarm.graph.GraphStateManager` | `read_consensus_summary`, `read_entity_impact`, `read_bracket_narratives`, `read_round_timeline` | All four called before the LLM; serializable result handed as JSON-rendered context |
| `alphaswarm.ollama_models.ModelManager` | `load_model` / `unload_model` with internal `asyncio.Lock` | Wrap synthesis body in `try/finally` (D-08) |
| `alphaswarm.web.routes.report` | `_validate_cycle_id` + `_CYCLE_ID_RE` path-traversal guard | Import and reuse — do not re-declare the regex |
| `alphaswarm.security.hashing.sha256_first8` | First-8 char SHA256 | Only referenced for canary assertions; not invoked by synthesize |

### Alternatives Considered
| Instead of | Could Use | Tradeoff | Decision |
|------------|-----------|----------|----------|
| Plain `format="json"` + pydantic validate | Ollama structured outputs (`format=<JSON Schema>` object) | Schema mode is newer (Ollama 0.5+); guarantees shape at inference time; costs one extra field in the request and makes local debugging harder (LLM refuses to stray from schema even when it should error out) | [RECOMMENDATION] Stay with `format="json"` + pydantic parse for parity with `worker.py` and `seed.py`. One retry on `ValidationError` with the validation error text appended to user message. Surface remaining failure via done_callback. [ASSUMED] Model compliance with plain JSON mode is already battle-tested in-project at 100 agents × 3 rounds. |
| ReACT engine pattern (like `report.py`) | Single prompt containing all prefetched data | ReACT is overkill — advisory needs one LLM decision, not multi-turn reasoning. Single prompt is simpler, faster, lower memory | [LOCKED by D-04/D-05] Single call with all context inlined. |
| `asyncio.Lock` on `app.state.orchestrator_lock` | Reuse `app.state.report_task` + existence check | A dedicated Lock is cleaner in principle but requires new state surface and changes to report.py; existing `ModelManager._lock` already serializes model load/unload | [LOCKED by D-08] Guard with existence+done() check against `report_task` and any active interview session; orchestrator's internal `_lock` handles the rest. |
| Store advisory result in Neo4j | Write to `advisory/{cycle_id}_advisory.json` on disk | Neo4j would violate ISOL-07 canary (holdings data lands in graph) — MUST write to disk only | [LOCKED by D-11 + ISOL-07] Disk-only persistence. Never write portfolio data to graph. |

**Installation:** No new Python dependencies. No new Node packages. All work is composition of existing stack.

**Version verification:**
```bash
uv run python -c "import pydantic, ollama, fastapi, aiofiles, structlog; print(pydantic.VERSION, ollama.__version__)"
# pydantic 2.12.5, ollama 0.6.1 — [VERIFIED against uv.lock]
```

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
├── advisory/              # NEW — ONLY permitted holdings importer besides web.routes.holdings
│   ├── __init__.py        # re-exports synthesize + AdvisoryReport + AdvisoryItem
│   ├── types.py           # AdvisoryItem, AdvisoryReport (frozen pydantic BaseModel)
│   └── engine.py          # synthesize() — prefetch + single LLM call + JSON parse + rank
└── web/routes/
    └── advisory.py        # NEW — POST/GET endpoints mirroring report.py
frontend/src/components/
└── AdvisoryPanel.vue      # NEW — full-screen modal mirroring ReportViewer.vue
tests/
├── unit/test_advisory_synthesize.py      # NEW — Fake Ollama + Fake GraphManager
├── integration/test_advisory_endpoint.py # NEW — spawn task + poll GET
└── invariants/test_holdings_isolation.py # MODIFIED — flip canary to real synthesize
```

### Pattern 1: Async 202 + Polling + Done-Callback (Phase 36)
**What:** POST spawns a background `asyncio.create_task`, returns 202 immediately. The task writes a file to disk as the success signal. A `done_callback` captures exceptions into `app.state.advisory_generation_error[cycle_id]` so GET can return 500 instead of the frontend polling to a 10-minute timeout.
**When to use:** Every long-running orchestrator task (phase 36 report, now phase 41 advisory).
**Example — mirror this exactly:**
```python
# Source: src/alphaswarm/web/routes/report.py:215-223 [VERIFIED: codebase]
task = asyncio.create_task(_run_advisory_synthesis(app_state, cycle_id, portfolio))
request.app.state.advisory_task = task
app_ref = request.app
task.add_done_callback(
    lambda t: _on_advisory_task_done(t, cycle_id, app_ref),
)
```

### Pattern 2: Frozen pydantic boundary types (ISOL-02 convention)
**What:** `BaseModel(frozen=True, extra="forbid")` with `tuple[...]` collection fields and `Decimal` for money. Reject unknown keys at runtime; static mypy rejects attribute drift.
**When to use:** Every new data type crossing a process boundary (disk, HTTP, LLM).
**Example:**
```python
# Source: pattern from src/alphaswarm/ingestion/types.py:83 [VERIFIED: codebase]
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Signal = Literal["BUY", "SELL", "HOLD"]

class AdvisoryItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ticker: str
    consensus_signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_summary: str
    position_exposure: Decimal

class AdvisoryReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle_id: str
    generated_at: datetime
    portfolio_outlook: str
    items: tuple[AdvisoryItem, ...] = Field(default_factory=tuple)
    total_holdings: int
    affected_holdings: int
```

### Pattern 3: Load→work→unload in `try/finally` (Phase 36 + 15)
**What:** Model lifecycle bounded by `finally` so crashes don't leak the orchestrator lock.
**When to use:** Every orchestrator-model call in an async task.
**Example:**
```python
# Source: src/alphaswarm/web/routes/report.py:310-382 [VERIFIED: codebase]
async def _run_advisory_synthesis(
    app_state: AppState, cycle_id: str, portfolio: PortfolioSnapshot,
) -> None:
    orchestrator = app_state.settings.ollama.orchestrator_model_alias
    try:
        await app_state.model_manager.load_model(orchestrator)
        # ... prefetch, prompt, inference, parse, rank, write to disk ...
    finally:
        try:
            await app_state.model_manager.unload_model(orchestrator)
        except Exception:
            log.warning("orchestrator_unload_failed", cycle_id=cycle_id)
```

### Pattern 4: Vue REVISION-1 dual-flag state machine (Phase 36)
**What:** `viewState` ∈ {loading, empty, rendered} is independent from `isAnalyzing` boolean. A 404 during polling keeps the "analyzing" chrome active; only 200 transitions to `rendered`, and only a 500 or timeout resets to empty.
**When to use:** Any modal that both triggers a backend job AND displays its result.
**Anti-pattern avoided:** Treating "generating" as a `viewState` value — a single-poll 404 would then flash the empty state back (Codex HIGH T-36-17 on Phase 36).

### Pattern 5: Importlinter whitelist for holdings (Phase 37)
**What:** `pyproject.toml` `[tool.importlinter]` forbidden contract with `source_modules = [...long list...]` and `forbidden_modules = ["alphaswarm.holdings"]`. `ignore_imports` whitelist entries for the two permitted importers.
**When to use:** Checking whether advisory's imports break the contract (they should NOT — advisory is whitelisted; see "Importlinter whitelist status" below).
**Verification:** `uv run lint-imports` MUST exit 0 after Phase 41 changes.

### Anti-Patterns to Avoid
- **Do NOT pass `PortfolioSnapshot` into the LLM prompt as a raw repr.** Serialize to a minimal ticker/qty/cost_basis dict; do not include `account_number_hash` in the prompt context. The canary will fail if `SNTL_CANARY_ACCT_000` appears in any rendered prompt.
- **Do NOT log the `PortfolioSnapshot` object directly.** Use structured field allowlist (`holdings_count=len(portfolio.holdings)`), never `portfolio=portfolio`. PII processor is a safety net, not a license.
- **Do NOT store advisory state in `StateStore`/WebSocket.** The broadcaster must never see advisory frames — ISOL-07 canary asserts this.
- **Do NOT write `PortfolioSnapshot` fields into Neo4j.** Neo4j is the swarm's memory; portfolio stays in the advisory file only.
- **Do NOT use `Path.exists()` / `Path.stat()` on the event loop.** Use `aiofiles.os.path.exists` / `aiofiles.os.stat` (Phase 36 T-36-14).
- **Do NOT amend the importlinter contract.** Advisory is already whitelisted as `source_modules` does not contain `alphaswarm.advisory`, so advisory can import `alphaswarm.holdings` freely — no `ignore_imports` addition needed. Verify by running `lint-imports` before and after Phase 41.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Background async task with failure surfacing | Custom queue + sleep loop | Exact copy of `asyncio.create_task` + `add_done_callback` + `app.state.*_generation_error` from Phase 36 | Phase 36 solved T-36-15 (done-callback), T-36-17 (viewState/isGenerating split), T-36-18 (500 terminal) — reusing avoids rediscovering those bugs |
| Cycle ID path traversal validation | Inline regex in advisory route | Import `_validate_cycle_id` + `_CYCLE_ID_RE` from `web/routes/report.py` | Single source of truth; any charset change applies to both endpoints |
| JSON schema enforcement on LLM output | Regex scrub the string / manual `json.loads` + ad-hoc checks | Ollama `format="json"` mode + `AdvisoryReport.model_validate_json(content)` with one bounded retry on `ValidationError` | Plain `format="json"` guarantees syntactic JSON; pydantic `frozen=True + extra="forbid"` enforces shape at the boundary |
| Concurrent orchestrator serialization | A second `asyncio.Lock` in app state | 409 CONFLICT guard against `app.state.report_task.done()==False` (+ any interview engine lock held) | Duplicates the report.py guard; makes the serialization constraint visible in the HTTP layer (operators see the error; frontend knows to back off) |
| Decimal JSON serialization | `json.dumps(..., default=str)` everywhere | Pydantic's built-in (`model_dump_json()`) uses custom Decimal handling when fields are typed `Decimal` | Prevents float precision loss (Pitfall 5 in Phase 39 RESEARCH); single control point |
| SVG chart / bespoke markdown rendering | New template files | Pure JSON output + Vue-side rendering of table rows + narrative | Advisory is a panel, not a report; no Jinja2 templates or pygal needed |
| Re-fetching market prices at synthesis time | Call YFinance again | Deferred per CONTEXT.md — use ContextPacket as-is | Context is already minutes-fresh; extra fetch doubles exposure of holdings to external network (ISOL-05 staleness already tolerable) |

**Key insight:** Phase 41 is 80% composition. Every new line of "clever" code is a new line unvalidated by prior reviews. Mirror Phase 36 structure *pedantically* — reviewer load drops, tests transplant, bugs don't recur.

## Runtime State Inventory

> This is NOT a rename/refactor phase — it is a greenfield feature phase. No stored data is being migrated; no OS-registered state changes; no existing secrets renamed. Section included for completeness because the canary activation (D-20) modifies an existing test file in place.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 41 creates the `advisory/` directory but stores NO new long-lived state. Existing Neo4j graph is READ-ONLY from the advisory engine's perspective. | None |
| Live service config | None — no new env vars, no new service registrations. `app.state.advisory_task` and `app.state.advisory_generation_error` are in-memory only (reset on server restart; report pattern precedent). | Add slot init in `web/app.py` lifespan |
| OS-registered state | None — no daemons, schedulers, or system services involved | None |
| Secrets/env vars | None new. Advisory reuses `app_state.settings.ollama.orchestrator_model_alias` and `app.state.portfolio_snapshot` (already loaded by Phase 39) | None |
| Build artifacts | Vue build artifact: `frontend/dist/assets/index-*.js` will grow by `AdvisoryPanel.vue` size (~5-8 KB minified). `frontend/dist` is gitignored and rebuilt by `npm run build`. | Rebuild frontend after component landing: `cd frontend && npm run build` |
| Test artifact (in-place mutation) | `tests/invariants/test_holdings_isolation.py` — `_minimal_simulation_body` is REPLACED by a real `synthesize()` harness call per D-20. Not a data migration; a test-code edit. | Planner must split into: (a) keep positive-control tests intact, (b) replace body, (c) add await + asyncio_mode fixture since synthesize is async. |

**Canonical question (after every file is updated, what runtime state still has old state cached/stored/registered?):** Nothing. Advisory is additive. The one existing file being modified is a test; the test contents wholly replace the prior stub.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Ollama server (local) | Synthesize LLM call | Required at run time (already required by every prior phase) | `>=0.6.1` | No fallback — offline failure surfaces as 503 via existing `services_unavailable` guard |
| Neo4j (Docker, local) | Prefetch bracket/entity/timeline/narratives | Required (already required by reports) | `>=5.28, <6.0` | No fallback — 503 via existing guard |
| Orchestrator model (`alphaswarm-orchestrator`) | Single inference call | Required — same tag as report generation | — | None |
| Node.js + npm (Vite build) | Frontend build of `AdvisoryPanel.vue` | Required for Vue SPA | matches existing project tooling | None |
| `alphaswarm-orchestrator` Ollama modelfile supports `format="json"` | Structured JSON output | Already in use by `worker.py:102` and `seed.py:69` | — | None |

**Missing dependencies with no fallback:** None — all required runtimes already present as project baseline.
**Missing dependencies with fallback:** None.

[VERIFIED: codebase — worker.py line 102, seed.py line 69 both call `format="json"` with the orchestrator/worker, so Ollama JSON mode compatibility is already proven in this project.]

## Common Pitfalls

### Pitfall 1: Portfolio data leakage through structlog `event_dict`
**What goes wrong:** `log.info("synthesis_start", portfolio=portfolio)` serializes the `PortfolioSnapshot` into the JSON log line, leaking holdings into surface #1 of the ISOL-07 canary.
**Why it happens:** structlog processor chain serializes any value via `repr()` or `str()` by default. PII redaction processor catches `holdings`, `cost_basis`, `account_number` keys but is a safety net, not a contract.
**How to avoid:** Log only scalar metadata — `holdings_count=len(portfolio.holdings)`, `cycle_id=cycle_id`. Never pass the snapshot object.
**Warning signs:** Any `log.*(..., portfolio=..., snapshot=...)` in reviewed diff.

### Pitfall 2: Decimal-to-float coercion in LLM prompt serialization
**What goes wrong:** `json.dumps({"cost_basis": Decimal("101.3071")})` raises `TypeError: Object of type Decimal is not JSON serializable`. Adding `default=float` silently rounds to 101.3071000000001 or worse.
**Why it happens:** Python `json` module has no native Decimal encoder.
**How to avoid:** Build prompt context using explicit `str(decimal_value)` conversions, same pattern as `web/routes/holdings.py:109`. Never `default=float`; `default=str` is acceptable IF you verify the LLM receives the string representation (which matches Phase 39 convention).
**Warning signs:** Any raw `json.dumps` without `default=str` over dicts containing `Holding`.

### Pitfall 3: LLM returns malformed / schema-violating JSON
**What goes wrong:** `format="json"` guarantees syntactically valid JSON but NOT your specific shape. Orchestrator may emit `{"advisory": [...], "outlook": "..."}` instead of `{"items": [...], "portfolio_outlook": "..."}`, or use `"signal"` instead of `"consensus_signal"`.
**Why it happens:** Prompt ambiguity; LLM inventiveness; field-name drift.
**How to avoid:** Three layers:
  1. **Prompt examples** — include one full worked example in the system prompt.
  2. **Strict schema** — pydantic `BaseModel(frozen=True, extra="forbid")` fails fast on unknown/missing fields.
  3. **Bounded retry** — on `ValidationError`, retry ONCE with the error text embedded in a new user message ("Your previous response failed validation: {err}. Please return only the JSON object matching the schema."). Never loop.
**Warning signs:** No retry budget → user waits 10 minutes for the polling timeout; unbounded retry → orchestrator pinned indefinitely.

### Pitfall 4: Orchestrator / worker model collision during live simulation
**What goes wrong:** If a user triggers POST /api/advisory/{cycle_id} while a report is generating, two simultaneous `model_manager.load_model()` calls happen. `ModelManager._lock` serializes them, but the second one waits — and the 10-minute polling window can tick down.
**Why it happens:** Advisory + report + live interview all use the same orchestrator alias. Report has a 409 guard against another report starting; advisory needs the same guard, and the mutual guard.
**How to avoid:** In `POST /api/advisory/{cycle_id}`: 409 CONFLICT if `request.app.state.report_task` exists AND not `.done()`, 409 if `request.app.state.advisory_task` exists AND not `.done()`, 409 if interview sessions show a lock held (per D-08). Mirror in `POST /api/report/{cycle_id}/generate` — add advisory_task check there if not already present.
**Warning signs:** Frontend error "Connection Lost" during normal use because two orchestrator calls starve each other.

### Pitfall 5: Canary false-assurance from too-minimal synthesis call
**What goes wrong:** Phase 37 wrote `_minimal_simulation_body` that trivially passes because it never touches the snapshot. If Phase 41 replaces it with a call like `await synthesize(snapshot=sentinel_portfolio, ollama_client=None, ...)` that short-circuits before touching sinks, the canary still trivially passes — but real production code could still leak.
**Why it happens:** Test harness omits the LLM call, which is the surface most likely to exfiltrate (via rendered prompt).
**How to avoid:** The canary harness MUST:
  1. Use a FakeOllamaClient that records the exact `messages` list it received and appends them to `capture_jinja_renders`.
  2. Use a FakeGraphManager whose `read_*` methods return empty dicts and whose `session.run` is patched to append Cypher + params to `capture_neo4j_writes`.
  3. Monkey-patch the advisory `structlog.get_logger()` to route through `capture_logs`.
  4. If advisory emits a WS event — it shouldn't — `capture_ws_frames` receives it.
**Warning signs:** Canary calls `synthesize()` with `ollama_client=None` or a client that raises immediately; sinks all end up empty regardless of whether synthesize would have leaked.

### Pitfall 6: Advisory task orphaned on server shutdown
**What goes wrong:** Lifespan teardown cancels `broadcaster_task` but not `advisory_task`. On shutdown, a running advisory generation gets `CancelledError`, which the done_callback records as `{"error": "advisory_generation_failed", "message": "cancelled"}`. On restart, that error is lost (app.state is reconstructed) but the error sentinel in the Vue client still shows "failed".
**Why it happens:** app.state does not persist across restarts; on-disk advisory file is the only durable signal.
**How to avoid:** Accept this — Phase 36 report has the same behavior by design. Document it, do NOT add shutdown cancellation (Phase 36 T-36-16 LOW, accepted risk).
**Warning signs:** Reviewer suggests "clean teardown of advisory_task." Reply: matches report precedent.

### Pitfall 7: Vue modal using outdated `cycle_id` after new simulation
**What goes wrong:** User completes simulation A, opens AdvisoryPanel, sees panel for cycle A. Closes it. Runs simulation B. Opens AdvisoryPanel — it still shows cycle A because the component cached the cycle_id.
**Why it happens:** Component-local ref persists across modal open/close; only unmount resets it.
**How to avoid:** Mirror ReportViewer.vue's `resolveCycleAndLoad` in `onMounted` — always fetch `/api/replay/cycles` most-recent-first on mount. Do NOT cache cycle_id across closes (Phase 36 handled this correctly; keep that pattern).
**Warning signs:** Module-level ref for `cycleId` instead of component-local.

### Pitfall 8: Importlinter contract breakage from `advisory/__init__.py` re-exports
**What goes wrong:** `alphaswarm/advisory/__init__.py` re-exports `synthesize` and `AdvisoryItem` via `from .engine import synthesize`. That creates `alphaswarm.advisory` → `alphaswarm.advisory.engine` edge, which `alphaswarm.advisory.engine` → `alphaswarm.holdings`. Since `alphaswarm.advisory` is NOT in importlinter's `source_modules`, this is allowed — but if any other module in `source_modules` imports `alphaswarm.advisory` (e.g., a future CLI helper), the full import chain flags the violation via transitive-edge analysis.
**Why it happens:** importlinter forbidden contract typically operates on direct imports, but chains matter when `web.app` or `cli` grow an advisory dependency later.
**How to avoid:** Keep `alphaswarm.advisory` consumed ONLY by `alphaswarm.web.routes.advisory` (not currently in source_modules either, but it SHOULD be added — see "Importlinter whitelist status" below). Run `uv run lint-imports` at verify time; fail planning if it produces warnings or new contracts are needed.
**Warning signs:** Any `from alphaswarm.advisory import ...` appearing in `alphaswarm.app`, `alphaswarm.cli`, or `alphaswarm.simulation`.

### Pitfall 9: `app.state.market_context_tickers` does not exist yet
**What goes wrong:** D-01 instructs "use `app.state.market_context_tickers` if available." A grep of the codebase reveals this attribute does NOT exist today — Phase 40 computes `tickers` locally in `simulation.py:822` but does NOT store them on app.state.
**Why it happens:** CONTEXT.md D-01 assumes a state surface that was deferred to Phase 41.
**How to avoid:** Plan 41-02 MUST either (a) have Phase 40's `run_simulation` store the ticker list on `app_state` before yielding `SimulationResult`, or (b) accept the D-02 fallback behavior (use global Round 3 consensus for everything, LLM decides relevance per D-03). Recommend (b): the LLM already receives entity_impact and bracket_narratives, which contain the ticker scope implicitly.
**Warning signs:** Plan 41-01 trying to read `app_state.market_context_tickers` — [VERIFIED: not present in codebase as of 2026-04-19]; requires Phase 40 edit or revised approach.

### Pitfall 10: Re-generating advisory overwrites prior file silently
**What goes wrong:** User generates advisory, reads it, closes panel. Clicks "Analyze" again (equivalent to Regenerate in Report pattern). The new file overwrites the old at `advisory/{cycle_id}_advisory.json` during the write window. A concurrent GET during the write sees a truncated file.
**Why it happens:** `aiofiles.open(path, "w")` truncates then writes. No atomic-rename pattern.
**How to avoid:** Accept the risk — matches Phase 36 T-36-16 (reviewed LOW). 3s poll cadence, 5-10 KB file size, millisecond write window. If observed in practice, follow-up quick task with `.tmp + os.rename`.
**Warning signs:** Plan 41-02 attempts atomic write — not needed; match precedent.

## Code Examples

Verified patterns for the planner:

### Example A: `AdvisoryItem` + `AdvisoryReport` types
```python
# File: src/alphaswarm/advisory/types.py
# Pattern source: src/alphaswarm/ingestion/types.py:83 [VERIFIED: codebase]
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Signal = Literal["BUY", "SELL", "HOLD"]

class AdvisoryItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ticker: str
    consensus_signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_summary: str
    position_exposure: Decimal

class AdvisoryReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle_id: str
    generated_at: datetime
    portfolio_outlook: str
    items: tuple[AdvisoryItem, ...] = Field(default_factory=tuple)
    total_holdings: int
    affected_holdings: int
```

### Example B: Synthesize entry point (skeleton)
```python
# File: src/alphaswarm/advisory/engine.py
# Pattern sources:
#   - Prefetch: src/alphaswarm/web/routes/report.py:314-339 (tool registry)
#   - Orchestrator call: src/alphaswarm/seed.py:69 (format="json")
#   - Model lifecycle: src/alphaswarm/web/routes/report.py:310-382 (try/finally)
# [VERIFIED: codebase]

from decimal import Decimal
from alphaswarm.advisory.types import AdvisoryItem, AdvisoryReport
from alphaswarm.holdings.types import PortfolioSnapshot

async def synthesize(
    *,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
    graph_manager: "GraphStateManager",
    ollama_client: "OllamaClient",
    orchestrator_model: str,
) -> AdvisoryReport:
    # 1. Prefetch — parallel where safe (all four read_* are idempotent reads)
    bracket_summary, timeline, narratives, entities = await asyncio.gather(
        graph_manager.read_consensus_summary(cycle_id),
        graph_manager.read_round_timeline(cycle_id),
        graph_manager.read_bracket_narratives(cycle_id),
        graph_manager.read_entity_impact(cycle_id),
    )

    # 2. Serialize holdings for prompt — NEVER repr(portfolio); minimal dict per holding.
    holdings_context = [
        {"ticker": h.ticker, "qty": str(h.qty), "cost_basis": str(h.cost_basis)}
        for h in portfolio.holdings
    ]
    total_cost_basis = sum(
        (h.cost_basis or Decimal("0")) for h in portfolio.holdings
    ) or Decimal("1")  # avoid /0

    # 3. Build prompt (pure function — testable separately; no I/O)
    messages = build_advisory_prompt(
        cycle_id=cycle_id,
        bracket_summary=bracket_summary,
        timeline=timeline,
        narratives=narratives,
        entity_impact=entities,
        holdings=holdings_context,
    )

    # 4. Inference with one bounded retry on ValidationError
    report = await _infer_with_retry(ollama_client, orchestrator_model, messages)

    # 5. Rank: score = confidence × (position_exposure / total_portfolio_cost_basis)
    ranked = tuple(sorted(
        report.items,
        key=lambda i: float(i.confidence) * float(i.position_exposure / total_cost_basis),
        reverse=True,
    ))
    return report.model_copy(update={
        "items": ranked,
        "total_holdings": len(portfolio.holdings),
        "affected_holdings": len(ranked),
    })
```

### Example C: Route mirroring `report.py`
```python
# File: src/alphaswarm/web/routes/advisory.py
# [VERIFIED: line-for-line parity with src/alphaswarm/web/routes/report.py]
from alphaswarm.web.routes.report import _validate_cycle_id  # reuse regex guard (Pitfall 8 avoidance)

@router.post("/advisory/{cycle_id}", status_code=status.HTTP_202_ACCEPTED)
async def generate_advisory(cycle_id: str, request: Request) -> GenerateResponse:
    _validate_cycle_id(cycle_id)
    app_state = request.app.state.app_state
    # 503 guard (graph_manager, ollama_client, model_manager, portfolio_snapshot)
    # 409 guard: phase != COMPLETE
    # 409 guard: report_task running  (Pitfall 4)
    # 409 guard: advisory_task running
    # Clear previous error entry; spawn task; attach done_callback.
    # Identical structure to report.py:146-226
```

### Example D: ISOL-07 canary activation harness
```python
# File: tests/invariants/test_holdings_isolation.py (modified)
# Replaces _minimal_simulation_body per D-20

async def _advisory_harness_body(
    snapshot: PortfolioSnapshot,
    ws_frames: list[str],
    neo4j_writes: list[str],
    jinja_renders: list[str],
    capture_logs: io.StringIO,
) -> None:
    # Construct Fake providers that append to the capture sinks.
    fake_graph = FakeGraphManager(neo4j_sink=neo4j_writes)  # empty dicts, records params
    fake_ollama = FakeOllamaClient(prompt_sink=jinja_renders)  # returns canned JSON
    # synthesize is the REAL function; the invariant is what it passes to sinks.
    _ = await synthesize(
        cycle_id="canary_cycle",
        portfolio=snapshot,
        graph_manager=fake_graph,
        ollama_client=fake_ollama,
        orchestrator_model="alphaswarm-orchestrator",
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 15 TUI report via CLI | Phase 36 HTTP 202 + polling + done_callback | 2026-04-16 (Phase 36 ship) | Advisory inherits the mature pattern; no rediscovery |
| Phase 15 pre-phase-37 — holdings imported anywhere | Phase 37 importlinter whitelist | 2026-04-17 (Phase 37) | Advisory is the ONE privileged consumer; static guarantee |
| TUI interview panel | Phase 35 web InterviewPanel; Phase 36 Vue REVISION-1 dual-flag | 2026-04-15/16 | Advisory mirrors the dual-flag state machine (Pitfall 7) |
| Phase 15 hand-rolled JSON validation in report engine | pydantic `BaseModel(frozen=True, extra="forbid")` with `model_validate_json` | Phase 37 ISOL-02 normalized this | Fail-fast schema at the LLM boundary |

**Deprecated/outdated:**
- Deferred: Re-fetching market prices at advisory synthesis time — explicit CONTEXT.md deferral; ContextPacket prices from the just-ended simulation are fresh enough.
- Deferred: Per-bracket advisory breakdown — single-LLM synthesis already incorporates bracket narratives via D-04 prefetch.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Plain `format="json"` mode (not full JSON Schema mode) is sufficient for orchestrator compliance at the AdvisoryReport shape level, given one bounded retry on ValidationError. | Standard Stack / Pitfall 3 | If orchestrator consistently drifts (e.g., inventing `"signal"` vs `"consensus_signal"`), the single retry may not converge → 500 surfaced via done_callback. Mitigation: planner can upgrade to `format=<json_schema_dict>` mode without breaking the public synthesize API — it's a one-line change in `_infer_with_retry`. |
| A2 | `app.state.market_context_tickers` does not exist as of Phase 40 commit — confirmed by grep. D-01 therefore requires either a Phase 40 touch-up (plan should not add this retroactively) or the D-02/D-03 fallback path is the operating reality. | Pitfall 9 | If I am wrong and Phase 40 did add this attribute, Plan 41-01 should read it directly. Risk is low: the LLM determines affected holdings anyway (D-03). |
| A3 | The advisory task slot `app.state.advisory_task` is a single handle (mirrors report pattern) rather than a dict keyed by cycle_id. | User Constraints / Example C | CONTEXT.md D-08 defers this to Claude's discretion. Single-handle matches report and is sufficient for serialization; a dict would allow parallel cycles but violates D-08 orchestrator serialization. |
| A4 | Frontend `npm run build` regenerates `dist/` cleanly on demand; no stale artifact concern. | Runtime State Inventory | If Vite caches break, `rm -rf frontend/dist frontend/node_modules/.vite` resets. |
| A5 | The ISOL-07 canary can run as async test under `asyncio_mode = "auto"` without additional pytest markers. | Runtime State Inventory, Example D | Verified: `[tool.pytest.ini_options] asyncio_mode = "auto"` [VERIFIED: pyproject.toml:51] — async tests need no `@pytest.mark.asyncio` decorator. The canary file already imports `pytest` and uses `pytestmark = pytest.mark.enable_socket` — planner must preserve that marker when replacing `_minimal_simulation_body`. |
| A6 | `alphaswarm.advisory` does NOT need to be added to importlinter `source_modules`, because `source_modules` enumerates modules forbidden to import `alphaswarm.holdings`. Since advisory IS permitted, it is correctly absent from that list. `alphaswarm.web.routes.advisory` SHOULD be added to `source_modules` because, like every other `web.routes.*`, it is forbidden from importing holdings directly (it imports `alphaswarm.advisory` instead). | Pattern 5 / Pitfall 8 | [VERIFIED: pyproject.toml:68-114 lists `alphaswarm.web.routes.*` submodules individually for each existing route; Phase 41 must add `alphaswarm.web.routes.advisory` to that list.] |

## Open Questions

1. **Should Plan 41-01 store `market_context_tickers` on `app_state` (requires Phase 40 touch) or accept D-02/D-03 fallback?**
   - What we know: Phase 40 computes `tickers` locally; it is not persisted.
   - What's unclear: Whether D-01's "if available" wording means "if Phase 40 is modified to persist it" or "ignore and fall through to D-02."
   - Recommendation: **Accept D-02/D-03 fallback.** The LLM (D-03) is the intelligence layer deciding which holdings are affected; forwarding the ticker set is an optimization, not a correctness requirement. Do not retrofit Phase 40 in Phase 41.

2. **Should advisory task and report task share a single `app.state.orchestrator_task` slot?**
   - What we know: D-08 serializes them; a single slot would enforce the invariant by structure.
   - What's unclear: Whether the Phase 36 reviewer who locked in `report_task` anticipated advisory.
   - Recommendation: Keep two slots (`report_task`, `advisory_task`) because they have independent done_callback error dicts. Enforce serialization via the 409 guard that checks the OTHER task in each endpoint.

3. **Should `POST /api/advisory/{cycle_id}` refuse to spawn if `portfolio_snapshot is None`?**
   - What we know: `app.state.portfolio_snapshot` can be None (Phase 39 D-08) if Schwab CSV load failed at startup.
   - What's unclear: Whether advisory should 503 (match `GET /api/holdings`) or 500 (fail during synthesis).
   - Recommendation: **503 with `{"error": "holdings_unavailable"}`** at POST time — same body shape as GET /api/holdings. Fail fast, don't spawn a doomed task.

4. **Retry budget on Ollama `ValidationError`: 1 or 2?**
   - What we know: Phase 15 report doesn't need schema validation because ReportAssembler uses Jinja templates on observations.
   - What's unclear: Whether local llama-family orchestrator reliably returns shape-conformant JSON.
   - Recommendation: **1 retry, then fail.** Matches backoff philosophy elsewhere (`OllamaClient._chat_with_backoff` max_tries=3 for transient errors, but that's network — not semantic). Two retries double user wait time on bad prompt; if repeated failures are seen in practice, tune the prompt not the retry budget.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 8.x` + `pytest-asyncio` with `asyncio_mode = "auto"` [VERIFIED: pyproject.toml:51] |
| Config file | `pyproject.toml [tool.pytest.ini_options]` [VERIFIED: lines 50-56] |
| Quick run command | `uv run pytest tests/unit/test_advisory_synthesize.py -x -q` |
| Full suite command | `uv run pytest tests/ -x && uv run lint-imports && uv run mypy src/` |
| Frontend quick check | `cd frontend && npm run type-check` (tsconfig `noEmit: true`) |
| Frontend full check | `cd frontend && npm run type-check && npm run build` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADVIS-01 | `synthesize()` returns ranked `AdvisoryReport` with correct schema | unit | `uv run pytest tests/unit/test_advisory_synthesize.py::test_returns_ranked_items -x` | ❌ Wave 0 |
| ADVIS-01 | Ranking formula applied (confidence × exposure / total) | unit | `uv run pytest tests/unit/test_advisory_synthesize.py::test_ranking_formula -x` | ❌ Wave 0 |
| ADVIS-01 | Prefetch calls four graph read methods before LLM | unit | `uv run pytest tests/unit/test_advisory_synthesize.py::test_prefetch_order -x` | ❌ Wave 0 |
| ADVIS-01 | LLM ValidationError triggers single retry | unit | `uv run pytest tests/unit/test_advisory_synthesize.py::test_validation_retry -x` | ❌ Wave 0 |
| ADVIS-01 | `AdvisoryItem` rejects unknown fields | unit | `uv run pytest tests/unit/test_advisory_types.py::test_extra_forbid -x` | ❌ Wave 0 |
| ADVIS-02 | POST returns 202 on valid cycle_id, happy path | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_post_202 -x` | ❌ Wave 0 |
| ADVIS-02 | POST returns 409 when `report_task` in flight | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_409_report_in_progress -x` | ❌ Wave 0 |
| ADVIS-02 | POST returns 409 when `advisory_task` in flight | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_409_advisory_in_progress -x` | ❌ Wave 0 |
| ADVIS-02 | POST returns 400 on bad cycle_id (path traversal) | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_400_invalid_cycle_id -x` | ❌ Wave 0 |
| ADVIS-02 | POST returns 409 on phase != COMPLETE | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_409_wrong_phase -x` | ❌ Wave 0 |
| ADVIS-02 | POST returns 503 on `portfolio_snapshot is None` | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_503_no_holdings -x` | ❌ Wave 0 |
| ADVIS-02 | GET 200 returns file payload | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_get_200 -x` | ❌ Wave 0 |
| ADVIS-02 | GET 404 when file missing and no error recorded | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_get_404 -x` | ❌ Wave 0 |
| ADVIS-02 | GET 500 when `advisory_generation_error[cycle_id]` recorded | integration | `uv run pytest tests/integration/test_advisory_endpoint.py::test_get_500_after_failure -x` | ❌ Wave 0 |
| ADVIS-02 | Orchestrator unloaded in finally even on exception | unit | `uv run pytest tests/unit/test_advisory_synthesize.py::test_unload_in_finally -x` | ❌ Wave 0 |
| ADVIS-03 | Canary flipped to real `synthesize` call — sentinel never in logs | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py::test_sentinels_do_not_appear_in_logs -x` | ✅ exists, body replaced per D-20 |
| ADVIS-03 | Canary — sentinel never in WS frames | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py::test_sentinels_do_not_appear_in_ws_frames -x` | ✅ exists, body replaced |
| ADVIS-03 | Canary — sentinel never in Neo4j writes | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py::test_sentinels_do_not_appear_in_neo4j_writes -x` | ✅ exists, body replaced |
| ADVIS-03 | Canary — sentinel never in rendered prompts | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py::test_sentinels_do_not_appear_in_rendered_prompts -x` | ✅ exists, body replaced |
| ADVIS-03 | Positive controls still green (capture machinery proven) | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py -k positive_control -x` | ✅ exists unchanged |
| ADVIS-03 | importlinter contract still holds after advisory added | invariant | `uv run lint-imports` | ✅ implicit via CI |
| ADVIS-03 | Vue frontend type-checks | ui-static | `cd frontend && npm run type-check` | ✅ existing tooling |
| ADVIS-03 | Vue AdvisoryPanel unmount clears polling interval | ui-manual | manual browser test: open+close during generation, DevTools shows no interval leak | ❌ manual step — human verification Plan 41-03 |
| ADVIS-03 | Escape/backdrop-click closes modal | ui-manual | manual | ❌ manual |
| ADVIS-03 | Ranked table signal colors match D-18 | ui-manual | manual visual check against design tokens | ❌ manual |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/test_advisory_synthesize.py tests/unit/test_advisory_types.py -x -q && uv run lint-imports` (fast — no Neo4j, no Ollama)
- **Per wave merge:** `uv run pytest tests/ -x && uv run mypy src/ && cd frontend && npm run type-check && npm run build`
- **Phase gate:** Full suite green; canary asserts all four surfaces; manual Vue verification completed and recorded in phase review.

### Wave 0 Gaps
- [ ] `tests/unit/test_advisory_synthesize.py` — covers ADVIS-01 unit behaviors (prefetch, ranking, retry, unload finally). NEW file.
- [ ] `tests/unit/test_advisory_types.py` — covers `AdvisoryItem` / `AdvisoryReport` pydantic validation. NEW file.
- [ ] `tests/integration/test_advisory_endpoint.py` — covers ADVIS-02 route behaviors. NEW file. Goes under `tests/integration/` → auto `enable_socket` per Phase 37 D-12.
- [ ] `tests/unit/conftest.py` may need a `FakeGraphManager` + `FakeOllamaClient` fixture pair (or reuse existing fakes if present) — reused by canary harness (Example D) and advisory unit tests. Check `tests/unit/conftest.py` before creating new file.
- [ ] Canary harness helpers — `FakeGraphManager`/`FakeOllamaClient` MUST route all writes/prompts/logs into capture sinks per Pitfall 5. Likely lives in `tests/invariants/fakes.py` or inline in the invariant file.
- [ ] Frontend: `frontend/src/components/AdvisoryPanel.vue` — covered by manual browser tests and `npm run type-check`; no component unit test framework is currently wired (Phase 36 set the same precedent — acceptable).
- [ ] No framework install needed — all frameworks present.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no — local-only web server, single-user | N/A |
| V3 Session Management | no | N/A |
| V4 Access Control | no — single-user context | N/A |
| V5 Input Validation | yes | Cycle ID regex `^[a-zA-Z0-9_-]+$` (path traversal, T-36-01); pydantic `extra="forbid"` on all request/response bodies; `AdvisoryItem` schema enforced on LLM output |
| V6 Cryptography | partial | Account numbers hashed via `sha256_first8` (Phase 39 HOLD-02) before they ever reach advisory; advisory does not touch raw account numbers |
| V7 Error Handling | yes | 503 bodies NEVER echo filesystem paths, exception text, or portfolio data (Phase 39 T-39-06 precedent); done_callback records safe message via `str(exc)` or `exc.__class__.__name__` |
| V8 Data Protection | yes | PII redaction structlog processor (Phase 37 ISOL-04) catches `holdings`, `portfolio`, `cost_basis`, `account_number` keys; ISOL-07 canary asserts absence of sentinel values across four surfaces |
| V9 Communications | partial | All network I/O is localhost (Ollama, Neo4j); no TLS concerns in single-machine deployment |
| V10 Malicious Code | no | No user-supplied code paths |
| V12 Files / Resources | yes | `advisory/{cycle_id}_advisory.json` write constrained by cycle_id regex (no `../`); `aiofiles.os.path.exists/stat` avoid TOCTOU by running on the event loop; write-truncation window is accepted per Phase 36 T-36-16 |
| V14 Configuration | no | No new config surfaces; reuses orchestrator alias from settings |

### Known Threat Patterns for FastAPI + Vue + Local Ollama

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in `cycle_id` → write to `advisory/../../etc/...` | Tampering | `_validate_cycle_id` regex guard imported from `report.py`; applied at both POST and GET handlers (D-12) |
| Portfolio data leakage into LLM-rendered prompt (surface #4 of canary) | Information Disclosure | Serialize holdings only as minimal `{ticker, qty, cost_basis}` dicts via `str(Decimal)`; never pass `PortfolioSnapshot` directly; ISOL-07 invariant test |
| Portfolio data leakage into logs (surface #1) | Information Disclosure | structlog PII redaction processor (Phase 37 D-05/D-06/D-07); log only scalar metadata; canary test |
| Portfolio data leakage into Neo4j (surface #2) | Information Disclosure | advisory NEVER calls `session.execute_write`; Neo4j access limited to read_* methods; canary test |
| Portfolio data leakage into WebSocket (surface #3) | Information Disclosure | advisory does not publish to `ConnectionManager`; canary test |
| Orchestrator model exhaustion (DoS by spamming POST) | DoS | 409 guard on in-flight tasks (advisory + report); per-client throttling is future work — acceptable for local single-user |
| Malformed LLM JSON → uncaught exception crashes server | DoS | pydantic `model_validate_json` inside `try/except`; done_callback converts any exception to `{"error": "advisory_generation_failed", "message": ...}` so server stays up |
| Concurrent file write vs. GET read → truncated response | Tampering (read) | Accepted risk per Phase 36 T-36-16; 3s poll absorbs transient truncation |
| Importlinter contract regression (future developer imports holdings elsewhere) | Tampering (integrity) | `tests/invariants/test_importlinter_contract.py` enforces on CI + pre-commit; Phase 37 D-03 |

## Sources

### Primary (HIGH confidence)
- `.planning/phases/41-advisory-pipeline/41-CONTEXT.md` — 20 locked decisions, 5 Claude-discretion items, 4 deferred items [VERIFIED: read in full]
- `.planning/REQUIREMENTS.md` §ADVIS-01/02/03 + §ISOL-07 [VERIFIED: read in full]
- `src/alphaswarm/web/routes/report.py` — complete async 202/polling/done_callback implementation [VERIFIED: codebase, full file read]
- `src/alphaswarm/report.py` — ReportEngine/ReportAssembler/`write_report` pattern [VERIFIED: codebase]
- `src/alphaswarm/graph.py` — four read methods: `read_consensus_summary` (line 1091), `read_round_timeline` (line 1131), `read_bracket_narratives` (line 1170), `read_entity_impact` (line 1360) [VERIFIED: codebase]
- `src/alphaswarm/ollama_client.py` — `OllamaClient.chat(format="json" | dict | None, ...)` [VERIFIED: line 50-100]
- `src/alphaswarm/holdings/types.py` — `Holding`, `PortfolioSnapshot` frozen dataclasses [VERIFIED: codebase]
- `src/alphaswarm/web/routes/holdings.py` — `load_portfolio_snapshot` lifespan helper; importlinter whitelist indirection pattern [VERIFIED: codebase]
- `src/alphaswarm/web/app.py` — lifespan assembly of `app.state.portfolio_snapshot`, `report_task`, `report_generation_error` [VERIFIED: lines 43-97]
- `tests/invariants/test_holdings_isolation.py` — current canary scaffold [VERIFIED: full file read]
- `tests/invariants/conftest.py` — sentinel fixtures, capture fixtures [VERIFIED: full file read]
- `frontend/src/components/ReportViewer.vue` — REVISION-1 dual-flag state machine [VERIFIED: full file read]
- `frontend/src/components/ControlBar.vue` — `isComplete` template block; Report button style [VERIFIED: full file read]
- `frontend/src/App.vue` — `showReportViewer` ref + handler pattern [VERIFIED: full file read]
- `pyproject.toml` — importlinter contract structure, pytest config, dependency versions [VERIFIED: full file read]
- `uv.lock` — pydantic 2.12.5, ollama 0.6.1 pinned [VERIFIED]
- `.planning/phases/37-isolation-foundation-provider-scaffolding/37-RESEARCH.md` — ISOL-01..ISOL-07 context [VERIFIED: partial read, relevant sections]

### Secondary (MEDIUM confidence)
- Phase 36 review artifacts (T-36-14, T-36-15, T-36-17, T-36-18) — referenced in `web/routes/report.py` docstring comments for pattern rationale [CITED: inline docstrings in codebase]
- Phase 39 REVIEWS closure notes — referenced in `web/routes/holdings.py` docstring comments [CITED: inline docstrings]

### Tertiary (LOW confidence — flagged)
- Ollama full JSON Schema mode behavior under orchestrator-class local models [ASSUMED A1]. Not verified in this project. Plain `format="json"` is battle-tested; schema mode is not. Recommendation is to stay with plain JSON mode.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library and version [VERIFIED: uv.lock / pyproject.toml / codebase inspection]
- Architecture patterns: HIGH — every pattern is a direct copy of an existing, reviewed implementation
- Pitfalls: HIGH — Pitfalls 1-8 are derived from Phase 36/37/39 review artifacts; Pitfall 9 discovered via grep (confirmed `market_context_tickers` not present); Pitfall 10 is an accepted Phase 36 risk carried forward
- Security domain: HIGH — threat model inherited from Phase 37 isolation scaffolding + Phase 36 path-traversal + Phase 39 503-body hygiene
- Validation architecture: HIGH — test framework + commands verified in `pyproject.toml`

**Research date:** 2026-04-19
**Valid until:** 2026-05-19 (30 days — patterns are stable; pydantic 2.x and Ollama 0.6.x are mature; no fast-moving dependencies in this phase)
