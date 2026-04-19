# Phase 41: Advisory Pipeline - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Post-simulation synthesis: after a simulation cycle completes, join the user's `PortfolioSnapshot` holdings against the 100-agent bracket consensus signals and surface which positions are most affected by the simulated market reaction. Delivers `alphaswarm.advisory.synthesize()`, `POST /api/advisory/{cycle_id}` + `GET /api/advisory/{cycle_id}` endpoints, and `AdvisoryPanel.vue` (full-screen modal triggered from the ControlBar). No new simulation logic — pure post-simulation analysis.

</domain>

<decisions>
## Implementation Decisions

### Ticker-Entity Correlation
- **D-01:** Match holdings tickers against ContextPacket tickers first (the tickers explicitly fetched by `YFinanceMarketDataProvider` during the simulation run). If `app.state.market_context_tickers` (or equivalent stored set) is available post-simulation, use it as the primary scope signal.
- **D-02:** Fallback for unmatched holdings (ticker not in ContextPacket scope): apply the global Round 3 consensus signal (BUY/SELL/HOLD counts from `read_consensus_summary`) as the signal. Position still appears in the advisory output with lower confidence.
- **D-03:** Final impact determination is delegated to the orchestrator LLM — not a programmatic rule. The LLM receives the full swarm context + portfolio and decides which holdings are genuinely affected by the simulation's seed rumor. Positions the LLM determines as unaffected are omitted from the ranked output.

### Synthesis Approach
- **D-04:** Pre-fetch all swarm data programmatically from Neo4j before the LLM call:
  - `bracket_summary` — global Round 3 BUY/SELL/HOLD counts
  - `entity_impact` — per-entity sentiment aggregation
  - `bracket_narratives` — per-bracket stance summaries
  - `round_timeline` — signal distribution across rounds 1-3
  - Seed rumor text (from the simulation seed stored in Neo4j or app.state)
- **D-05:** Single orchestrator LLM call — one prompt containing all prefetched swarm data + serialized portfolio holdings (ticker, qty, cost_basis). LLM outputs:
  1. A list of `AdvisoryItem` records for affected holdings (structured JSON)
  2. A `portfolio_outlook` narrative paragraph (1-3 paragraphs)
  The LLM decides which holdings are affected; unaffected holdings are simply absent from the JSON output.
- **D-06:** `AdvisoryItem` schema:
  ```
  ticker: str
  consensus_signal: "BUY" | "SELL" | "HOLD"
  confidence: float (0.0–1.0)
  rationale_summary: str  (1-2 sentences)
  position_exposure: Decimal  (total cost_basis for this holding)
  ```
- **D-07:** Ranking: `score = confidence × (position_exposure / total_portfolio_cost_basis)`. Highest combined signal strength + portfolio weight ranks first.
- **D-08:** Orchestrator lifecycle: `load_model → synthesis → unload_model` in a `finally` block. Matches the report pattern exactly. Advisory synthesis must never run concurrently with agent interviews or report generation (ADVIS-02 serialization requirement). Check `app.state.report_task` and any active `interview` before spawning the advisory task.

### Endpoint Response Pattern
- **D-09:** `POST /api/advisory/{cycle_id}` → 202 Accepted immediately. Spawns background asyncio Task (same pattern as `POST /api/report/{cycle_id}/generate`). Returns `{"status": "accepted", "cycle_id": cycle_id}`.
- **D-10:** `GET /api/advisory/{cycle_id}` → reads `advisory/{cycle_id}_advisory.json` from disk. Returns 200 with advisory payload, 404 if not generated yet, 500 if background task failed (done_callback pattern from Phase 36).
- **D-11:** Advisory JSON written to `advisory/{cycle_id}_advisory.json`. Directory created if absent. Persistent across server restarts (no regeneration required on refresh).
- **D-12:** `_CYCLE_ID_RE` path traversal guard (reuse from `web/routes/report.py`) applied to both endpoints.
- **D-13:** Done-callback on the advisory asyncio Task captures failures into `app.state.advisory_generation_error[cycle_id]` (same pattern as `app.state.report_generation_error`). GET endpoint surfaces 500 on recorded failure so the frontend can stop polling.

### Advisory Panel Layout (Vue)
- **D-14:** Full-screen modal — same chrome as `ReportViewer.vue` (backdrop + centered modal, Escape/backdrop-click to close). Modal size: 80vw × 80vh, capped at 1200px × 900px.
- **D-15:** ControlBar trigger: "Advisory" button added to the `isComplete` template block alongside the existing "Report" button. Button style: same as `.control-bar__btn--report` (transparent background, accent border, accent text). Emits `open-advisory-panel` event; App.vue owns the `showAdvisoryPanel` ref.
- **D-16:** Modal content layout (top to bottom):
  1. **Header**: "Advisory — {cycle_id[:8]}" + "Analyze" action button + "×" close button
  2. **Narrative block**: `portfolio_outlook` text rendered as plain text with `var(--color-text-primary)`
  3. **Divider**: `1px solid var(--color-border)`
  4. **Table**: ranked `AdvisoryItem` list — columns: TICKER | SIGNAL | CONF | EXPOSURE | RATIONALE
  5. **Footer**: status text ("N of M positions affected") + Analyze button (mirrors Report's Generate button)
- **D-17:** Only affected holdings are shown in the table. Holdings the LLM omitted are not displayed. Footer shows count: "{N} of {total_holdings} positions affected by this simulation."
- **D-18:** Signal cell color coding: BUY → `var(--color-accent)` (green/blue tint), SELL → `var(--color-destructive)` (red tint), HOLD → `var(--color-text-secondary)` (neutral). Matches existing bracket signal bar conventions.
- **D-19:** Advisory panel has independent `viewState` and `isAnalyzing` flags (same REVISION-1 pattern from ReportViewer — never conflate generation status with view rendering state).

### ISOL-07 Canary Activation
- **D-20:** Phase 37 scaffolded `tests/invariants/test_holdings_isolation.py` with `_minimal_simulation_body`. Phase 41 replaces that stub with a real `synthesize()` call using the sentinel `PortfolioSnapshot` (SNTL_CANARY_TICKER, SNTL_CANARY_ACCT_000, etc.). The canary asserts that sentinel values do NOT appear in logs, Neo4j properties, WebSocket frames, or agent prompts after advisory synthesis runs.

### Claude's Discretion
- Exact Cypher query shape for prefetching `entity_impact` and `bracket_narratives` (reuse existing graph methods from `report.py` tool registry)
- LLM prompt template for the advisory synthesis call (system + user message structure)
- JSON parsing/validation of the LLM's structured advisory output (Pydantic model or dataclass)
- Exact `portfolio_outlook` display typography in the modal (font-size, line-height — follow existing `ReportViewer` prose styles)
- Whether `advisory_task` is stored on `app.state` or a separate dict keyed by `cycle_id`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §ADVIS-01, §ADVIS-02, §ADVIS-03 — three acceptance-tracked requirements this phase closes
- `.planning/REQUIREMENTS.md` §ISOL-07 — canary activation (scaffolded Phase 37, activates Phase 41)
- `.planning/ROADMAP.md` §"Phase 41: Advisory Pipeline" — goal, success criteria, plan split

### Holdings types (Phase 37/39 outputs)
- `src/alphaswarm/holdings/types.py` — `Holding` and `PortfolioSnapshot` frozen stdlib dataclasses
- `src/alphaswarm/holdings/loader.py` — `HoldingsLoader.load(path)` classmethod
- `src/alphaswarm/web/routes/holdings.py` — only web module permitted to import `alphaswarm.holdings`; advisory uses holdings via `app.state.portfolio_snapshot`, NOT direct import

### Importlinter whitelist
- `pyproject.toml` §[tool.importlinter] — `alphaswarm.advisory` is whitelisted to import `alphaswarm.holdings` (D-04, Phase 37 D-04); no pyproject.toml edit needed for the advisory package itself

### Web app patterns (Phase 36 established)
- `src/alphaswarm/web/routes/report.py` — async 202+polling pattern, done_callback, `_validate_cycle_id`, path traversal guard, `_run_report_generation`, `_on_report_task_done` — mirror all of these for advisory
- `src/alphaswarm/web/app.py` — lifespan pattern for `app.state` construction; router registration; add advisory router here
- `src/alphaswarm/report.py` — `ReportEngine` tool registry pattern; `write_report` aiofiles disk writer — advisory uses similar Neo4j prefetch then single LLM call

### Neo4j graph methods (existing, reuse)
- `src/alphaswarm/graph.py` methods: `read_consensus_summary`, `read_entity_impact`, `read_bracket_narratives`, `read_round_timeline` — all already exist; advisory prefetches them all before the LLM call

### Canary invariant
- `tests/invariants/test_holdings_isolation.py` — ISOL-07 canary; Phase 41 replaces `_minimal_simulation_body` with real `synthesize()` call

### Vue front-end patterns
- `frontend/src/components/ReportViewer.vue` — full-screen modal pattern, REVISION-1 dual-flag state machine (viewState + isGenerating), polling loop, error handling — AdvisoryPanel.vue mirrors this
- `frontend/src/components/ControlBar.vue` — `isComplete` template block; add "Advisory" button alongside "Report" here
- `frontend/src/App.vue` — `showReportViewer` ref + handler pattern; add `showAdvisoryPanel` ref + `onOpenAdvisoryPanel` / `onCloseAdvisoryPanel` handlers here
- `frontend/src/assets/variables.css` — design tokens (`--color-accent`, `--color-destructive`, spacing vars) for signal color coding

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `report.py:_run_report_generation` — complete async background task pattern with load_model, work, unload_model in finally; advisory synthesis mirrors this
- `report.py:_on_report_task_done` — done_callback capturing failures into `app.state.report_generation_error`; advisory uses same pattern with `advisory_generation_error`
- `web/routes/report.py:_validate_cycle_id` — `re.compile(r"^[a-zA-Z0-9_-]+$")`; import and reuse in advisory route
- `graph.py` methods: `read_consensus_summary`, `read_entity_impact`, `read_bracket_narratives`, `read_round_timeline` — all used in report.py tool registry; advisory calls them directly (no ReACT loop needed)
- `ReportViewer.vue` — entire REVISION-1 state machine (viewState × isGenerating, polling, done-callback 500 handling) is the template for AdvisoryPanel.vue
- `ControlBar.vue:isComplete` block — add "Advisory" button here alongside existing "Report" button using `.control-bar__btn--report` style class

### Established Patterns
- `asyncio_mode = "auto"` project-wide — async test functions need no decorator
- `pytest-socket --disable-socket` global gate — advisory unit tests must use Fake providers; integration tests go under `tests/integration/`
- mypy strict mode — all new types must be fully typed; `AdvisoryItem` should be a frozen pydantic `BaseModel(frozen=True)` or stdlib frozen dataclass
- Background task + `app.state` task slot: `app.state.report_task` is the existing pattern; add `app.state.advisory_task` alongside it
- Polling at 3s cadence with 200-iteration cap (10-minute max) — reuse from ReportViewer

### Integration Points
- `src/alphaswarm/advisory/__init__.py` (new) — `synthesize(cycle_id, portfolio)` public entry point
- `src/alphaswarm/advisory/types.py` (new) — `AdvisoryItem` type, `AdvisoryReport` container (items list + portfolio_outlook string)
- `src/alphaswarm/advisory/engine.py` (new) — prefetch + single LLM call logic; model lifecycle; JSON output parsing
- `src/alphaswarm/web/routes/advisory.py` (new) — POST + GET endpoints; 202 pattern; disk I/O via aiofiles
- `src/alphaswarm/web/app.py` — `app.include_router(advisory_router, prefix="/api")` + advisory task slot init
- `frontend/src/components/AdvisoryPanel.vue` (new) — full-screen modal
- `frontend/src/components/ControlBar.vue` — add "Advisory" emit + button to `isComplete` block
- `frontend/src/App.vue` — import AdvisoryPanel, add `showAdvisoryPanel` state, wire ControlBar event

</code_context>

<specifics>
## Specific Ideas

- User explicitly wants the orchestrator to synthesize the entire swarm's collective view — "take advice/into account what everyone in the swarm is saying" — not just programmatic bracket counts. The LLM should reason about the simulation's consensus before making per-holding calls.
- "Not every rumor or piece of news or earnings impacts every stock I hold" — the LLM is the intelligence layer deciding relevance. Holdings not mentioned or implied by the seed rumor should be omitted from the advisory output, not shown with neutral signals.
- "A very thorough, well put together report" — the `portfolio_outlook` narrative paragraph should be substantive (not a one-liner). The table rows should have meaningful rationale_summary text, not just the signal label.
- ControlBar complete-phase layout: `[ Complete ]  [ Advisory ]  [ Report ]  [ Stop ]` — Advisory button left of Report button.
- Advisory JSON file: `advisory/{cycle_id}_advisory.json` (parallel to `reports/{cycle_id}_report.md`).

</specifics>

<deferred>
## Deferred Ideas

- Per-bracket advisory breakdown (e.g., "Quants say SELL, Whales say BUY on NVDA") — interesting but the single-LLM synthesis already incorporates bracket narratives; separate per-bracket table is future work
- Advisory history across multiple cycles (compare how recommendations changed over time) — out of scope for v6.0
- Export advisory to PDF or CSV — future phase
- Re-fetch live market prices at advisory synthesis time for fresh prices — deferred; Phase 40's ContextPacket prices are already recent enough for advisory relevance

</deferred>

---

*Phase: 41-advisory-pipeline*
*Context gathered: 2026-04-19*
