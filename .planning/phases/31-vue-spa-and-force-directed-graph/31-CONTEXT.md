# Phase 31: Vue SPA and Force-Directed Graph - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the Vue 3 SPA entry point and the force-directed agent graph — the hero feature of v5.0. FastAPI serves the production build; a Vite dev server proxies API/WS in development. D3 drives the force simulation (physics only); Vue owns the SVG DOM. 100 agent nodes render in bracket-clustered groups with real-time signal coloring; INFLUENCED_BY edges animate in on round transitions fetched from a new `/api/edges` endpoint built in this phase. A fixed right panel displays agent detail on node click.

Phase 32 (REST Controls), Phase 33 (Monitoring Panels), Phase 34 (Replay), Phase 35 (Interviews), and Phase 36 (Report Viewer) are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Vue Build and Serving Strategy
- **D-01:** Vite dev server runs on `:5173` with HMR. `vite.config.ts` proxies `/api` and `/ws` to FastAPI on `:8000`. Two processes in dev: `npm run dev` + `uvicorn`.
- **D-02:** Production: `npm run build` outputs to `dist/`. FastAPI mounts `dist/` as `StaticFiles` at `/`. Single server, single port in production.
- **D-03:** The `frontend/` directory lives at the project root (alongside `src/`), not inside `src/alphaswarm/web/`. FastAPI serves its `dist/` output.

### Force Graph Rendering Architecture
- **D-04:** SVG rendering (not Canvas) — locked from prior discussion. Native DOM events, CSS transitions, zero custom hit-testing code.
- **D-05:** D3 is the physics engine only. Vue owns the SVG DOM via `shallowRef` + `triggerRef`. The D3 node array is never wrapped in a Vue Proxy.
- **D-06:** Layout reheats only on topology changes (new nodes or new INFLUENCED_BY edges), not on every 200ms WebSocket snapshot. State updates (signal color, rationale text) are applied as DOM attribute mutations without touching the simulation.

### Bracket Clustering
- **D-07:** 10 bracket archetype centroids are arranged in a circle at a fixed radius from the graph center. `d3.forceX` and `d3.forceY` pull each node toward its bracket's centroid with a moderate strength (α ~0.3). Clusters emerge visually without hard constraints.
- **D-08:** Bracket centroids are computed once at initialization from the bracket list and remain fixed regardless of simulation state. No centroid re-computation on snapshot updates.

### Node Visual Encoding
- **D-09:** Signal color: green (`#22c55e`) = BUY, red (`#ef4444`) = SELL, gray (`#6b7280`) = HOLD. Applied as SVG `fill` attribute updates — no CSS class toggling.
- **D-10:** Node size reflects bracket archetype via a fixed radius per bracket index (r = 5px base + 1px per bracket tier, range 5–14px). Claude has discretion on exact radius values.

### INFLUENCED_BY Edge Endpoint (built in Phase 31)
- **D-11:** New `routes/edges.py` implements `GET /api/edges/{cycle_id}?round=N`. Queries Neo4j for `INFLUENCED_BY` relationships created in that cycle/round. Registered in `create_app()` with `/api` prefix.
- **D-12:** Phase 32 SC-3 verifies this endpoint but does not re-implement it. The endpoint is built here because the Vue graph and the edge data are developed together.
- **D-13:** Response schema: `{"edges": [{"source_id": str, "target_id": str, "weight": float}]}`. Simple flat list — no pagination needed at 100 agents.

### Edge Animation
- **D-14:** INFLUENCED_BY edges fade in (opacity 0 → 1) over ~600ms CSS transition when a new round is detected via the WebSocket snapshot (`round_num` change). Existing edges from prior rounds persist (no removal until cycle resets).
- **D-15:** Edge fetch is triggered by `round_num` change in the WebSocket snapshot, not by a timer or polling.

### Agent Detail Sidebar
- **D-16:** Fixed right panel (~280px wide). Slides in from the right when a node is clicked; the graph container shrinks to fill the remaining width. Closes via an X button or clicking empty graph space.
- **D-17:** Sidebar displays: agent name, bracket archetype label, current signal (color-coded chip), and current-round rationale text. Content updates in real time as WebSocket snapshots arrive for the selected agent.
- **D-18:** Only one agent sidebar open at a time. Clicking a different node switches to that agent.

### Claude's Discretion
- Exact D3 force strength parameters (link distance, charge strength, centering strength, collision radius)
- Vue component decomposition (`App.vue`, `ForceGraph.vue`, `AgentSidebar.vue`, etc.)
- CSS animation easing for sidebar slide-in
- Exact bracket radius values within the 5–14px range
- Whether `vite.config.ts` uses a single proxy entry or per-path entries

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/ROADMAP.md` §"Phase 31: Vue SPA and Force-Directed Graph" — goal, success criteria SC-1 through SC-5

### Existing Phase 29–30 infrastructure (must read before implementing)
- `src/alphaswarm/web/app.py` — `create_app()` and `lifespan()`: Phase 31 adds `StaticFiles` mount and `edges_router` registration here
- `src/alphaswarm/web/routes/health.py` — router file pattern for new `routes/edges.py`
- `src/alphaswarm/web/broadcaster.py` — `snapshot_to_json()` pipeline: defines the WebSocket payload schema Vue consumes
- `src/alphaswarm/state.py` — `StateSnapshot`, `AgentState`, `BracketSummary` dataclasses: defines the JSON keys the Vue frontend reads

### Neo4j query reference (for edges endpoint)
- `src/alphaswarm/graph.py` (or `graph_manager.py`) — existing Neo4j query patterns for INFLUENCED_BY relationships; edges endpoint reuses these patterns

### Project config
- `pyproject.toml` — no new Python deps expected; `frontend/package.json` will be new
- `src/alphaswarm/web/__init__.py` — exports surface; check before adding new modules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ConnectionManager` + `broadcaster.py` — WebSocket stream already operational; Vue just connects to `ws://localhost:8000/ws/state`
- `StateStore.snapshot()` + `drain_rationales()` — already serialized as JSON by broadcaster; frontend parses `agent_states[i].signal`, `agent_states[i].rationale`, `bracket_summaries`
- `routes/simulation.py` — Pydantic request/response model pattern for the edges endpoint
- `_make_test_app()` in `tests/test_web.py` — extend to include edges router for tests

### Established Patterns
- **Router-per-domain (Phase 29 D-02):** New `routes/edges.py` with `APIRouter()`, registered via `app.include_router(edges_router, prefix="/api")`
- **Lifespan owns stateful objects:** Any Neo4j session used by the edges endpoint goes through `request.app.state.app_state.graph_manager`
- **structlog component naming:** `structlog.get_logger(component="web.edges")`
- **D3 + Vue pattern:** `shallowRef(nodes)` + `triggerRef(nodesRef)` after D3 mutates positions — do NOT use `ref()` or `reactive()` on D3 node arrays

### Integration Points
- `web/app.py` `create_app()` — add `app.mount("/", StaticFiles(directory="frontend/dist", html=True))` after all API/WS routes; add edges router
- `frontend/vite.config.ts` — proxy `/api` and `/ws` to `http://localhost:8000`
- `tests/test_web.py` — add edges endpoint tests alongside existing web tests

</code_context>

<specifics>
## Specific Ideas

- Bracket centroids arranged in a circle (not a grid) — matches the "mirofish" mental model from v5.0 direction discussion
- Edge fade-in (not draw/stroke-dasharray) — simpler, performant at 100 nodes, and visually sufficient
- The sidebar shrinks the graph container width rather than overlaying it — avoids obscuring nodes during inspection

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 31-vue-spa-and-force-directed-graph*
*Context gathered: 2026-04-13*
