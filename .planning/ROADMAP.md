# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** - Phases 1-10 (shipped 2026-03-27)
- [x] **v2.0 Engine Depth** - Phases 11-15 (shipped 2026-04-02)
- [x] **v4.0 Interactive Simulation & Analysis** - Phases 24-28 (shipped 2026-04-12)
- [ ] **v5.0 Web UI** - Phases 29-36 (in progress)

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
- [ ] **Phase 33: Web Monitoring Panels** - Live rationale feed with animated entries and D3 bracket sentiment bars in the browser
- [ ] **Phase 34: Replay Mode Web UI** - Cycle picker, round stepping, and force graph re-render from stored Neo4j state (wires Phase 32 stubs)
- [ ] **Phase 35: Agent Interviews Web UI** - Click any post-simulation graph node to open a live multi-turn interview panel in the browser
- [ ] **Phase 36: Report Viewer** - Fetch and render the post-simulation market analysis report as a formatted panel within the SPA

### Phase 33: Web Monitoring Panels
**Goal**: Bring full observability into the browser — live rationale feed with animated entries and D3 bracket sentiment bars updating from the WebSocket snapshot, matching the TUI panel equivalents
**Depends on**: Phase 31 (Vue SPA and WebSocket snapshot)
**Requirements**: WEB-03, WEB-04
**Success Criteria** (what must be TRUE):
  1. A rationale feed panel shows the latest agent reasoning entries with slide-in animation as new entries arrive via the WebSocket snapshot
  2. Bracket sentiment bars render as D3 SVG charts with one bar per bracket, updating after each round from `snapshot.bracket_summaries`
  3. Layout is responsive — panels fit alongside the force graph without clipping or overflow
  4. Feed is capped (e.g. 20 entries) with oldest entries fading out to prevent unbounded DOM growth
**Plans**: TBD

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
**Plans**: TBD

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
**Plans**: TBD

### Phase 36: Report Viewer
**Goal**: Surface the post-simulation market analysis report (generated by Phase 15's ReportAssembler) directly in the browser as a readable formatted panel, completing the full web UI feature set
**Depends on**: Phase 35, Phase 15 (ReportAssembler and CLI report command)
**Requirements**: WEB-06, REPORT-02
**Success Criteria** (what must be TRUE):
  1. A new `GET /api/report/{cycle_id}` endpoint serves the generated report for a completed cycle (reads from the exported file or triggers generation if missing)
  2. A Report Viewer panel renders the report with formatted sections (consensus summary, bracket narratives, entity impact analysis)
  3. The viewer is accessible from the control bar or sidebar after simulation completes
  4. If no report exists yet, the panel shows a "Generate Report" button that triggers report generation and polls for completion
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 11 -> 12 -> 13 -> 14 -> 15 -> 24 -> 26 -> 27 -> 28 -> 29 -> 30 -> 31 -> 32 -> 33 -> 34 -> 35 -> 36

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
| 33. Web Monitoring Panels | v5.0 | 0/0 | Planned | — |
| 34. Replay Mode Web UI | v5.0 | 0/0 | Planned | — |
| 35. Agent Interviews Web UI | v5.0 | 0/0 | Planned | — |
| 36. Report Viewer | v5.0 | 0/0 | Planned | — |
