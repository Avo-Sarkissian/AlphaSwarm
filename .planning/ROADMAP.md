# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** - Phases 1-10 (shipped 2026-03-27)
- [x] **v2.0 Engine Depth** - Phases 11-15 (shipped 2026-04-02)
- [x] **v4.0 Interactive Simulation & Analysis** - Phases 24-28 (shipped 2026-04-12)
- [x] **v5.0 Web UI** — Phases 29-36 (shipped 2026-04-18)
- [ ] **v6.0 Data Enrichment & Personalized Advisory** — Phases 37-43 (started 2026-04-18)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Core Engine (Phases 1-10) - SHIPPED 2026-03-27</summary>

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

### v2.0 Engine Depth (Phases 11-15)

**Milestone Goal:** Deepen the simulation engine with live graph memory, richer agent behavior, dynamic persona generation, post-simulation interviews, and structured report generation -- building the full analytical data model.

- [x] **Phase 11: Live Graph Memory** - Real-time Neo4j rationale episodes, narrative edges, and interview context summaries written during simulation (completed 2026-03-31)
- [x] **Phase 12: Richer Agent Interactions** - Agents publish public rationale posts that peers read and react to via token-budget-aware context injection (completed 2026-04-01)
- [x] **Phase 13: Dynamic Persona Generation** - Entity-aware bracket modifiers generated from seed rumor for situation-specific agent personas (completed 2026-04-02)
- [x] **Phase 14: Agent Interviews** - Post-simulation conversational Q&A with any agent using reconstructed decision context (completed 2026-04-02)
- [x] **Phase 15: Post-Simulation Report** - ReACT agent queries Neo4j and generates structured market analysis as exportable markdown (completed 2026-04-02)

## Phase Details

### Phase 11: Live Graph Memory
**Goal**: Neo4j becomes a living memory that captures per-agent reasoning arcs, narrative connections, and decision context as the simulation runs -- not just a post-round data dump
**Depends on**: Phase 10 (v1 complete)
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03
**Success Criteria** (what must be TRUE):
  1. After a simulation completes, each agent has a RationaleEpisode node per round in Neo4j containing their rationale text, timestamps, peer context received, and signal flip detection
  2. Narrative REFERENCES edges connect Decision nodes to Entity nodes extracted during seed injection, queryable by entity name
  3. Running a Cypher query against a completed simulation returns a complete 3-round reasoning arc for any agent (decisions, rationale episodes, influence relationships, and entity references)
  4. Write performance remains stable -- batch UNWIND pattern keeps Neo4j transaction count under 10 per round (not 100 per-agent transactions)
**Plans**: 3 plans
Plans:
- [x] 11-01-PLAN.md -- FlipType enum, WriteBuffer module, and compute_flip_type with unit tests
- [x] 11-02-PLAN.md -- GraphStateManager extensions (4 new methods, schema, decision_id refactor)
- [x] 11-03-PLAN.md -- Simulation integration (WriteBuffer wiring, narrative generation, integration tests)

### Phase 12: Richer Agent Interactions
**Goal**: Agents influence each other through published rationale content, not just signal votes, creating observable social dynamics in the simulation graph
**Depends on**: Phase 11
**Requirements**: SOCIAL-01, SOCIAL-02
**Success Criteria** (what must be TRUE):
  1. Each agent's decision output includes a public_rationale field that is stored as a Post node in Neo4j with zero additional inference calls
  2. In Rounds 2 and 3, each agent receives top-K ranked peer rationale posts (by influence weight) as part of their prompt context, with a strict token budget preventing context window overflow
  3. READ_POST edges in Neo4j trace which agents read which posts, enabling post-simulation analysis of information flow
  4. Agent outputs in Rounds 2-3 show observable reactions to peer rationale content (citations, agreement, disagreement) compared to Round 1 baseline
**Plans**: 2 plans
Plans:
- [x] 12-01-PLAN.md -- Post node data layer (RankedPost type, write_posts, read_ranked_posts, write_read_post_edges, schema index, tests)
- [x] 12-02-PLAN.md -- Simulation integration (budget-aware _format_peer_context, run_simulation wiring, test updates)

### Phase 13: Dynamic Persona Generation
**Goal**: The simulation generates situation-specific agent personas from the seed rumor itself, so agents have domain-relevant expertise and biases tailored to the scenario
**Depends on**: Phase 11
**Requirements**: PERSONA-01, PERSONA-02
**Success Criteria** (what must be TRUE):
  1. Given a seed rumor about a specific domain (e.g., oil markets, tech earnings), the orchestrator LLM generates entity-specific bracket modifiers in a single JSON call
  2. Generated modifiers are injected into the existing generate_personas() pipeline, producing 100 agents across 10 brackets with situation-aware system prompts while preserving the bracket structure and agent count invariant
  3. Input sanitization prevents prompt injection via adversarial seed rumor entity names -- entity text is validated, length-limited, and never concatenated raw into system prompts
**Plans**: 2 plans
Plans:
- [x] 13-01-PLAN.md -- Data layer: ParsedModifiersResult type, sanitize_entity_name, parse_modifier_response 3-tier fallback, generate_personas modifiers kwarg, tests
- [x] 13-02-PLAN.md -- Integration: generate_modifiers orchestrator call, inject_seed modifier callback, run_simulation wiring

### Phase 14: Agent Interviews
**Goal**: After simulation completes, users can select any agent and have a live multi-turn conversation about their decisions, with the agent responding in character using full decision context
**Depends on**: Phase 11
**Requirements**: INT-01, INT-02, INT-03
**Success Criteria** (what must be TRUE):
  1. Selecting an agent reconstructs their full context from Neo4j -- persona, all 3 rounds of decisions, rationale history, peer influences received, and entity references
  2. The agent responds conversationally in character using the worker LLM with their original system prompt restored, maintaining consistency with their simulation decisions across multiple exchanges
  3. Users can interview agents via the TUI by clicking any agent cell in the grid post-simulation, opening an interactive Q&A panel with clean exit back to the dashboard
  4. Interview sessions use a sliding window for conversation history to prevent context overflow during extended exchanges
**Plans**: 2 plans
Plans:
- [x] 14-01-PLAN.md -- Interview data layer and engine (InterviewContext/RoundDecision types, read_agent_interview_context graph method, InterviewEngine with sliding window, unit tests)
- [x] 14-02-PLAN.md -- TUI integration (InterviewScreen overlay, AgentCell.on_click handler, cycle_id capture, human verification)
**UI hint**: yes

### Phase 15: Post-Simulation Report
**Goal**: A ReACT agent autonomously queries the simulation graph and produces a structured market analysis report that synthesizes 300 agent decisions into actionable narrative
**Depends on**: Phase 11
**Requirements**: REPORT-01, REPORT-02, REPORT-03
**Success Criteria** (what must be TRUE):
  1. The ReACT agent completes a Thought-Action-Observation loop using prompt-based tool dispatching (no Ollama native tools), with a hard cap of 8-10 iterations and duplicate call detection
  2. Cypher query tools return structured data for bracket consensus summaries, influence topology leaders, entity-level sentiment trends, and signal flip metrics
  3. A CLI `report` subcommand generates a structured markdown report and exports it to a file via aiofiles, with the file path displayed in the TUI
  4. The report contains distinct analytical sections (consensus summary, key dissenters, bracket narratives, entity impact analysis) rendered from Jinja2 templates
  5. Report generation uses the orchestrator model with proper model lifecycle serialization -- never runs concurrently with agent interviews
**Plans**: 2 plans
Plans:
- [x] 15-01-PLAN.md -- ReACT engine + Cypher query tools (ReportEngine, ToolObservation, _parse_action_input, 8 GraphStateManager read methods, unit tests)
- [x] 15-02-PLAN.md -- Delivery layer (Jinja2 templates, ReportAssembler, CLI report subcommand, aiofiles export, sentinel file, TUI polling)

### v4.0 Interactive Simulation & Analysis (Phases 24-28)

**Milestone Goal:** Add mid-simulation shock injection, real-time impact analysis, HTML report export with Schwab portfolio overlay, and simulation replay — completing the full interactive analysis suite.

- [x] **Phase 24: HTML Report Export** - Exportable HTML simulation reports with SVG charts and Schwab portfolio overlay (completed 2026-04-09)
- [x] **Phase 26: Shock Injection Core** - Mid-simulation shock injection with governor suspend/resume and ReplayStore isolation (completed 2026-04-10)
- [x] **Phase 27: Shock Analysis and Reporting** - Shock impact analysis with bracket delta mode, read_shock_impact, and Jinja2 shock template (completed 2026-04-11)
- [x] **Phase 28: Simulation Replay** - Re-render a past simulation cycle from stored Neo4j state without re-running inference (completed 2026-04-12)

### Phase 28: Simulation Replay
**Goal**: Re-render any completed simulation cycle from stored Neo4j state, stepping through rounds 1-3 in the TUI without re-running agent inference
**Depends on**: Phase 27
**Requirements**: REPLAY-01
**Success Criteria** (what must be TRUE):
  1. A CLI `replay` subcommand accepts a `cycle_id` and re-populates the TUI grid round-by-round from Neo4j decision data
  2. The existing TUI dashboard (agent grid, bracket panel, rationale sidebar) renders correctly from replayed state with no live inference calls
  3. `read_full_cycle_signals()` Cypher query completes in under 2s for cycles with 600+ nodes (COLLECT aggregation profiled and optimized)
  4. Replay mode is visually distinct from live simulation (e.g., header shows "REPLAY -- Cycle {id}")
**Plans**: 3 plans

Plans:
- [x] 28-01-PLAN.md -- Wave 0 tests, SimulationPhase.REPLAY enum, ReplayStore class, 4 GraphStateManager read methods
- [x] 28-02-PLAN.md -- CLI replay subcommand, TUI replay mode (CyclePickerScreen, key bindings, auto-advance, header/footer rendering)
- [x] 28-03-PLAN.md -- Human verification of TUI replay visual and interactive behavior

### v5.0 Web UI (Phases 29-36)

**Milestone Goal:** Replace the Textual TUI with a browser-based Vue 3 + FastAPI web UI — live force-directed agent graph, simulation controls, shock injection, monitoring panels, replay mode, agent interviews, and report viewer.

- [x] **Phase 29: FastAPI Skeleton and Event Loop Foundation** - FastAPI app with lifespan, WebSocket state stream, and async event loop wiring (completed 2026-04-13)
- [x] **Phase 30: WebSocket State Stream** - Real-time StateSnapshot broadcast over WebSocket with connection manager (completed 2026-04-13)
- [x] **Phase 31: Vue SPA and Force-Directed Graph** - Vue 3 + Vite SPA with D3 force-directed agent graph, sidebar, and WebSocket composable (completed 2026-04-14)
- [x] **Phase 32: REST Controls and Simulation Control Bar** - Simulation start/stop/shock REST endpoints, replay contract stubs, and Vue control bar with shock drawer (completed 2026-04-14)
- [x] **Phase 33: Web Monitoring Panels** - Live rationale feed with animated entries and D3 bracket sentiment bars in the browser (completed 2026-04-15)
- [x] **Phase 34: Replay Mode Web UI** - Cycle picker, round stepping, and force graph re-render from stored Neo4j state (wires Phase 32 stubs) (completed 2026-04-15)
- [x] **Phase 35: Agent Interviews Web UI** - Click any post-simulation graph node to open a live multi-turn interview panel in the browser (completed 2026-04-16)
- [x] **Phase 35.1: Shock Injection Wiring** (INSERTED) - Bugfix closure wiring shock drawer submission into ShockEvent persistence end-to-end (completed 2026-04-16)
- [x] **Phase 36: Report Viewer** - Fetch and render the post-simulation market analysis report as a formatted panel within the SPA (completed 2026-04-17)

### Phase 33: Web Monitoring Panels
**Goal**: Bring full observability into the browser — live rationale feed with animated entries and D3 bracket sentiment bars updating from the WebSocket snapshot, matching the TUI panel equivalents
**Depends on**: Phase 31 (Vue SPA and WebSocket snapshot)
**Requirements**: WEB-03, WEB-04
**Success Criteria** (what must be TRUE):
  1. A rationale feed panel shows the latest agent reasoning entries with slide-in animation as new entries arrive via the WebSocket snapshot
  2. Bracket sentiment bars render as D3 SVG charts with one bar per bracket, updating after each round from `snapshot.bracket_summaries`
  3. Layout is responsive — panels fit alongside the force graph without clipping or overflow
  4. Feed is capped (e.g. 20 entries) with oldest entries fading out to prevent unbounded DOM growth
**Plans**: 2 plans
Plans:
- [x] 33-01-PLAN.md -- Foundation layer: d3-transition dep, CSS vars, allRationales composable, BracketPanel.vue, RationaleFeed.vue
- [x] 33-02-PLAN.md -- App.vue layout integration and human visual verification

### Phase 34: Replay Mode Web UI
**Goal**: Wire the Phase 32 replay contract stubs into a real browser replay experience — cycle picker, round-by-round stepping, and live force graph re-render from Neo4j state without new inference
**Depends on**: Phase 32 (replay REST endpoints), Phase 31 (force graph)
**Requirements**: WEB-06, REPLAY-01
**Success Criteria** (what must be TRUE):
  1. `GET /api/replay/cycles` populates a cycle picker UI; user selects a completed cycle to replay
  2. `POST /api/replay/start/{cycle_id}` loads Round 1 agent states into the force graph; nodes update color and position from stored decisions
  3. `POST /api/replay/advance` steps to the next round; force graph transitions to the new round state
  4. Replay mode is visually distinct from live simulation (e.g. a "REPLAY" banner or header badge)
  5. The force graph's node click → sidebar flow works identically in replay mode
**Plans**: 3 plans

Plans:
- [x] 34-01-PLAN.md -- ReplayManager class, replay route implementations, broadcaster coupling, Wave 0 tests
- [x] 34-02-PLAN.md -- CSS tokens, CyclePicker.vue modal, ControlBar replay strip, ForceGraph edge-clear fix, App.vue wiring
- [x] 34-03-PLAN.md -- Human verification of replay mode in browser

### Phase 35: Agent Interviews Web UI
**Goal**: Click any agent node in the post-simulation force graph to open a live multi-turn interview panel that proxies to the existing InterviewEngine, letting users interrogate agent decisions in the browser
**Depends on**: Phase 31 (force graph node click), Phase 14 (InterviewEngine)
**Requirements**: WEB-06
**Success Criteria** (what must be TRUE):
  1. A new `POST /api/interview/{agent_id}` REST endpoint reconstructs agent context from Neo4j via InterviewEngine and returns the agent's response
  2. Clicking a node in post-simulation state opens a slide-in interview panel (distinct from the existing AgentSidebar)
  3. The panel supports multi-turn conversation — each user message calls the endpoint and appends the response
  4. The panel can be dismissed; the force graph and sidebar remain interactive behind it
  5. Interview calls are non-blocking — a loading indicator shows while the LLM responds
**Plans**: 3 plans

Plans:
- [x] 35-01-PLAN.md -- Interview route, tests, lifespan wiring (backend)
- [x] 35-02-PLAN.md -- InterviewPanel.vue, AgentSidebar button, App.vue wiring (frontend)
- [x] 35-03-PLAN.md -- Human verification of interview flow in browser

### Phase 35.1: Shock Injection Wiring (INSERTED)
**Goal**: Close the shock injection integration gap — wire ShockDrawer submission to ShockEvent persistence in Neo4j with end-to-end verification
**Depends on**: Phase 35
**Requirements**: REPLAY-03 (partial)
**Plans**: 2 plans

Plans:
- [x] 35.1-01-PLAN.md -- Backend wiring + Neo4j persistence
- [x] 35.1-02-PLAN.md -- Frontend submit flow + E2E verification

### Phase 36: Report Viewer
**Goal**: Surface the post-simulation market analysis report (generated by Phase 15's ReportAssembler) directly in the browser as a readable formatted panel, completing the full web UI feature set
**Depends on**: Phase 35, Phase 15 (ReportAssembler and CLI report command)
**Requirements**: WEB-06, REPORT-02
**Success Criteria** (what must be TRUE):
  1. A new `GET /api/report/{cycle_id}` endpoint serves the generated report for a completed cycle (reads from the exported file or triggers generation if missing)
  2. A Report Viewer panel renders the report with formatted sections (consensus summary, bracket narratives, entity impact analysis)
  3. The viewer is accessible from the control bar or sidebar after simulation completes
  4. If no report exists yet, the panel shows a "Generate Report" button that triggers report generation and polls for completion
**Plans**: 2 plans

Plans:
- [x] 36-01-PLAN.md -- Report route (GET + POST /generate), background task, tests, lifespan wiring (backend)
- [x] 36-02-PLAN.md -- ReportViewer.vue modal with marked+DOMPurify, ControlBar Report button, App.vue mount, human verification (frontend)

### v6.0 Data Enrichment & Personalized Advisory (Phases 37-43)

**Milestone Goal:** Transform AlphaSwarm from isolated rumor simulator into an informed advisory system. The swarm reasons on real market data via frozen `ContextPacket` slices; the orchestrator synthesizes personalized recommendations against an in-memory holdings CSV — with strict information isolation enforced by importlinter contracts, pydantic `extra="forbid"` schemas, PII log redaction, and a sentinel-based canary test. Holdings never enter any worker prompt, Neo4j node, or WebSocket frame.

**Architecture principle (Option A — locked):** ingestion layer fetches data (yfinance, RSS/NewsAPI) → swarm consumes `ContextPacket` only → orchestrator is synthesis-only: holdings + swarm output → advisory markdown.

- [ ] **Phase 37: Isolation Foundation & Provider Scaffolding** - Frozen type boundaries, importlinter contract, pytest-socket, PII redaction, and canary scaffold — every downstream phase inherits the invariant
- [ ] **Phase 38: Market Data + News Ingestion** - AsyncTTLCache, YFinanceProvider with tenacity + graceful degradation, RSSProvider primary + NewsAPI optional, VCR cassette tests
- [ ] **Phase 39: Holdings CSV Ingestion** - Broker adapter pattern (Schwab, Fidelity, generic), in-memory HoldingsStore, drag-drop uploader with confirm gate, Neo4j schema assertion (no Holding/Position labels)
- [ ] **Phase 40: Context Packet Assembly & Swarm Injection** - Pure-function ContextAssembler with per-archetype slicing, 2000-token budget enforced, SimulationPhase.INGESTING, 100-agent scale smoke test
- [ ] **Phase 41: Advisory Pipeline (Orchestrator Synthesis)** - AdvisoryPipeline as the only holdings+swarm join point, closed-universe grounding, post-synthesis ticker validator, explicit abstention, SEC-style disclaimer, SimulationPhase.ADVISING
- [ ] **Phase 42: Advisory Web UI** - AdvisoryPanel.vue with persistent disclaimer banner, AdvisoryReportPublic WS model, explicit allowlist serializer, sentinel-based WS contract test
- [ ] **Phase 43: v6 E2E & Carry-Forward Validation** - Full CSV → advisory E2E, 5-run RSS cache plateau, final log-grep isolation audit, v5.0 carry-forward debt resolution

### Phase 37: Isolation Foundation & Provider Scaffolding
**Goal**: Establish the frozen type boundaries, import contracts, network gates, and PII redaction that every downstream v6.0 phase inherits — before any ingestion, holdings, or advisory code exists
**Depends on**: v5.0 complete (Phase 36)
**Requirements**: ISOL-01, ISOL-02, ISOL-03, ISOL-04, ISOL-05, ISOL-06, ISOL-07
**Success Criteria** (what must be TRUE):
  1. `Holding`, `PortfolioSnapshot`, `ContextPacket`, `MarketSlice`, and `NewsSlice` frozen dataclasses exist with `extra="forbid"` and zero holdings fields on the swarm-side types
  2. importlinter CI gate fails on an intentional violation commit (simulation/worker/ingestion/seed/parsing cannot import `alphaswarm.holdings`) and passes on the clean tree
  3. Canary test `test_holdings_isolation.py` runs with sentinel ticker/cost-basis fixtures and passes trivially (no join point yet — activated in Phase 41)
  4. `pytest-socket` in CI causes any outbound network call during the test suite to fail loudly
  5. structlog PII redaction processor is globally installed — a fuzz test injecting known sensitive keys (`holdings`, `portfolio`, `cost_basis`) produces zero verbatim values in the log stream
**Estimated complexity**: Medium — scaffolding-heavy but low-risk; no business logic, tight defensive invariants
**Plans**: TBD

### Phase 38: Market Data + News Ingestion
**Goal**: Ship rate-limited, cache-backed async providers for yfinance market data and RSS/NewsAPI news — with graceful degradation, staleness metadata, and a fully offline test suite
**Depends on**: Phase 37 (isolation types + provider protocols + pytest-socket)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06, INGEST-07
**Success Criteria** (what must be TRUE):
  1. yfinance 429 mock (via VCR cassette or `FakeMarketDataProvider`) triggers tenacity exponential backoff and, on persistent failure, produces a `MarketSlice` with `{data: null, staleness: "fetch_failed"}` rather than crashing the simulation
  2. Every market-data field in a built `MarketSlice` carries `fetched_at`, `source`, and `freshness` metadata (market-hours-aware TTL honored)
  3. RSSProvider deduplicates by content hash, honors 72h freshness window, and caps at 2 items per source per entity; NewsAPIProvider is only invoked when `settings.news.newsapi_enabled=True` (default off)
  4. `pytest-socket` blocks real outbound network calls across the full test suite; provider contracts are tested against recorded VCR cassettes
  5. `AsyncTTLCache` unit test proves two concurrent `get()` calls on the same key coalesce to one backing fetch (lock correctness)
**Estimated complexity**: High — external dependency quirks (yfinance 429 behavior, RSS feed variety), cache correctness under concurrency
**Plans**: TBD

### Phase 39: Holdings CSV Ingestion
**Goal**: Load user holdings via drag-drop CSV with broker-specific adapters and a generic column-mapping fallback — storing parsed portfolios in-memory only, never serialized to Neo4j or disk
**Depends on**: Phase 37 (Holding/PortfolioSnapshot types + importlinter + PII redaction)
**Requirements**: HOLD-01, HOLD-02, HOLD-03, HOLD-04, HOLD-05, HOLD-06, HOLD-07, HOLD-08
**Success Criteria** (what must be TRUE):
  1. Schwab and Fidelity golden-fixture CSVs load into `PortfolioSnapshot` without any code changes (TS-01 — broker fingerprint dispatch works); an unknown broker routes to the generic column-mapping UI without crashing
  2. Neo4j schema assertion test enumerates all node labels in the running graph after a full simulation and confirms no `:Holding` or `:Position` labels ever exist
  3. Pydantic row-level validation errors (e.g., "row 7 column 'Qty' couldn't parse '-'") are surfaced to the UI preview table; `HoldingsStore` only commits after explicit user "Confirm"
  4. `POST /api/holdings/upload` → preview → `GET /api/holdings/status` round-trip works in the browser; raw account numbers are SHA256-hashed before any storage or log output
  5. `HoldingsStore` singleton on `app.state` is cleared on FastAPI lifespan shutdown; no holdings survive a process restart
**Estimated complexity**: Medium — well-known CSV schema drift patterns, but broker-adapter boilerplate plus UI column-mapping flow
**Plans**: TBD
**UI hint**: yes

### Phase 40: Context Packet Assembly & Swarm Injection
**Goal**: Bridge ingestion output to the swarm via a pure-function `ContextAssembler` that enforces a 2000-token budget, per-archetype filter-not-expand slicing, and emits `SimulationPhase.INGESTING` — without regressing the existing 193+ test suite
**Depends on**: Phase 38 (ingestion providers), Phase 39 (holdings types — for isolation assertions)
**Requirements**: CTX-01, CTX-02, CTX-03, CTX-04, CTX-05, CTX-06, CTX-07, CTX-08
**Success Criteria** (what must be TRUE):
  1. 100-agent × full-packet scale smoke test completes without any `ResourceGovernor` pause transition (regression guard for `bug_governor_deadlock.md` re-emergence from prompt bloat)
  2. `MAX_WORKER_CONTEXT_TOKENS = 2000` is enforced at packet assembly; every `build_agent_prompt()` unit test asserts `count_tokens(prompt) <= budget` at N=100 agents
  3. `simulation.py` accepts an optional `context_packet` parameter and the existing test suite passes unchanged when `context_packet=None` (backward-compatible)
  4. `slice_for(bracket)` returns distinct `ArchetypeSlice` payloads — Quants receive fundamentals+technicals, Degens receive volume ratio+52-week range+headline count
  5. `SimulationPhase.INGESTING` appears in the WebSocket phase stream between SEEDING and ROUND_1 without any broadcaster or UI code changes
**Estimated complexity**: High — token budget empirical calibration, scale smoke test against live governor, swarm-pure module discipline
**Plans**: TBD

### Phase 41: Advisory Pipeline (Orchestrator Synthesis)
**Goal**: Generate the advisory markdown — the one codebase function receiving both holdings and swarm output — with closed-universe grounding, post-synthesis ticker validation, explicit abstention, and SEC-style methodology disclaimer
**Depends on**: Phase 40 (ContextPacket produced), Phase 39 (HoldingsStore populated), Phase 37 (isolation enforcement)
**Requirements**: ADV-01, ADV-02, ADV-03, ADV-04, ADV-05, ADV-06, ADV-07, ADV-08, ADV-09, ADV-10, ADV-11, ADV-12, ADV-13
**Success Criteria** (what must be TRUE):
  1. Empty-holdings input produces a "No actionable signal" advisory — never a fabricated report; weak-signal consensus across held tickers also abstains
  2. Post-synthesis regex validator extracts uppercase tickers; a fabricated ticker (not in `holdings_tickers ∪ swarm_entities`) is rejected, regenerated up to 2 times, and on persistent failure surfaces an explicit `"Advisory validation failed"` error rather than silently passing through
  3. `temperature=0.1` and `top_p=0.8` are asserted in an orchestrator config test; `SimulationPhase.ADVISING` fires between Round 3 and COMPLETE; advisory markdown is written to `reports/{cycle_id}/advisory.md` via aiofiles
  4. `settings.advisory.enabled=False` fully disables the advisory step — the simulator reverts to v5.0 pure-rumor behavior and the existing 193+ tests continue passing
  5. Generated advisory uses qualitative language only ("Review / Monitor / No action indicated"), carries the non-optional SEC-style methodology disclaimer block, and cites specific `RationaleEpisode` rationale snippets (reusing v2 live-graph-memory infrastructure)
**Estimated complexity**: High — prompt-engineering iteration cycles, validator correctness under adversarial fabrications, orchestrator model-lifecycle coordination with existing OllamaModelManager
**Plans**: TBD

### Phase 42: Advisory Web UI
**Goal**: Surface the Phase 41 advisory in the browser via a markdown panel with a persistent "not investment advice" banner, staleness chips, and a WebSocket contract that provably cannot leak holdings
**Depends on**: Phase 41 (advisory artifact exists)
**Requirements**: ADVUI-01, ADVUI-02, ADVUI-03, ADVUI-04, ADVUI-05, ADVUI-06
**Success Criteria** (what must be TRUE):
  1. WebSocket sentinel contract test passes: a sentinel ticker (`HOLDINGS_CANARY_TICKER_ZZZ`) inserted into fixture holdings never appears in any WS frame across a full simulation end-to-end
  2. `AdvisoryPanel.vue` renders the advisory markdown via `GET /api/advisory/{cycle_id}` (not via the WebSocket payload) — panel is not populated unless the REST fetch succeeds
  3. `POST /api/advisory/generate` mirrors the Phase 36 report route pattern (non-blocking 202 Accepted, background asyncio.Task); `GET /api/advisory/{cycle_id}` returns 404 until generation completes
  4. Explicit allowlist serializer `snapshot_to_ws_payload()` is the only function that constructs WS snapshot dicts; adding any new field requires modifying this function (catches drift at code-review time)
  5. Persistent "Simulation output — not investment advice" banner is rendered on every advisory render; staleness chips appear next to every data point from the context packet; empty-advisory state shows a clean "no advisory yet" message (not a broken view)
**Estimated complexity**: Medium — well-trodden Phase 36 ReportViewer pattern; main novelty is the serializer allowlist + sentinel contract test
**Plans**: TBD
**UI hint**: yes

### Phase 43: v6 E2E & Carry-Forward Validation
**Goal**: Full milestone validation via end-to-end run with a sentinel holdings fixture, plus resolution of all v5.0 carry-forward tech debt (phase 29 backfill, Nyquist VALIDATION.md for phases 29/31/35.1, nine human UAT items across phases 32/34/36)
**Depends on**: Phases 37, 38, 39, 40, 41, 42 (all prior v6.0 phases)
**Requirements**: V6UAT-01, V6UAT-02, V6UAT-03, V6UAT-04, V6UAT-05, V6UAT-06, V6UAT-07, V6UAT-08
**Success Criteria** (what must be TRUE):
  1. Full E2E happy path: CSV upload → confirm → seed rumor → INGESTING → Rounds 1-3 → ADVISING → advisory panel rendered with non-fabricated recommendations and SEC disclaimer — completes without error
  2. Final isolation audit — log-grep over the full simulation log with sentinel holdings fixture (`HOLDINGS_CANARY_TICKER_ZZZ`, `SECRET_COST_BASIS_999999`) finds zero matches outside the advisory module path
  3. 5-run RSS telemetry plateau confirmed — RSS (psutil) does not grow monotonically across 5 consecutive full simulations (no cache memory leak regression)
  4. Advisory abstention validated on two edge cases: empty-holdings input yields "No actionable signal"; a weak-consensus run over held tickers also abstains rather than fabricating a recommendation
  5. v5.0 carry-forward debt resolved or re-deferred with documented reason — Phase 29 planning artifact backfill complete; VALIDATION.md written for phases 29, 31, 35.1; all nine human UAT items from phases 32/34/36 have explicit resolution ("verified", "deferred to v7.0 with reason", or "superseded by v6.0 change")
**Estimated complexity**: Medium — integration-heavy but no new business logic; the bulk is disciplined UAT walk-through plus carry-forward paperwork
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 11 -> 12 -> 13 -> 14 -> 15 -> 24 -> 26 -> 27 -> 28 -> 29 -> 30 -> 31 -> 32 -> 33 -> 34 -> 35 -> 35.1 -> 36 -> 37 -> 38 -> 39 -> 40 -> 41 -> 42 -> 43

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Project Foundation | v1.0 | 2/2 | Complete | 2026-03-24 |
| 2. Ollama Integration | v1.0 | 3/3 | Complete | 2026-03-25 |
| 3. Resource Governance | v1.0 | 2/2 | Complete | 2026-03-25 |
| 4. Neo4j Graph State | v1.0 | 2/2 | Complete | 2026-03-25 |
| 5. Seed Injection and Agent Personas | v1.0 | 2/2 | Complete | 2026-03-26 |
| 6. Round 1 Standalone | v1.0 | 1/1 | Complete | 2026-03-26 |
| 7. Rounds 2-3 Peer Influence and Consensus | v1.0 | 2/2 | Complete | 2026-03-26 |
| 8. Dynamic Influence Topology | v1.0 | 3/3 | Complete | 2026-03-26 |
| 9. TUI Core Dashboard | v1.0 | 2/2 | Complete | 2026-03-27 |
| 10. TUI Panels and Telemetry | v1.0 | 2/2 | Complete | 2026-03-27 |
| 11. Live Graph Memory | v2.0 | 3/3 | Complete | 2026-03-31 |
| 12. Richer Agent Interactions | v2.0 | 2/2 | Complete | 2026-04-01 |
| 13. Dynamic Persona Generation | v2.0 | 2/2 | Complete | 2026-04-02 |
| 14. Agent Interviews | v2.0 | 2/2 | Complete | 2026-04-02 |
| 15. Post-Simulation Report | v2.0 | 2/2 | Complete | 2026-04-02 |
| 24. HTML Report Export | v4.0 | -- | Complete | 2026-04-09 |
| 26. Shock Injection Core | v4.0 | 5/5 | Complete | 2026-04-10 |
| 27. Shock Analysis and Reporting | v4.0 | 3/3 | Complete | 2026-04-11 |
| 28. Simulation Replay | v4.0 | 3/3 | Complete | 2026-04-12 |
| 29. FastAPI Skeleton and Event Loop Foundation | v5.0 | -- | Complete | 2026-04-13 |
| 30. WebSocket State Stream | v5.0 | -- | Complete | 2026-04-13 |
| 31. Vue SPA and Force-Directed Graph | v5.0 | 4/4 | Complete | 2026-04-14 |
| 32. REST Controls and Simulation Control Bar | v5.0 | 4/4 | Complete | 2026-04-14 |
| 33. Web Monitoring Panels | v5.0 | 2/2 | Complete    | 2026-04-15 |
| 34. Replay Mode Web UI | v5.0 | 3/3 | Complete   | 2026-04-15 |
| 35. Agent Interviews Web UI | v5.0 | 3/3 | Complete | 2026-04-16 |
| 35.1. Shock Injection Wiring | v5.0 | 2/2 | Complete | 2026-04-16 |
| 36. Report Viewer | v5.0 | 2/2 | Complete    | 2026-04-17 |
| 37. Isolation Foundation & Provider Scaffolding | v6.0 | 0/? | Not started | - |
| 38. Market Data + News Ingestion | v6.0 | 0/? | Not started | - |
| 39. Holdings CSV Ingestion | v6.0 | 0/? | Not started | - |
| 40. Context Packet Assembly & Swarm Injection | v6.0 | 0/? | Not started | - |
| 41. Advisory Pipeline (Orchestrator Synthesis) | v6.0 | 0/? | Not started | - |
| 42. Advisory Web UI | v6.0 | 0/? | Not started | - |
| 43. v6 E2E & Carry-Forward Validation | v6.0 | 0/? | Not started | - |
