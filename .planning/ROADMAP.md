# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** — Phases 1-10 (shipped 2026-03-27)
- [x] **v2.0 Engine Depth** — Phases 11-15 (shipped 2026-04-02)
- [x] **v4.0 Interactive Simulation & Analysis** — Phases 24-28 (shipped 2026-04-12)
- [ ] **v5.0 Web UI** — Phases 29-36 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Core Engine (Phases 1-10) — SHIPPED 2026-03-27</summary>

- [x] **Phase 1: Project Foundation** — Scaffold, configuration system, type definitions, and structured logging (completed 2026-03-24)
- [x] **Phase 2: Ollama Integration** — Async LLM client, sequential model loading, and structured output parsing (completed 2026-03-25)
- [x] **Phase 3: Resource Governance** — Dynamic concurrency control, memory monitoring, task safety, and retry logic (completed 2026-03-25)
- [x] **Phase 4: Neo4j Graph State** — Graph schema with cycle-scoped indexes and batch-writing GraphStateManager (completed 2026-03-25)
- [x] **Phase 5: Seed Injection and Agent Personas** — Orchestrator entity extraction and 100 agent personas with decision schema (completed 2026-03-26)
- [x] **Phase 6: Round 1 Standalone** — All 100 agents process a seed rumor independently in a single inference wave (completed 2026-03-26)
- [x] **Phase 7: Rounds 2-3 Peer Influence and Consensus** — Peer context injection and final consensus lock complete the 3-round cascade (completed 2026-03-26)
- [x] **Phase 8: Dynamic Influence Topology** — INFLUENCED_BY edges form from citation patterns, bracket aggregation, and Miro batcher stub (completed 2026-03-26)
- [x] **Phase 9: TUI Core Dashboard** — Agent grid, snapshot-based rendering, and simulation status display (completed 2026-03-27)
- [x] **Phase 10: TUI Panels and Telemetry** — Rationale sidebar, hardware telemetry footer, and bracket aggregation panel (completed 2026-03-27)

See full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>v2.0 Engine Depth (Phases 11-15) — SHIPPED 2026-04-02</summary>

- [x] **Phase 11: Live Graph Memory** — Real-time Neo4j rationale episodes, narrative edges, and interview context summaries written during simulation (completed 2026-03-31)
- [x] **Phase 12: Richer Agent Interactions** — Agents publish public rationale posts that peers read and react to via token-budget-aware context injection (completed 2026-04-01)
- [x] **Phase 13: Dynamic Persona Generation** — Entity-aware bracket modifiers generated from seed rumor for situation-specific agent personas (completed 2026-04-02)
- [x] **Phase 14: Agent Interviews** — Post-simulation conversational Q&A with any agent using reconstructed decision context (completed 2026-04-02)
- [x] **Phase 15: Post-Simulation Report** — ReACT agent queries Neo4j and generates structured market analysis as exportable markdown (completed 2026-04-02)

See full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

<details>
<summary>v4.0 Interactive Simulation & Analysis (Phases 24-28) — SHIPPED 2026-04-12</summary>

- [x] **Phase 24: HTML Report Export** — Exportable HTML simulation reports with SVG charts and Schwab portfolio overlay (completed 2026-04-09)
- [x] **Phase 26: Shock Injection Core** — Mid-simulation shock injection with governor suspend/resume and ReplayStore isolation (completed 2026-04-10)
- [x] **Phase 27: Shock Analysis and Reporting** — Shock impact analysis with bracket delta mode, read_shock_impact, and Jinja2 shock template (completed 2026-04-11)
- [x] **Phase 28: Simulation Replay** — Re-render a past simulation cycle from stored Neo4j state without re-running inference (completed 2026-04-12)

See full details: `.planning/milestones/v4.0-ROADMAP.md`

</details>

### v5.0 Web UI (In Progress)

**Milestone Goal:** Replace the Textual TUI with a Vue 3 + FastAPI web dashboard featuring a live force-directed agent influence graph as the hero feature.

- [x] **Phase 29: FastAPI Skeleton and Event Loop Foundation** — FastAPI app factory with Uvicorn lifespan owning the event loop, non-destructive StateStore snapshot, and per-client WebSocket queue architecture (completed 2026-04-13)
- [x] **Phase 30: WebSocket State Stream** — Real-time WebSocket broadcast of StateSnapshot JSON at 5Hz to all connected browser clients (completed 2026-04-13)
- [x] **Phase 31: Vue SPA and Force-Directed Graph** — Vue 3 SPA with live D3 force-directed graph rendering 100 agent nodes clustered by bracket with animated INFLUENCED_BY edges (completed 2026-04-14)
- [ ] **Phase 32: REST Controls and Simulation Control Bar** — REST endpoints for simulation start, shock injection, replay, and edge queries plus browser-side control bar and shock drawer
- [ ] **Phase 33: Monitoring Panels** — Bracket summary, rationale sidebar, and telemetry strip panels consuming the WebSocket state stream
- [ ] **Phase 34: Replay Mode Web UI** — Web-based replay player with cycle picker, round stepper, and auto-advance consuming the replay REST endpoints
- [ ] **Phase 35: Agent Interview Panel** — Post-simulation agent Q&A via streaming WebSocket with interview gating to COMPLETE phase only
- [ ] **Phase 36: Report Viewer and Final Integration** — Browser-based report generation trigger and HTML report viewing via FastAPI static file serving

## Phase Details

### Phase 29: FastAPI Skeleton and Event Loop Foundation
**Goal**: Uvicorn owns the asyncio event loop and all simulation infrastructure (StateStore, Governor, Neo4j driver) is created inside the FastAPI lifespan context so downstream phases have a correct single-loop foundation
**Depends on**: Phase 28 (v4.0 complete)
**Requirements**: BE-01, BE-02, BE-03
**Success Criteria** (what must be TRUE):
  1. Running `alphaswarm web` starts a Uvicorn server and GET /api/health returns 200 with simulation phase and memory stats
  2. StateStore.snapshot() can be called multiple times in succession without losing rationale entries (non-destructive reads verified by test)
  3. A second WebSocket client connecting does not drain rationale entries that the first client should have received (per-client queue isolation)
  4. POST /api/simulate/start while a simulation is already running returns HTTP 409 (SimulationManager singleton guard)
**Plans:** 5/5 plans complete
Plans:
- [x] 29-01-PLAN.md — Install deps + StateStore non-destructive refactor + TUI call site update
- [x] 29-02-PLAN.md — web/ package scaffold (app factory, lifespan, health endpoint, SimulationManager, ConnectionManager) + tests
- [x] 29-03-PLAN.md — CLI web subparser + integration verification

### Phase 30: WebSocket State Stream
**Goal**: Browser clients receive a live JSON state stream over WebSocket at 5Hz so the frontend can render real-time agent state without polling
**Depends on**: Phase 29
**Requirements**: BE-04
**Success Criteria** (what must be TRUE):
  1. Connecting to ws://localhost:8000/ws/state with wscat during an active simulation produces a continuous stream of JSON snapshots at approximately 200ms intervals
  2. A slow or paused client does not block snapshot delivery to other connected clients (bounded queue with drop-oldest or skip)
  3. Disconnecting a client cleanly removes its writer task with no error logs or resource leaks
**Plans:** 2 plans
Plans:
- [ ] 30-01-PLAN.md — Wave 0 test stubs + broadcaster.py (snapshot_to_json + start_broadcaster) + routes/websocket.py (/ws/state endpoint)
- [ ] 30-02-PLAN.md — Wire broadcaster task and ws_router into app.py + human wscat verification

### Phase 31: Vue SPA and Force-Directed Graph
**Goal**: Users see a live force-directed graph of 100 agent nodes in the browser, clustered by bracket archetype, with signal-colored nodes and animated INFLUENCED_BY edges that appear on each round transition
**Depends on**: Phase 30
**Requirements**: VIS-01, VIS-02, VIS-03, VIS-04
**Success Criteria** (what must be TRUE):
  1. Opening localhost:8000 in a browser during simulation shows 100 agent nodes arranged in a force-directed layout with visible bracket clustering (10 archetype groups)
  2. Agent nodes change color in real time as signals update (green=buy, red=sell, gray=hold) and node size reflects bracket archetype
  3. INFLUENCED_BY edges animate into the graph when a new round completes, fetched from GET /api/edges/{cycle_id}?round=N
  4. Clicking any agent node opens a detail sidebar showing agent name, bracket, current signal, and current-round rationale text
  5. The graph remains smooth (no perpetual bouncing) during 200ms state updates — layout only reheats on topology changes, not on every snapshot
**Plans:** 4/4 plans complete
Plans:
- [x] 31-01-PLAN.md — Backend edges endpoint + StaticFiles mount + GraphStateManager.read_influence_edges + tests
- [x] 31-02-PLAN.md — Frontend Vite scaffold + design tokens + WebSocket composable + App shell empty state
- [x] 31-03-PLAN.md — ForceGraph.vue with D3 force simulation, bracket clustering, real-time signal coloring
- [x] 31-04-PLAN.md — Edge animation + AgentSidebar + human visual verification
**UI hint**: yes

### Phase 32: REST Controls and Simulation Control Bar
**Goal**: Users can start a simulation, inject shocks, and trigger replay from the browser via REST endpoints wired to a control bar UI
**Depends on**: Phase 31
**Requirements**: BE-05, BE-06, BE-07, BE-08, BE-09, BE-10, CTL-01, CTL-02
**Success Criteria** (what must be TRUE):
  1. User can type a seed rumor into a text input and click Start to launch a simulation — the control bar disables the start button while a simulation is active
  2. User can open a shock injection drawer mid-simulation, submit shock text, and see a confirmation — a second concurrent shock request shows an error (HTTP 409 guard)
  3. GET /api/edges/{cycle_id}?round=N returns the INFLUENCED_BY edge list for the requested round
  4. GET /api/replay/cycles returns a list of completed simulation cycles eligible for replay
  5. POST /api/replay/start/{cycle_id} and POST /api/replay/advance endpoints accept requests and return correct responses
**Plans**: TBD
**UI hint**: yes

### Phase 33: Monitoring Panels
**Goal**: Users can monitor bracket signal distributions, read agent rationale, and observe system telemetry in dedicated panels alongside the force graph
**Depends on**: Phase 31
**Requirements**: MON-01, MON-02, MON-03
**Success Criteria** (what must be TRUE):
  1. A bracket summary bar shows per-bracket buy/sell/hold distribution and updates live as WebSocket snapshots arrive
  2. Selecting an agent (via graph click or panel) shows that agent's full reasoning text for the active round, updating on round transitions
  3. A telemetry strip displays current RAM %, active semaphore count, simulation phase label, and round indicator — all updating in real time
**Plans**: TBD
**UI hint**: yes

### Phase 34: Replay Mode Web UI
**Goal**: Users can replay a past simulation cycle in the browser with round-by-round stepping through the same graph and panels used for live simulation
**Depends on**: Phase 32, Phase 33
**Requirements**: CTL-03
**Success Criteria** (what must be TRUE):
  1. User can select a completed cycle from a dropdown, click to enter replay mode, and see the graph populate with that cycle's Round 1 state
  2. User can step through rounds manually (next-round button) or enable auto-advance, with the graph and panels updating to show each round's state
  3. Round progress display shows current round number and total rounds during replay
**Plans**: TBD
**UI hint**: yes

### Phase 35: Agent Interview Panel
**Goal**: Users can conduct post-simulation Q&A conversations with any agent, receiving streamed token responses via WebSocket
**Depends on**: Phase 31
**Requirements**: BE-11, INT-01, INT-02
**Success Criteria** (what must be TRUE):
  1. After simulation completes, clicking an agent in the graph or detail sidebar opens an interview chat panel that streams the LLM response token-by-token
  2. During an active simulation, the interview panel is disabled with an explanatory tooltip indicating interviews are available after simulation completes
  3. Multiple interview turns with the same agent maintain conversation context (multi-turn Q&A with sliding window)
**Plans**: TBD
**UI hint**: yes

### Phase 36: Report Viewer and Final Integration
**Goal**: Users can generate and view the simulation report directly in the browser without leaving the web dashboard
**Depends on**: Phase 35
**Requirements**: RPT-01
**Success Criteria** (what must be TRUE):
  1. User can click a Generate Report button after simulation completes, see a loading indicator, and then view the generated HTML report in a new browser tab served by FastAPI
  2. The report generation button is disabled during active simulation and before any simulation has completed
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1-10 (v1.0) -> 11-15 (v2.0) -> 24-28 (v4.0) -> 29-36 (v5.0)

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
| 24. HTML Report Export | v4.0 | 2/2 | Complete | 2026-04-09 |
| 26. Shock Injection Core | v4.0 | 5/5 | Complete | 2026-04-10 |
| 27. Shock Analysis and Reporting | v4.0 | 3/3 | Complete | 2026-04-11 |
| 28. Simulation Replay | v4.0 | 3/3 | Complete | 2026-04-12 |
| 29. FastAPI Skeleton and Event Loop Foundation | v5.0 | 5/5 | Complete   | 2026-04-13 |
| 30. WebSocket State Stream | v5.0 | 0/2 | Planned | - |
| 31. Vue SPA and Force-Directed Graph | v5.0 | 4/4 | Complete   | 2026-04-14 |
| 32. REST Controls and Simulation Control Bar | v5.0 | 0/? | Not started | - |
| 33. Monitoring Panels | v5.0 | 0/? | Not started | - |
| 34. Replay Mode Web UI | v5.0 | 0/? | Not started | - |
| 35. Agent Interview Panel | v5.0 | 0/? | Not started | - |
| 36. Report Viewer and Final Integration | v5.0 | 0/? | Not started | - |
