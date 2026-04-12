# Project Research Summary

**Project:** AlphaSwarm v5.0 Web UI
**Domain:** Real-time multi-agent simulation dashboard — Vue 3 SPA + FastAPI replacing Textual TUI
**Researched:** 2026-04-12
**Confidence:** HIGH

---

## Executive Summary

AlphaSwarm v5.0 replaces the Textual TUI with a browser-based dashboard that visualizes 100 agents reasoning toward consensus on a live force-directed graph. This is a well-understood class of problem: a single-process asyncio simulation engine bridged to a Vue 3 SPA over WebSocket, serving a single operator on localhost. The stack decision space is narrow and well-researched — all technologies are current stable releases with strong official documentation. Execution risk is not about which libraries to pick. It is about how they connect to the existing engine, and two integration decisions must be made correctly in Phase 1 or everything downstream will fail in difficult-to-debug ways.

The recommended graph approach is D3 `d3-force` + SVG, not Cytoscape.js, not vis.js, not Canvas. At 100 nodes, SVG provides native DOM events, CSS transitions, and stroke-dasharray edge animation with zero custom hit-testing code. Cytoscape's own performance documentation explicitly warns about edge arrow rendering cost and opacity overhead. D3 is used as a pure physics computation engine — it produces `{x, y}` coordinates per tick, and Vue's `<template>` SVG renders them via `:cx="node.x"` bindings. D3 does not touch the DOM. This separation eliminates the classic framework-vs-D3 DOM conflict and is the decisive pattern for the hero feature. Canvas is only necessary above ~1,500 SVG elements; AlphaSwarm is fixed at 100 agents.

The two non-negotiable Phase 1 decisions: (1) Uvicorn must own the asyncio event loop — all `StateStore` locks, `ResourceGovernor` events, and Neo4j driver must be created inside the FastAPI lifespan context manager, not before `uvicorn.run()`. This is the same failure mode as the prior 7-bug governor deadlock. (2) `StateStore.snapshot()` has a destructive side effect that drains up to 5 rationale entries per call, designed for a single TUI consumer. Before Phase 2 WebSocket broadcast is built, `snapshot()` must be refactored to be non-destructive, with a separate `drain_rationales()` method called exactly once per broadcast tick by the `StateRelay`. Every other feature — graph, panels, replay, interview — flows correctly once these two foundations are solid.

---

## Key Findings

### Recommended Stack

The backend adds only two direct Python dependencies: `fastapi>=0.135.0` and `uvicorn[standard]>=0.44.0`. The `textual` dependency is removed in Phase 8. The frontend scaffolds with Vue 3.5.32, Vite 8, TypeScript 5.7, Pinia 3, and vue-router 5. D3 is imported as individual tree-shakeable modules (`d3-force`, `d3-selection`, `d3-scale`, `d3-interpolate`, `d3-force-clustering`) totaling ~30KB gzipped — versus Cytoscape's 300KB monolith. VueUse `@vueuse/core` 14.2 provides the `useWebSocket` composable with built-in auto-reconnect, heartbeat, and reactive connection state.

Version compatibility is tightly constrained: Pinia 3.x requires Vue 3.5+, VueUse 14.x requires Vue 3.5+, Vite 8 requires Node.js >=20.19. All three requirements are satisfied by the Vue 3.5.32 target. Node 18 is dropped by Vite 8 and must not be used on the development machine.

**Core technologies:**
- FastAPI 0.135 + Uvicorn 0.44: REST and WebSocket server, ASGI lifecycle owner — Starlette-native async WebSocket, Pydantic integration matches existing models
- Vue 3.5.32 + Pinia 3 + vue-router 5: SPA framework — Composition API with `<script setup>`, reactive state stores, official Vue ecosystem only
- d3-force + d3-selection + d3-scale + d3-interpolate: Graph physics and color scales — ~30KB tree-shakeable; D3 for math only, Vue owns the SVG DOM
- d3-force-clustering: Bracket group clustering force — pulls agents toward bracket centroid, enabling 10 visual archetype clusters
- @vueuse/core 14.2: WebSocket composable + resize observer — auto-reconnect, heartbeat, reactive status refs; `useWebSocket`, `useResizeObserver`, `useThrottleFn`
- TypeScript 5.7 strict mode: Typed WebSocket message envelopes, graph node/edge interfaces, Pinia store types — matches Python codebase strict typing philosophy

**Explicitly rejected (do not use):**
- Cytoscape.js — 300KB monolith; Canvas-only edge animation is expensive per their own docs; edge arrows and semitransparent edges are specifically flagged as 2x+ rendering cost
- vis.js — auto-clusters at 100+ nodes (unwanted); Canvas-only; no maintained Vue 3 wrapper
- Socket.IO — rooms/namespaces/fallback-polling overkill for single-operator localhost
- Tailwind CSS — PostCSS build pipeline complexity for a single dark-theme dashboard; scoped CSS is correct
- Three.js / 3D force graph — WebGL complexity with no analytical value at 100 nodes; 2D is more readable
- Redis / message broker — in-memory `ConnectionManager` is sufficient; single process, single user
- orjson — saves microseconds on 4KB payloads at 5Hz; stdlib json is correct for MVP
- Canvas rendering for the force graph — SVG is correct at 100 nodes; Canvas becomes necessary only above ~1,500 elements

### Expected Features

Features are organized by the dependency chain from FEATURES.md. The backbone is serial (Phases 1-4); panels and polish can parallelize from Phase 5 onward.

**Must have (table stakes — replaces TUI parity):**
- Live force-directed graph replacing the 10x10 color grid — 100 nodes, HSL signal+confidence coloring, INFLUENCED_BY edges
- WebSocket real-time state stream at 200ms cadence
- Start simulation from browser (REST POST + seed rumor text input)
- Agent click-to-inspect (SVG DOM click event + tooltip/side panel)
- Bracket signal distribution panel (reads from snapshot brackets array)
- Rationale feed panel — rolling window, last 50 entries, append on receive
- Telemetry footer — TPS, elapsed, governor state, memory pressure
- Shock injection during simulation (POST + governor suspend/resume with race guard)
- Simulation replay mode (REST endpoints + StateRelay dual-source switch)
- Agent interview panel (WebSocket session wrapping InterviewEngine, post-simulation only)

**Should have (differentiators beyond TUI):**
- Force-directed INFLUENCED_BY edge visualization — edges animate into position as agents cite each other each round; the TUI never showed edges
- Bracket clustering in graph — forceX/forceY pulls each of 10 archetypes toward a soft cluster; fixed-position grid was TUI's blunt instrument
- Edge animation on new influence — stroke-dasharray SVG transition when a new edge is created
- Smooth agent color transitions between rounds — d3-interpolate between HSL states instead of abrupt color swap
- Round-by-round edge diff in replay — new edges highlighted per round
- Zoom and pan on graph (d3-zoom composable on the SVG element)

**Defer to v2+:**
- Real-time LLM token streaming in interview (complete response only for v5.0 MVP)
- Export graph as image (screenshot suffices for now)
- Mobile responsiveness (desktop-only, 1280px minimum; local tool)
- Dark/light theme toggle (dark only; maintaining two themes doubles CSS work)
- Report viewer in browser (CLI path still works; lowest-priority differentiator)

**Critical graph edge data gap:** `StateSnapshot` contains no `INFLUENCED_BY` edge data — the TUI never rendered edges, so this was never needed in the snapshot contract. Edge data lives only in Neo4j. Do NOT add edges to `StateStore`'s hot-path write contract. Resolution: `GET /api/edges/{cycle_id}?round=N` REST endpoint; Vue watches `snapshot.round_num` and fetches on round change. Edges update once per round, so polling on round transition is efficient.

### Architecture Approach

The architecture is single-process, single-event-loop. Uvicorn owns the loop. The simulation runs as `asyncio.create_task()` from a REST trigger. The `StateRelay` is the sole bridge between `StateStore` and all WebSocket clients: it awaits `StateStore._change_event`, drains rationales exactly once, serializes the full snapshot once, and broadcasts the same bytes string to all connected clients via per-client `asyncio.Queue` writer tasks. REST handles all control actions. WebSocket handles server-to-client state push and the stateful multi-turn interview conversation.

The frontend organization separates concerns cleanly: Pinia stores own application state; composables (`useForceGraph.ts`, `useSimulationSocket.ts`) own framework integration logic; Vue components are thin consumers of store data. D3's `forceSimulation` is stored as a plain `let` variable — never in a Vue `ref()` or `reactive()`. Node arrays use `shallowRef()` to prevent Vue's Proxy from intercepting D3's per-tick `node.x = newX` mutations.

**Major components:**
1. `WebApp` (`src/alphaswarm/web/app.py`) — FastAPI factory with lifespan; creates `AppState`, starts `StateRelay` task, mounts CORS and static files
2. `StateRelay` (`src/alphaswarm/web/state_relay.py`) — sole `StateStore` snapshot consumer; awaits `_change_event`; serialize-once broadcast; dual-source switch for live vs replay
3. `SimulationManager` (`src/alphaswarm/web/simulation_manager.py`) — `asyncio.Lock` singleton guard; wraps `run_simulation()` as background task; enforces one simulation at a time
4. `InterviewRelay` (`src/alphaswarm/web/interview_relay.py`) — wraps `InterviewEngine` in per-client WebSocket session; enforces post-simulation gating via phase check
5. Route modules (`routes/sim.py`, `routes/replay.py`, `routes/report.py`, `routes/cycles.py`) — REST endpoints; `asyncio.Lock` on shock injection endpoint
6. `useForceGraph.ts` composable — D3 `forceSimulation` as pure physics engine; `shallowRef` + `triggerRef` for node array; strict `onBeforeUnmount` cleanup; topology-only reheats
7. Pinia simulation store (`stores/simulation.ts`) — `applySnapshot()` merges WebSocket payload; computed signal distribution and bracket groupings; `selectedAgentId` drives tooltip/interview panel

**Python files that change:**
- `state.py` — add `_change_event: asyncio.Event`; refactor `snapshot()` to non-destructive; add `drain_rationales()` method (~25 lines total)
- `cli.py` — add `web` subcommand routing to uvicorn entrypoint
- `app.py` — new FastAPI factory and lifespan (or major refactor of existing)
- `tui.py` — deleted in Phase 8
- `pyproject.toml` — add fastapi + uvicorn; remove textual; update `[project.scripts]`

### Critical Pitfalls

Research identified 16 pitfalls across critical, moderate, and minor categories. The 5 highest-impact pitfalls that can cause architectural rewrites or simulation corruption:

1. **Event loop conflict — Phase 1** (Pitfall 1): If `uvicorn.run()` and `asyncio.run()` coexist, all asyncio primitives bind to different loops. `ResourceGovernor._resume_event.wait()` hangs forever; `asyncio.Queue` operations silently deadlock. This is the exact failure class of the prior 7-bug governor deadlock. Fix: Uvicorn owns the loop; all objects created inside FastAPI lifespan context manager; simulation launched as `asyncio.create_task()`, not `asyncio.run()`.

2. **StateStore destructive drain breaks broadcast — Phase 1-2** (Pitfall 2): `StateStore.snapshot()` drains up to 5 rationale entries per call (state.py lines 200-204). Any second caller (REST health check, debug endpoint, second WebSocket handler) silently consumes entries. `ReplayStore.snapshot()` is already non-destructive and documents this explicitly — `StateStore` must match. Fix: `drain_rationales()` method called exactly once per broadcast tick by `StateRelay`; `snapshot()` becomes a pure read with no side effects.

3. **Vue Proxy corrupts D3 node mutation — Phase 3** (Pitfall 7): Storing the D3 node array in `ref()` wraps every object in an ES Proxy. D3's per-tick `node.x = newX` triggers Vue setter traps — 6,000+ per second at 100 nodes × 60fps. Frame rate drops to 10-15fps. Fix: `shallowRef()` for node and edge arrays; manual `triggerRef(nodesRef)` once after D3 tick callback; or keep D3 arrays as plain `let` variables entirely outside Vue reactivity.

4. **D3 alpha thrashing on 200ms live updates — Phase 3** (Pitfall 5): Calling `simulation.alpha(1).restart()` on every snapshot resets simulation energy 5 times per second. The graph never reaches equilibrium; all 100 nodes perpetually bounce. The hero feature becomes an unusable animated blur. Fix: separate data updates (signal color, confidence opacity) from layout updates; only reheat on topology changes (new INFLUENCED_BY edges); use `alpha(0.05)` warm restart, never `alpha(1)`; pin nodes after initial layout settles.

5. **Interview LLM contention during simulation — Phase 7** (Pitfall 4): `InterviewEngine.ask()` calls `OllamaClient.chat()`, which queues behind active simulation inference. On M1 Max with `OLLAMA_MAX_LOADED_MODELS=2`, this causes 60+ second interview waits and potential governor CRISIS from unmonitored KV cache growth. The governor's `TokenPool` does not account for interview requests. Fix: gate interviews to `SimulationPhase.COMPLETE` only; return HTTP 409 during active simulation. This preserves the original TUI design contract where the interview screen was inaccessible until simulation completion.

**Additional pitfalls to wire into phases:**
- Per-client `asyncio.Queue` writer task with `asyncio.wait_for` timeout (Pitfall 3, Phase 2): prevents one paused browser tab from blocking the entire broadcast and stalling the simulation
- WebSocket disconnect detection via concurrent reader task + heartbeat (Pitfall 8, Phase 2): Starlette reports `CONNECTED` for dead clients until TCP keepalive expires (2+ minutes on macOS); send-only broadcast never detects disconnects
- Governor suspend/resume race on concurrent shock requests (Pitfall 10, Phase 4): `asyncio.Lock` on the shock endpoint; HTTP 409 on second concurrent request
- D3 simulation memory leak on Vue component unmount (Pitfall 6, Phase 3): `simulation.stop()` + `simulation.on('tick', null)` + `cancelAnimationFrame()` + remove zoom/drag listeners in `onBeforeUnmount()`; HMR makes this immediately visible during development
- Vite WebSocket proxy requires `ws: true` flag (Pitfall 13, Phase 3 dev tooling): without it, WebSocket upgrade handshake silently fails through the Vite dev server proxy
- StaticFiles mount order in production FastAPI (Pitfall 14, Phase 8): mount last after all API routers; `app.mount("/", StaticFiles(...))` catches all routes if registered first

---

## Implications for Roadmap

The feature dependency graph defines a clear linear backbone for Phases 1-4, with parallel work possible across Phases 5-7. The build order below is consistent across all four research files and the key themes identified for this synthesis.

### Phase 1: FastAPI Skeleton + Event Loop Foundation
**Rationale:** The event loop ownership decision and StateStore drain refactor must precede all other work. Two browser-visible features require zero lines of Vue code to validate. Getting this wrong poisons everything downstream silently.
**Delivers:** `WebApp` FastAPI factory, lifespan context manager, `AppState` wired to Uvicorn, `StateStore._change_event` field, `drain_rationales()` method, non-destructive `snapshot()`, `SimulationManager` singleton guard with `asyncio.Lock`, `cli.py web` subcommand, `/api/health` endpoint.
**Addresses:** Architectural foundation for all table-stakes features.
**Avoids:** Pitfall 1 (event loop conflict), Pitfall 2 (destructive drain), Pitfall 11 (double-start corruption), Pitfall 16 (enum serialization: build explicit `serialize_snapshot()` here with `.value` conversion)
**Research flag:** STANDARD PATTERNS — FastAPI lifespan + `asyncio.create_task` are official FastAPI documentation. No phase research needed.

### Phase 2: WebSocket State Stream
**Rationale:** All frontend work requires a working data pipe. The `StateRelay` architecture must be correct from the first commit — retrofitting per-client queues and disconnect detection after the broadcast pattern is established is painful.
**Delivers:** `StateRelay` asyncio task (event-driven, 200ms throttle floor), `ConnectionManager` with per-client `asyncio.Queue(maxsize=10)` writer tasks, heartbeat/reader coroutine per client for disconnect detection, `serialize_snapshot()` (single call, `send_text(bytes)` to all clients), `/ws/state` WebSocket endpoint. Testable via `npx wscat`.
**Uses:** FastAPI native WebSocket, stdlib json (serialize once per tick regardless of client count)
**Avoids:** Pitfall 3 (slow client blocks broadcast), Pitfall 8 (dead client accumulation), Pitfall 9 (per-client serialization cost)
**Research flag:** STANDARD PATTERNS — FastAPI `ConnectionManager` is directly from official FastAPI docs. Per-client queue pattern is well-documented.

### Phase 3: Vue SPA + Force-Directed Graph
**Rationale:** The hero feature. Once data flows from Phase 2, the Vue scaffold and D3 graph can be built. This phase must nail the D3/Vue ownership contract (who touches the DOM, who manages reactivity) from the start. Retrofitting `shallowRef`, cleanup protocol, and alpha management into a working-but-broken graph is expensive.
**Delivers:** Vue 3 + Vite scaffold in `web/`, Pinia simulation store with `applySnapshot()`, `useSimulationSocket.ts` composable routing WebSocket messages to stores, `useForceGraph.ts` composable (D3 physics + `shallowRef` + `onBeforeUnmount` cleanup + warm-restart-only alpha management), `ForceGraph.vue` SVG component with 100 nodes colored by HSL signal/confidence, bracket clustering via `forceX`/`forceY`, zoom/pan via d3-zoom, `AgentTooltip.vue` on SVG click events, `GET /api/edges/{cycle_id}?round=N` REST endpoint, Vue watcher on `snapshot.round_num` triggering edge fetch, Vite config with `ws: true` proxy.
**Addresses:** Table stakes — live agent graph, agent click-to-inspect. Differentiators — INFLUENCED_BY edge visualization, bracket clustering, zoom/pan.
**Avoids:** Pitfall 5 (alpha thrashing), Pitfall 6 (D3 memory leak), Pitfall 7 (Vue Proxy corruption), Pitfall 12 (edge data gap), Pitfall 13 (Vite WebSocket proxy)
**Research flag:** NEEDS ATTENTION — `useForceGraph.ts` is custom code with several non-obvious constraints that interact. Recommend a focused spike: scaffold the composable with shallowRef + cleanup + warm restart before building any panel components on top of it. Validate with real WebSocket data at 200ms cadence before declaring Phase 3 complete.

### Phase 4: REST Controls + Control Bar
**Rationale:** Start-simulation from browser closes the end-to-end loop for MVP. Shock injection requires the race condition guard on governor suspend/resume — this must be in the endpoint from day one, not added after a race is observed.
**Delivers:** `POST /api/sim/start` (launches `SimulationManager.start(rumor)`), `POST /api/sim/shock` (with `asyncio.Lock` guard, HTTP 409 on concurrent request), `ControlBar.vue` (start button, shock text input, phase indicator), frontend button disable state tied to simulation phase from Pinia store.
**Addresses:** Table stakes — start simulation from browser, shock injection.
**Avoids:** Pitfall 10 (governor suspend/resume race), Pitfall 11 (double-start, already guarded in Phase 1's SimulationManager)
**Research flag:** STANDARD PATTERNS — REST + asyncio.Lock + HTTP 409 are standard patterns. No research needed.

### Phase 5: Panels + Visual Polish
**Rationale:** TUI parity features that require the graph and data pipe but not each other. All read from Pinia store state already populated by Phases 2-3. Can be developed in parallel within the phase.
**Delivers:** `BracketPanel.vue` (signal distribution per archetype), `RationalePanel.vue` (rolling window, last 50 entries, append-on-receive), `TelemetryFooter.vue` (TPS, elapsed, governor state + memory % from snapshot), edge animation on new INFLUENCED_BY (stroke-dasharray SVG transition triggered by edge fetch), smooth agent node color transitions between rounds (d3-interpolate between HSL states on round change), agent search/filter by bracket or ID in Pinia store with graph highlight.
**Addresses:** Table stakes — bracket panel, rationale feed, telemetry footer. Differentiators — edge animation, smooth color transitions, agent filter.
**Research flag:** STANDARD PATTERNS — Pinia computed state and Vue component composition. d3-interpolate color transitions are well-documented.

### Phase 6: Replay Mode
**Rationale:** Depends on the existing `ReplayStore` (already built, non-destructive snapshot semantics) and the graph from Phase 3. `StateRelay` dual-source mode is a small addition to Phase 2's relay component. No new architectural concepts — replay follows the same WebSocket broadcast path, just with a different store as source.
**Delivers:** `POST /api/replay/start`, `POST /api/replay/advance`, `POST /api/replay/stop`, `GET /api/cycles`, `StateRelay` dual-source mode (live vs replay switch), `ReplayControls.vue` (cycle picker, round advance, auto-advance toggle), round-by-round edge diff highlighting (compare edge sets between rounds, color new edges).
**Addresses:** Table stakes — simulation replay. Differentiator — round edge diff.
**Research flag:** STANDARD PATTERNS — `ReplayStore` semantics are already defined and tested. StateRelay dual-source is a straightforward conditional on `_active_store`.

### Phase 7: Agent Interview Panel
**Rationale:** Post-simulation only. Adding this late means the gating logic (phase check → HTTP 409 during active simulation) is natural rather than bolted on. Interview requires a completed simulation for agent context anyway, so deferring preserves the original TUI design contract with zero special handling.
**Delivers:** `/ws/interview/{agent_id}` WebSocket endpoint, `InterviewRelay` session manager (load context from Neo4j, create `InterviewEngine`, deliver context message on connect, relay Q&A turns), `InterviewPanel.vue` (slide-out, multi-turn Q&A, loading state for 5-60s LLM response), HTTP 409 guard during active simulation, `try/finally` cleanup of `InterviewEngine` on WebSocket disconnect.
**Addresses:** Table stakes — agent interview.
**Avoids:** Pitfall 4 (LLM contention during simulation), Pitfall 15 (engine memory leak on disconnect)
**Research flag:** NEEDS ATTENTION — Interview gating strategy should be confirmed before coding: post-simulation-only (simplest, matches TUI contract) vs semaphore-during-simulation (adds complexity, governor awareness gap). Recommendation from research is post-simulation-only. Confirm with project owner.

### Phase 8: Report Viewer + TUI Removal
**Rationale:** Least-risk phase. Report viewer is read-only. TUI removal is file deletion. StaticFiles mount order must be correct in production — register after all API routers. TUI must not be removed until all table-stakes features are smoke-tested in the web UI.
**Delivers:** `GET /api/report/{cycle_id}` (generate via `ReportEngine` or return cached), `ReportViewer.vue` (renders report markdown in browser), `StaticFiles` mount as final registration in `app.py`, `tui.py` deleted, `textual` removed from `pyproject.toml`, `pyproject.toml` `[project.scripts]` updated.
**Addresses:** Differentiator — report viewer in browser. Milestone complete — TUI fully removed.
**Avoids:** Pitfall 14 (StaticFiles mount order catches `/api/*` routes if registered first)
**Research flag:** STANDARD PATTERNS — StaticFiles serving, markdown rendering, and dependency removal are trivial operations.

### Phase Ordering Rationale

- Phases 1-2 are the mandatory data backbone. No frontend work is valid until Phase 2 produces a wscat-testable WebSocket broadcast. These two phases exist to eliminate the two founding risks (event loop, rationale drain) before any UI code is written against them.
- Phase 3 is high creative risk. The D3/Vue integration contract has multiple non-obvious traps (shallowRef, onBeforeUnmount, alpha management) that interact. Getting it right the first time is cheaper than retrofitting. Treat Phase 3 as the risk-reduction phase for the entire frontend.
- Phases 4-5 are independent of each other once Phase 3 is stable. They can be interleaved or assigned to parallel workstreams.
- Phases 6-7 are independent of each other. Replay is lower risk than Interview; either order works. Both depend on Phase 3 (graph) and Phase 5 (panels) being stable, but neither requires the other.
- Phase 8 is always last. TUI removal before web UI verification would leave the project without a working UI.

### Research Flags Summary

| Phase | Research Needed | Reason |
|-------|-----------------|--------|
| Phase 3 | Yes — spike recommended | `useForceGraph.ts` composable has multiple interacting non-obvious constraints; validate D3/Vue ownership split with real data before building panels on top |
| Phase 7 | Yes — decision required | Interview gating: post-simulation-only vs semaphore-during-simulation; confirm with project owner before coding the endpoint |
| Phase 1 | No | FastAPI lifespan + asyncio.create_task are official-documentation patterns |
| Phase 2 | No | ConnectionManager + per-client queue are FastAPI official patterns |
| Phase 4 | No | REST + asyncio.Lock + HTTP 409 are standard; governor integration points are known |
| Phase 5 | No | Pinia + Vue SFC composition; d3-interpolate color transitions are well-documented |
| Phase 6 | No | ReplayStore is pre-built; StateRelay dual-source is well-defined; no new concepts |
| Phase 8 | No | File deletion + static file serving + pyproject edit |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against official npm/PyPI registries as of April 2026. Version compatibility matrix cross-checked. D3 SVG vs Canvas decision grounded in official Cytoscape performance docs and SVG performance research. |
| Features | HIGH | Feature list derived from direct TUI parity analysis. Edge data gap is a known and resolved gap (REST endpoint). Anti-features explicitly excluded with rationale. |
| Architecture | HIGH | Integration points map precisely to existing codebase (state.py lines 200-204 for drain, governor.py for _resume_event, simulation.py for run_simulation signature). Patterns are from FastAPI official docs. Single-process constraint is proven by TUI architecture. |
| Pitfalls | HIGH | Critical pitfalls 1-2 are grounded in the existing codebase (governor deadlock analysis in MEMORY.md, StateStore drain in state.py). D3 pitfalls 5-7 are documented against D3 source behavior with observable warning signs. Starlette disconnect pitfall confirmed against Starlette Issue #1811. |

**Overall confidence: HIGH**

### Gaps to Address

- **SVG vs Canvas rendering discrepancy:** ARCHITECTURE.md contains a section recommending Canvas and listing SVG as "Anti-Pattern 5." STACK.md and PITFALLS.md both explicitly argue SVG is the correct choice at 100 nodes and mark it "acceptable permanently" in the technical debt table. The synthesis verdict is **SVG** — the Canvas recommendation in ARCHITECTURE.md is an artifact of an earlier research draft. Confirm SVG choice with project owner before Phase 3 work begins; a one-line correction in ARCHITECTURE.md would prevent future confusion.

- **d3-force-clustering third-party status:** The `d3-force-clustering` package (vasturiano) is flagged MEDIUM confidence in STACK.md. If it proves incompatible or unmaintained, bracket clustering falls back to vanilla `forceX`/`forceY` targeting bracket centroid coordinates — a straightforward ~10-line alternative requiring no plugin. Not a blocking risk.

- **orjson for serialize-once path:** PITFALLS.md (Pitfall 9) recommends orjson for the serialize-once broadcast. STACK.md recommends stdlib json for MVP. Resolution: start with stdlib json and `send_text(pre_serialized_string)` (serialize once, regardless of client count). Add orjson only if CPU profiling identifies serialization as a measurable bottleneck. Not a blocking gap.

- **Interview streaming (future):** MVP defers LLM token streaming. If added later, `InterviewRelay` needs Ollama's `stream=True` path. The WebSocket architecture supports it; it is not designed out. Plan a separate research spike when the feature is scheduled.

- **Shock injection write path verification:** FEATURES.md and ARCHITECTURE.md describe `write_shock_event()` in `GraphStateManager`, but the exact method signature should be verified against `graph.py` before Phase 4 implementation. Listed as a low-risk gap — most likely present, but confirm.

---

## Sources

### Primary (HIGH confidence)
- FastAPI official docs (fastapi.tiangolo.com) — WebSocket ConnectionManager, lifespan context manager, StaticFiles mount order, Depends() DI pattern
- D3.js official docs (d3js.org/d3-force) — Force simulation API, alpha/decay, tick events, restart semantics, `forceX`/`forceY`
- Cytoscape.js performance documentation — Edge rendering cost warnings, edge arrow overhead, semitransparent edge cost (basis for rejection)
- Pinia official docs (pinia.vuejs.org) — defineStore, Composition API pattern, Vue 3.5+ requirement confirmed
- VueUse docs (vueuse.org/core/usewebsocket) — useWebSocket auto-reconnect, heartbeat interval, reactive status/data refs
- PyPI registries: fastapi 0.135.3, uvicorn 0.44.0 (April 2026 current)
- npm registries: vue 3.5.32, pinia 3.0.4, vue-router 5.0.4, @vueuse/core 14.2.1 (current as of research date)
- Existing AlphaSwarm codebase: `state.py` lines 155-162 (rationale queue drop logic), lines 200-204 (destructive drain), lines 259-280 (ReplayStore non-destructive snapshot); `governor.py` (_resume_event, _adjustment_lock, TokenPool); `simulation.py` (run_simulation signature and parameters)
- AlphaSwarm MEMORY.md governor bug analysis — confirms asyncio event loop split as root cause of the 7-bug governor deadlock; validates Pitfall 1 as the highest-priority risk

### Secondary (MEDIUM confidence)
- d3-force-clustering (github.com/vasturiano) — third-party D3 force plugin; active maintenance but not part of official D3 org
- Starlette Issue #1811 — `websocket.client_state` reports CONNECTED after client is gone in send-only pattern
- FastAPI Discussion #9031 — confirmed Starlette disconnect detection gap
- Visual Cinnamon (visualcinnamon.com) — stroke-dasharray + dashoffset edge animation technique (established SVG pattern)
- DEV Community (dev.to) — Vue 3 + D3 Composition API integration patterns; multiple independent sources confirming shallowRef recommendation
- SSE vs WebSocket 2026 comparison — bidirectional requirement justifies WebSocket over SSE for this use case

### Tertiary (LOW confidence)
- Vite 8.0 minor version — major release confirmed for 2026; exact minor version unverified at research time

---

*Research completed: 2026-04-12*
*Ready for roadmap: yes*
