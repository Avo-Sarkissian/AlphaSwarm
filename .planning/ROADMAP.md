# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** — Phases 1-10 (shipped 2026-03-27)
- [x] **v2.0 Engine Depth** — Phases 11-15 (shipped 2026-04-02)
- [x] **v4.0 Interactive Simulation & Analysis** — Phases 24-28 (shipped 2026-04-12)
- [x] **v5.0 Web UI** — Phases 29-36 (shipped 2026-04-18)
- 🚧 **v6.0 Real Data + Advisory** — Phases 37-41 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Core Engine (Phases 1-10) — SHIPPED 2026-03-27</summary>

- [x] **Phase 1: Project Foundation** - Scaffold, configuration system, type definitions, and structured logging (completed 2026-03-24)
- [x] **Phase 2: Ollama Integration** - Async LLM client, sequential model loading, and structured output parsing (completed 2026-03-25)
- [x] **Phase 3: Resource Governance** - Dynamic concurrency control, memory monitoring, task safety, and retry logic (completed 2026-03-25)
- [x] **Phase 4: Neo4j Graph State** - Graph schema with cycle-scoped indexes and batch-writing GraphStateManager (completed 2026-03-25)
- [x] **Phase 5: Seed Injection and Agent Personas** - Orchestrator entity extraction and 100 agent personas with decision schema (completed 2026-03-26)
- [x] **Phase 6: Round 1 Standalone** - All 100 agents process a seed rumor independently in a single inference wave (completed 2026-03-26)
- [x] **Phase 7: Rounds 2-3 Peer Influence and Consensus** - Peer context injection and final consensus lock complete the 3-round cascade (completed 2026-03-26)
- [x] **Phase 8: Dynamic Influence Topology** - INFLUENCED_BY edges form from citation patterns, bracket aggregation, and Miro batcher stub (completed 2026-03-26)
- [x] **Phase 9: TUI Core Dashboard** - Agent grid, snapshot-based rendering, and simulation status display (completed 2026-03-27)
- [x] **Phase 10: TUI Panels and Telemetry** - Rationale sidebar, hardware telemetry footer, and bracket aggregation panel (completed 2026-03-27)

</details>

<details>
<summary>v2.0 Engine Depth (Phases 11-15) — SHIPPED 2026-04-02</summary>

- [x] **Phase 11: Live Graph Memory** - Real-time Neo4j rationale episodes, narrative edges, and interview context summaries written during simulation (completed 2026-03-31)
- [x] **Phase 12: Richer Agent Interactions** - Agents publish public rationale posts that peers read and react to via token-budget-aware context injection (completed 2026-04-01)
- [x] **Phase 13: Dynamic Persona Generation** - Entity-aware bracket modifiers generated from seed rumor for situation-specific agent personas (completed 2026-04-02)
- [x] **Phase 14: Agent Interviews** - Post-simulation conversational Q&A with any agent using reconstructed decision context (completed 2026-04-02)
- [x] **Phase 15: Post-Simulation Report** - ReACT agent queries Neo4j and generates structured market analysis as exportable markdown (completed 2026-04-02)

</details>

<details>
<summary>v4.0 Interactive Simulation & Analysis (Phases 24-28) — SHIPPED 2026-04-12</summary>

- [x] **Phase 24: HTML Report Export** - Exportable HTML simulation reports with SVG charts and Schwab portfolio overlay (completed 2026-04-09)
- [x] **Phase 26: Shock Injection Core** - Mid-simulation shock injection with governor suspend/resume and ReplayStore isolation (completed 2026-04-10)
- [x] **Phase 27: Shock Analysis and Reporting** - Shock impact analysis with bracket delta mode, read_shock_impact, and Jinja2 shock template (completed 2026-04-11)
- [x] **Phase 28: Simulation Replay** - Re-render a past simulation cycle from stored Neo4j state without re-running inference (completed 2026-04-12)

</details>

<details>
<summary>v5.0 Web UI (Phases 29-36) — SHIPPED 2026-04-18</summary>

- [x] **Phase 29: FastAPI Skeleton and Event Loop Foundation** - FastAPI app with lifespan, WebSocket state stream, and async event loop wiring (completed 2026-04-13)
- [x] **Phase 30: WebSocket State Stream** - Real-time StateSnapshot broadcast over WebSocket with connection manager (completed 2026-04-13)
- [x] **Phase 31: Vue SPA and Force-Directed Graph** - Vue 3 + Vite SPA with D3 force-directed agent graph, sidebar, and WebSocket composable (completed 2026-04-14)
- [x] **Phase 32: REST Controls and Simulation Control Bar** - Simulation start/stop/shock REST endpoints, replay contract stubs, and Vue control bar with shock drawer (completed 2026-04-14)
- [x] **Phase 33: Web Monitoring Panels** - Live rationale feed with animated entries and D3 bracket sentiment bars in the browser (completed 2026-04-15)
- [x] **Phase 34: Replay Mode Web UI** - Cycle picker, round stepping, and force graph re-render from stored Neo4j state (completed 2026-04-15)
- [x] **Phase 35: Agent Interviews Web UI** - Click any post-simulation graph node to open a live multi-turn interview panel in the browser (completed 2026-04-16)
- [x] **Phase 35.1: Shock Injection Wiring** - ShockEvent Neo4j persistence, run_simulation consume_shock wiring (INSERTED — completed 2026-04-16)
- [x] **Phase 36: Report Viewer** - Fetch and render the post-simulation market analysis report as a formatted panel within the SPA (completed 2026-04-17)

</details>

### v6.0 Real Data + Advisory (Phases 37-41)

**Milestone Goal:** Ground the simulation in real market data — live price feeds, news headlines, and portfolio holdings loaded from Schwab CSV — and surface personalized post-simulation advisory insights via an orchestrator synthesis pipeline.

- [x] **Phase 37: Isolation Foundation + Provider Scaffolding** - Frozen type contracts, provider protocols + fakes, PII redaction, socket gate, importlinter holdings isolation (completed 2026-04-18)
- [x] **Phase 38: Market Data + News Providers** - Real `MarketDataProvider` (yfinance) and `NewsProvider` (RSS/newsapi) implementations with integration tests (completed 2026-04-18)
- [ ] **Phase 39: Holdings Loader** - `HoldingsLoader` reads Schwab CSV into `PortfolioSnapshot` with HOLD-02 account number hashing; `GET /api/holdings` REST endpoint
- [ ] **Phase 40: Simulation Context Wiring** - Wire `ContextPacket` (entities + market + news) into simulation seed injection so agents receive grounded price/headline context
- [ ] **Phase 41: Advisory Pipeline** - `alphaswarm.advisory` synthesis: post-simulation advisory report joining holdings positions against consensus signals and market data; `GET /api/advisory/{cycle_id}` endpoint + Vue advisory panel

## Phase Details

### Phase 37: Isolation Foundation + Provider Scaffolding
**Goal**: Establish the isolation foundation for v6.0 Option A: frozen type contracts, provider protocols, defensive test gates (PII redaction + socket blocking), and the holdings import-linter enforcement contract
**Depends on**: Phase 36 (v5.0 Web UI complete)
**Requirements**: ISOL-01, ISOL-02, ISOL-03, ISOL-04, ISOL-05, ISOL-06, ISOL-07
**Success Criteria** (what must be TRUE):
  1. `alphaswarm.holdings` subpackage with frozen stdlib dataclasses `Holding` and `PortfolioSnapshot` (ISOL-01)
  2. `alphaswarm.ingestion` subpackage with pydantic v2 frozen+forbid models `ContextPacket`, `MarketSlice`, `NewsSlice`, `Fundamentals`; all collection fields are `tuple[...]` (ISOL-02)
  3. `importlinter` forbidden contract in `pyproject.toml` with whitelist-only inversion; `uv run lint-imports` exits 0; drift-resistant coverage test catches new packages (ISOL-03)
  4. Recursive PII redaction structlog processor in shared_processors chain before renderer (ISOL-04)
  5. `pytest-socket --disable-socket` global gate with `--allow-unix-socket`; `enable_socket` escape hatch; `tests/integration/` conftest auto-applies marker (ISOL-05, ISOL-06)
  6. Four-surface holdings isolation canary (logs, Neo4j, WebSocket, prompt) with sentinel `PortfolioSnapshot`, representation variants, positive controls; labeled SCAFFOLDED pending Phase 41 activation (ISOL-07)
**Plans**: 4 plans
Plans:
- [x] 37-01-PLAN.md -- Frozen type boundaries: Holding, PortfolioSnapshot, ContextPacket, MarketSlice, NewsSlice, Fundamentals, sha256_first8, dev deps
- [x] 37-02-PLAN.md -- MarketDataProvider + NewsProvider Protocol classes + FakeMarketDataProvider + FakeNewsProvider
- [x] 37-03-PLAN.md -- Recursive PII redaction structlog processor + pytest-socket global gate + hypothesis fuzz tests
- [x] 37-04-PLAN.md -- importlinter forbidden contract + drift-resistant coverage test + four-surface holdings isolation canary + integration conftest

### Phase 38: Market Data + News Providers
**Goal**: Implement real `MarketDataProvider` (yfinance batch price fetch) and `NewsProvider` (RSS or newsapi headlines) against the Phase 37 Protocol contracts, with integration tests using the `tests/integration/` conftest socket escape hatch
**Depends on**: Phase 37
**Requirements**: INGEST-01, INGEST-02
**Success Criteria** (what must be TRUE):
  1. `YFinanceMarketDataProvider` implements `MarketDataProvider` protocol — `fetch_batch(tickers, as_of)` returns `dict[str, MarketSlice]` with `price`, `fundamentals`, and `staleness` populated from yfinance
  2. `RSSNewsProvider` (or equivalent) implements `NewsProvider` protocol — `fetch_headlines(entities)` returns `dict[str, NewsSlice]` with entity-filtered headlines and `staleness`
  3. Both providers use the `StalenessState` typing (`fresh`/`stale`/`fetch_failed`) and never raise — failures return `fetch_failed` slices
  4. Integration tests in `tests/integration/` hit real network and pass with `enable_socket` marker; unit tests use Fakes
**Plans**: 3 plans

Plans:
- [x] 38-01-PLAN.md -- YFinanceMarketDataProvider: thread-per-ticker fast_info+info, _fetch_batch_shared, Decimal precision, D-19 fetch_failed, unit tests (monkeypatched yf.Ticker)
- [x] 38-02-PLAN.md -- RSSNewsProvider: dual-source URL routing (Yahoo ticker / Google News topic with quote_plus), httpx+feedparser, entity filter, max_age_hours, D-19, unit tests (mocked httpx)
- [x] 38-03-PLAN.md -- Integration tests: real-network yfinance + RSS tests in tests/integration/ (auto enable_socket via conftest) + User-Agent regression guard

### Phase 39: Holdings Loader
**Goal**: Load Schwab CSV export into a `PortfolioSnapshot` with account number hashing (HOLD-02), expose holdings via a `GET /api/holdings` FastAPI endpoint, and wire `web.routes.holdings` into the importlinter whitelist
**Depends on**: Phase 37
**Requirements**: HOLD-01, HOLD-02, HOLD-03
**Success Criteria** (what must be TRUE):
  1. `HoldingsLoader.load(path)` reads a Schwab CSV export and returns a `PortfolioSnapshot` with `Holding` tuples; raw account numbers are hashed via `sha256_first8` before storage (HOLD-02)
  2. `GET /api/holdings` returns serialized holdings for the configured CSV path; `alphaswarm.web.routes.holdings` is the only web module permitted to import `alphaswarm.holdings`
  3. Holdings never appear in simulation logs, Neo4j, WebSocket frames, or agent prompts — the four-surface canary (Phase 37 ISOL-07) activates and confirms isolation
  4. Malformed or missing CSV returns a structured error response; no exception propagates to the WebSocket loop
**Plans**: 2 plans

Plans:
- [ ] 39-01-PLAN.md -- HoldingsLoader class, CSV parser, sha256_first8 account hashing, unit tests
- [ ] 39-02-PLAN.md -- GET /api/holdings route, lifespan loader wiring, isolation canary activation, integration test

### Phase 40: Simulation Context Wiring
**Goal**: Wire `ContextPacket` (entities + market slices + news slices) into the simulation seed injection path so agents receive grounded current price and headline context alongside the seed rumor
**Depends on**: Phase 38
**Requirements**: INGEST-03, SIM-04
**Success Criteria** (what must be TRUE):
  1. `run_simulation` accepts an optional `context_packet: ContextPacket | None`; when provided, market prices and news headlines for seed entities are appended to each agent's Round 1 prompt
  2. `ContextPacket` is assembled by the orchestrator before simulation via `MarketDataProvider.fetch_batch` + `NewsProvider.fetch_headlines` on extracted entities
  3. Context packet contents are scrubbed by the PII redaction processor before reaching logs or Neo4j (Phase 37 ISOL-04)
  4. Simulation runs correctly with `context_packet=None` (backward-compatible default)
**Plans**: 2 plans

Plans:
- [ ] 40-01-PLAN.md -- ContextPacket assembly in orchestrator, run_simulation context_packet param, prompt injection, unit tests
- [x] 40-02-PLAN.md -- Integration test: full simulation run with real ContextPacket from Phase 38 providers (completed 2026-04-18)

### Phase 41: Advisory Pipeline
**Goal**: After simulation completes, synthesize a personalized advisory by joining the agent consensus signals against the user's `PortfolioSnapshot` holdings and current market data — surfacing which positions are most affected by the simulated market reaction
**Depends on**: Phase 39 (holdings), Phase 40 (context wiring)
**Requirements**: ADVIS-01, ADVIS-02, ADVIS-03
**Success Criteria** (what must be TRUE):
  1. `alphaswarm.advisory.synthesize(cycle_id, portfolio)` joins final-round bracket consensus signals against each holding's ticker, returning a ranked list of `AdvisoryItem` (ticker, consensus_signal, confidence, rationale_summary, position_exposure)
  2. `POST /api/advisory/{cycle_id}` triggers synthesis and returns the advisory JSON; a Vue `AdvisoryPanel.vue` renders it post-simulation alongside the existing Report Viewer
  3. The four-surface holdings isolation canary (Phase 37 ISOL-07) activates: canary `_minimal_simulation_body` is replaced with real `synthesize()` call confirming no holdings values leak to logs/Neo4j/WS/prompts
  4. Advisory synthesis uses the orchestrator model with proper lifecycle serialization — never runs concurrently with agent interviews or report generation
**Plans**: 3 plans

Plans:
- [ ] 41-01-PLAN.md -- AdvisoryItem type, synthesize() function, bracket consensus join logic, unit tests
- [ ] 41-02-PLAN.md -- POST /api/advisory/{cycle_id} route, lifespan wiring, canary activation (ISOL-07 flip)
- [ ] 41-03-PLAN.md -- AdvisoryPanel.vue, ControlBar Advisory button, App.vue wiring, human verification

## Progress

**Execution Order:**
Phases execute in numeric order: 37 -> 38 -> 39 -> 40 -> 41

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1–10. v1.0 Core Engine | v1.0 | ✓ | Complete | 2026-03-27 |
| 11–15. v2.0 Engine Depth | v2.0 | ✓ | Complete | 2026-04-02 |
| 24–28. v4.0 Interactive | v4.0 | ✓ | Complete | 2026-04-12 |
| 29–36. v5.0 Web UI | v5.0 | ✓ | Complete | 2026-04-18 |
| 37. Isolation Foundation + Provider Scaffolding | v6.0 | 4/4 | Complete | 2026-04-18 |
| 38. Market Data + News Providers | v6.0 | 3/3 | Complete    | 2026-04-18 |
| 39. Holdings Loader | v6.0 | 0/2 | Not started | — |
| 40. Simulation Context Wiring | v6.0 | 0/2 | Not started | — |
| 41. Advisory Pipeline | v6.0 | 0/3 | Not started | — |
