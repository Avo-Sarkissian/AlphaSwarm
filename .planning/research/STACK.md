# Stack Research: AlphaSwarm v5.0 Web UI

**Domain:** Real-time multi-agent simulation dashboard (100 agents, force-directed graph, WebSocket state streaming)
**Researched:** 2026-04-12
**Confidence:** HIGH (core libs verified via official docs and npm/PyPI; versions cross-referenced)

## Scope

This document covers ONLY the stack additions needed for the v5.0 Web UI milestone. The validated existing stack (Python 3.11+, asyncio, ollama-python >=0.6.1, neo4j >=5.28, pydantic, pydantic-settings, structlog, psutil, httpx, backoff, Jinja2, aiofiles, pygal) is NOT re-evaluated.

---

## Critical Decision: Force-Directed Graph Library

**Recommendation: D3.js (`d3-force` + `d3-selection` + SVG rendering) -- not Cytoscape.js, not vis.js.**

### Why D3 Wins for This Use Case

| Criterion | D3.js (d3-force) | Cytoscape.js | vis.js (vis-network) |
|-----------|-------------------|--------------|----------------------|
| **100-node performance** | Trivial (designed for 1000+) | Good but overhead from abstraction layer | Good, but auto-clusters at 100+ nodes (unwanted behavior) |
| **Edge animation** | Full SVG control: stroke-dasharray animation, CSS transitions, particle effects via requestAnimationFrame | Limited: line-dash-offset hack via `ele.animation()`. Their own perf docs warn "edge arrows are expensive to render" and "semitransparent edges with arrows are more than twice as slow" | Canvas-only, no per-edge SVG animation |
| **Bracket clustering** | `forceX`/`forceY` positioning forces per bracket + `d3-force-clustering` plugin = exact control over 10 bracket groups | Possible but requires manual layout override | Built-in clustering designed for node simplification, not visual grouping |
| **Click-to-inspect** | Native SVG DOM events (`click`, `mouseover`) -- standard browser behavior | Custom event system (extra abstraction layer) | Custom event system |
| **Live edge creation** | Add link to `simulation.force("link").links()`, call `simulation.alpha(0.3).restart()` -- edges animate into position naturally | `cy.add()` then re-run layout -- more disruptive to existing positions | Re-stabilization required |
| **Color control** | Direct HSL manipulation on SVG fill attributes (exact match for existing `compute_cell_color` HSL logic in tui.py line 47) | Style sheets with limited color functions | Options-based theming, less granular |
| **Vue 3 integration** | Use D3 for math/forces only, Vue owns the DOM via `<template>` SVG -- clean separation of concerns | Requires wrapper lib (`vue3-cytoscape`, 12 GitHub stars, uncertain maintenance) | No maintained Vue 3 wrapper exists |
| **Bundle size** | `d3-force` + `d3-selection` + `d3-scale`: ~30KB gzipped (tree-shakeable, import only what you use) | ~300KB minified (monolithic, no tree-shaking) | ~200KB minified |

### The Decisive Factor: Edge Animation

The "mirofish canvas" hero feature requires **live edge animation** as INFLUENCED_BY relationships form during inference. This means:

- Edges must appear with a drawing/growing animation (SVG stroke-dasharray + dashoffset transition)
- Edge color and weight must update in real-time based on influence strength
- Edges need directional flow indicators (animated dashes or arrowhead markers)

D3's SVG approach gives **pixel-level control** over edge rendering via standard CSS/SVG animation techniques. Cytoscape.js uses Canvas rendering internally, which means edge animation requires their custom `ele.animation()` API -- and their own performance documentation explicitly warns about the rendering cost of edge arrows and transparency.

With only 100 nodes and ~200-400 edges, SVG rendering is more than adequate. SVG performance concerns only emerge at 1000+ DOM elements. At our scale, the visual expressiveness of SVG is the correct tradeoff over Canvas.

### SVG vs Canvas at 100 Nodes

The previous version of this document recommended Canvas rendering. After deeper analysis, **SVG is the better choice at 100 nodes** because:

1. **Edge animation**: SVG stroke-dasharray + CSS transitions provide smooth edge drawing effects with zero custom render loop code. Canvas requires manual animation frame management.
2. **Click interaction**: SVG elements are standard DOM nodes with native event handlers. Canvas requires hit-testing math (point-in-rectangle/circle calculations).
3. **CSS styling**: SVG elements accept CSS properties directly, including transitions and hover states. Canvas styling must be imperative.
4. **Browser DevTools**: SVG elements appear in the DOM inspector. Canvas is a black box.
5. **100 nodes + 400 edges = 500 SVG elements**: Well within browser SVG performance budget. Frame drops only occur at 2000+ elements with frequent full redraws.

Canvas becomes necessary at 1000+ nodes. We have 100.

### Integration Pattern: D3 for Math, Vue for DOM

Do NOT let D3 touch the DOM. Use D3's force simulation as a pure computation engine:

```
D3 forceSimulation  -->  computes { x, y } per node per tick
Vue reactive refs   -->  bind x, y to <circle>, <line> in <svg> template
```

This avoids the classic D3-in-a-framework trap where D3's `enter/exit/update` selection pattern fights the framework's reactivity system. Vue owns the DOM; D3 owns the physics.

---

## Recommended Stack

### Backend (Python -- NEW additions)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| FastAPI | >=0.135.0 | REST + WebSocket API server | Already decided per PROJECT.md. Built on Starlette with native async WebSocket support via `@app.websocket()`. Pydantic integration matches existing models. Latest: 0.135.3 (April 2026) |
| uvicorn | >=0.44.0 | ASGI server | Production-grade, required by FastAPI. Single-worker mode shares asyncio event loop with simulation -- critical for StateStore access without IPC. Latest: 0.44.0 (April 2026) |
| websockets | >=15.0 | WebSocket protocol implementation | Required by Starlette for WebSocket transport. Installed automatically via `uvicorn[standard]` |

### Frontend Core

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Vue | ^3.5.32 | UI framework | Already decided. Composition API + `<script setup>` + reactivity system for real-time state binding. v3.5 is current stable (v3.6 targeted mid-2026). Latest: 3.5.32 (April 2026) |
| Vite | ^8.0.0 | Build tool / dev server | Official Vue tooling. Sub-50ms HMR, ESM-native, proxy config for FastAPI backend. Requires Node.js >=20.19. Latest major: 8.0 (2026) |
| vue-router | ^5.0.4 | Client-side routing | Official router for Vue 3. Routes: `/simulation`, `/replay/:id`, `/report/:id`. Latest: 5.0.4 (March 2026) |
| Pinia | ^3.0.4 | State management | Official Vue state library, replaces Vuex. Composition API-native, TypeScript-first. Stores: simulation state, WebSocket connection, agent selection. Requires Vue 3.5+. Latest: 3.0.4 |
| TypeScript | ^5.7.0 | Type safety | Strict mode. Type WebSocket message protocol, agent state interfaces, graph node/edge types. Matches Python codebase's strict typing philosophy |

### Frontend Visualization (D3 modules -- tree-shakeable)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| d3-force | ^3.0.0 | Force simulation engine | Physics computation for 100-node layout. Velocity Verlet integrator, tick events, alpha/decay control. 10 bracket groups via `forceX`/`forceY`. ~8KB gzipped |
| d3-selection | ^3.0.0 | DOM utility (minimal use) | Only for `d3.select()` to read SVG bounding box dimensions in the graph composable. Vue handles all actual DOM rendering |
| d3-scale | ^4.0.0 | Color and size scales | Map confidence (0.0-1.0) to HSL lightness, map influence weight to edge thickness/opacity. Matches existing `compute_cell_color` HSL logic |
| d3-interpolate | ^3.0.0 | Smooth color transitions | Interpolate between color states during round transitions (pending grey -> BUY green / SELL red). Smooth visual transitions instead of abrupt color pops |
| d3-force-clustering | ^1.0.0 | Bracket group clustering | Custom clustering force pulling nodes toward bracket centroid. 10 archetypes = 10 visual clusters. Maintained by vasturiano (recommended replacement for deprecated d3-force-cluster-3d) |

### Frontend Utilities

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @vueuse/core | ^14.2.0 | Composition utilities | `useWebSocket` (auto-reconnect, heartbeat, reactive status/data refs), `useResizeObserver` (responsive graph container), `useThrottleFn` (throttle snapshot processing). Requires Vue >=3.5. Latest: 14.2.1 (February 2026) |

---

## WebSocket Architecture: Hybrid WebSocket + REST

### Why WebSocket Over SSE

SSE (Server-Sent Events) is simpler for pure server-to-client streaming and reportedly scales better for broadcast-only scenarios (one 2026 source reports SSE handling 100K connections where WebSocket choked at 12K). However, AlphaSwarm needs **bidirectional communication**:

- **Server -> Client:** State snapshots (~5/sec), individual agent decisions, edge creation events, governor metrics, phase transitions, interview response tokens
- **Client -> Server:** Shock injection text, interview questions, replay commands (play/pause/step), simulation start/stop

SSE + separate REST POST would work but doubles the transport surface area (two connection types, two reconnection strategies, two error handling paths). WebSocket handles both directions cleanly on a single connection.

**Verdict:** WebSocket for the main simulation channel. REST for stateless read operations (fetch report HTML, list past simulation cycles, load replay data from Neo4j).

### Connection Manager Pattern

FastAPI's official docs recommend a `ConnectionManager` class with an `active_connections: list[WebSocket]` for multi-client broadcast. For AlphaSwarm (single-operator, localhost-only, no load balancer, no multi-worker), this in-memory pattern is sufficient. No Redis pub/sub, no `encode/broadcaster`, no external message broker needed.

The existing `StateStore.snapshot()` maps directly:

```
Current TUI:  StateStore.snapshot() --> Textual set_interval(1/5) reads at 200ms
New Web UI:   StateStore.snapshot() --> asyncio task broadcasts JSON at 200ms via WebSocket
```

### Message Protocol: JSON Text Frames

Do NOT use msgpack, protobuf, or binary serialization.

- 100 agents x ~40 bytes each = ~4KB per snapshot. JSON overhead is negligible at this size
- Browser DevTools can inspect JSON WebSocket frames directly -- critical during development
- No serialization library dependency on either end (stdlib `json` on Python, `JSON.parse` in browser)
- msgpack's ~25% size savings is meaningless at 4KB over localhost loopback

Do NOT add `orjson`. At 4KB payloads broadcast 5 times per second, stdlib `json.dumps()` takes <0.1ms. orjson's 5-10x speedup saves microseconds that are invisible next to the 200ms polling interval. One fewer dependency.

### Typed Message Envelopes

```typescript
// Server -> Client
type ServerMessage =
  | { type: "snapshot"; data: StateSnapshot }
  | { type: "edge_created"; data: { source: string; target: string; weight: number } }
  | { type: "agent_decision"; data: { agent_id: string; signal: string; confidence: number } }
  | { type: "phase_change"; data: { phase: string; round: number } }
  | { type: "governor"; data: GovernorMetrics }
  | { type: "interview_token"; data: { agent_id: string; token: string; done: boolean } }

// Client -> Server
type ClientMessage =
  | { type: "inject_shock"; data: { text: string } }
  | { type: "interview"; data: { agent_id: string; question: string } }
  | { type: "replay_command"; data: { action: "play" | "pause" | "step"; cycle_id?: string } }
  | { type: "start_simulation"; data: { seed_rumor: string } }
```

### Granular Events + Polling Snapshots (Hybrid)

The current TUI polls `snapshot()` every 200ms for bulk state. For the web UI, supplement polling with **push events** for things that animate better as discrete occurrences:

- **Polling (200ms):** Agent grid colors, bracket summaries, governor telemetry -- same as TUI
- **Push events:** Edge creation (animate the edge drawing in), individual agent decisions (pop the node color), phase transitions (trigger round transition animation)

This requires adding lightweight event hooks in `simulation.py` that push to the WebSocket manager alongside the existing StateStore writes.

---

## Installation

### Backend (Python)

```bash
# Add to existing pyproject.toml dependencies
uv add fastapi "uvicorn[standard]"

# This pulls in: fastapi, starlette, uvicorn, websockets, httptools, uvloop
# Total new direct deps: 2 (fastapi, uvicorn)

# REMOVE after web UI is feature-complete:
uv remove textual
```

Updated `pyproject.toml` dependencies:

```toml
dependencies = [
    "pydantic>=2.12.5",
    "pydantic-settings>=2.13.1",
    "structlog>=25.5.0",
    "psutil>=7.2.2",
    "ollama>=0.6.1",
    "backoff>=2.2.1",
    "neo4j>=5.28,<6.0",
    "jinja2>=3.1.6",
    "aiofiles>=25.1.0",
    # v5.0: web UI
    "fastapi>=0.135.0",
    "uvicorn[standard]>=0.44.0",
    # REMOVED: "textual>=8.1.1"
]
```

### Frontend (new directory: `frontend/`)

```bash
# Scaffold Vue 3 + TypeScript + Pinia + Router + ESLint (from repo root)
npm create vue@latest frontend -- --typescript --pinia --router --eslint

cd frontend

# D3 modules (tree-shakeable -- import only what you use)
npm install d3-force d3-selection d3-scale d3-interpolate d3-force-clustering

# D3 type definitions
npm install -D @types/d3-force @types/d3-selection @types/d3-scale @types/d3-interpolate

# VueUse for useWebSocket, useResizeObserver, useThrottleFn
npm install @vueuse/core
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative Instead |
|-------------|-------------|----------------------------------|
| D3 `d3-force` + SVG | Cytoscape.js (Canvas) | If you need 5000+ nodes where Canvas outperforms SVG. Cytoscape's edge animation is also limited and expensive per their own docs. Not relevant at 100 nodes |
| D3 `d3-force` + SVG | vis.js (vis-network) | If you want a plug-and-play network viz with zero customization. Wrong when edge animation, bracket clustering, and HSL color control are hero features |
| D3 `d3-force` + SVG | Sigma.js + Graphology | If you need WebGL rendering for 10,000+ nodes. Massive overkill at 100 nodes, and WebGL makes click interaction harder |
| D3 `d3-force` + SVG | force-graph (vasturiano) | Higher-level Canvas wrapper around d3-force. Convenient but less control over bracket clustering layout and edge animation. Revisit only if the custom composable gets unmanageably complex |
| SVG rendering | Canvas rendering | If element count exceeds ~1500 with frequent full redraws. At 100 nodes + 400 edges = 500 elements, SVG is comfortably performant and gives native DOM events + CSS transitions |
| Pinia ^3.0.4 | Vuex 4 | Never. Vuex is in maintenance mode since 2022. Pinia is the official Vue 3 successor |
| VueUse `useWebSocket` | Native `WebSocket` API | If you want zero extra dependencies. But you lose auto-reconnect, heartbeat, and reactive refs. The ~3KB cost is worth the robustness |
| JSON text frames | msgpack binary frames | If payloads exceed ~50KB per message. At 4KB over localhost, JSON debugging transparency wins |
| WebSocket | SSE (Server-Sent Events) | If the dashboard were purely read-only with no shock injection, interviews, or replay controls |
| stdlib `json` | orjson | If serialization is a measurable bottleneck. At 4KB x 5/sec, stdlib json takes <0.1ms per call. orjson saves microseconds for an extra dependency |
| FastAPI native WebSocket | Socket.IO (python-socketio) | If you need rooms, namespaces, automatic long-polling fallback. Single-operator localhost needs none of this |
| uvicorn single-worker | uvicorn multi-worker / gunicorn | Multi-worker runs separate processes with isolated memory. StateStore and ResourceGovernor cannot be shared across processes without IPC. Single-user local tool does not need multi-worker |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Plotly.js** | 15MB+ bundle. Already rejected in v4.0. Chart-oriented, not network-topology-oriented | D3 for graph viz. Keep pygal for report SVG charts (already working) |
| **Socket.IO** | Abstraction layer with rooms/namespaces/fallback-to-polling. Single-operator localhost needs none of this. Adds `python-socketio` + `socket.io-client` deps | Native FastAPI WebSocket via Starlette |
| **Vuex** | Maintenance mode since 2022. Pinia is the official replacement | Pinia ^3.0.4 |
| **Chart.js** (for agent graph) | Renders bar/line/pie charts, not network topology graphs | D3 `d3-force` |
| **Three.js / 3D force graph** | 3D adds visual complexity without value for a 100-node influence topology. 2D is clearer and matches the 10x10 grid mental model | 2D D3 force layout with SVG |
| **Tailwind CSS** | PostCSS build pipeline complexity for a single-page dashboard. "Clean minimalist aesthetic" is better served by scoped CSS | `<style scoped>` in Vue SFCs + CSS custom properties for dark theme |
| **Nuxt** | SSR/SSG framework for multi-page SEO apps. This is a single-page localhost dashboard | Plain Vue 3 + Vite + vue-router |
| **Axios** | `fetch()` is built into every browser with TypeScript support. Axios adds 13KB for no benefit in localhost-only app | Native `fetch()` for REST calls |
| **vue-d3-network / vue-force-graph** | Thin wrappers with <100 GitHub stars, unmaintained, fight Vue reactivity by letting D3 own DOM | Custom `useForceGraph` composable (~150 LOC): D3 for math, Vue `<template>` for SVG |
| **vue3-cytoscape** | 12 GitHub stars, uncertain maintenance, extra abstraction layer | Direct D3 integration if using D3, or direct Cytoscape API (but D3 is recommended) |
| **Redis / message broker** | Single-operator, single-process, localhost. In-memory ConnectionManager is sufficient | `ConnectionManager` class per FastAPI official docs |
| **orjson** | 4KB JSON payloads x 5/sec. stdlib `json.dumps` takes <0.1ms. orjson saves microseconds for an extra dep | `import json` (stdlib) |
| **Tailwind UI / Headless UI / Radix Vue** | Component libraries for complex multi-page apps. Dashboard has 3 views with minimal form controls | Custom Vue components |
| **Quasar / Vuetify / PrimeVue** | Full UI frameworks impose a visual language conflicting with minimalist dark-terminal aesthetic. 200KB+ bundles | Custom dark theme via CSS variables matching TUI palette |
| **msgpack / protobuf** | Binary WebSocket frames. Lose browser DevTools inspection for ~25% size savings on 4KB payloads | JSON text frames |

---

## Stack Patterns

### Force-Directed Graph Composable (`useForceGraph.ts`)

```typescript
// D3 for physics computation, Vue for SVG DOM rendering
const nodes = ref<GraphNode[]>([])
const links = ref<GraphLink[]>([])

// NOT reactive -- D3 mutates node objects directly during simulation
let simulation: d3.Simulation<GraphNode, GraphLink>

onMounted(() => {
  simulation = d3.forceSimulation(nodes.value)
    .force("charge", d3.forceManyBody().strength(-80))
    .force("link", d3.forceLink(links.value).id(d => d.id).distance(60))
    .force("center", d3.forceCenter(width / 2, height / 2))
    // Bracket clustering: pull nodes toward bracket group centers
    .force("clusterX", d3.forceX(d => bracketCenterX[d.bracket]).strength(0.15))
    .force("clusterY", d3.forceY(d => bracketCenterY[d.bracket]).strength(0.15))
    .force("collide", d3.forceCollide(12))
    .on("tick", () => {
      // Trigger Vue reactivity -- spread creates new array reference
      nodes.value = [...simulation.nodes()]
    })
})

// When WebSocket pushes new INFLUENCED_BY edge:
function addEdge(source: string, target: string, weight: number) {
  links.value.push({ source, target, weight })
  simulation.force("link", d3.forceLink(links.value).id(d => d.id).distance(60))
  simulation.alpha(0.3).restart()  // Reheat to animate new edge into position
}
```

### WebSocket State Sync Composable (`useSimulationSocket.ts`)

```typescript
// VueUse handles reconnect, heartbeat, reactive connection status
const { status, data, send } = useWebSocket('ws://localhost:8000/ws/simulation', {
  autoReconnect: { retries: 5, delay: 1000 },
  heartbeat: { message: 'ping', interval: 30000 },
})

// Route incoming messages to appropriate Pinia store actions
watch(data, (raw) => {
  if (!raw) return
  const msg: ServerMessage = JSON.parse(raw)
  switch (msg.type) {
    case 'snapshot':       simulationStore.applySnapshot(msg.data); break
    case 'edge_created':   graphStore.addEdge(msg.data); break
    case 'agent_decision': simulationStore.updateAgent(msg.data); break
    case 'phase_change':   simulationStore.setPhase(msg.data); break
    case 'governor':       simulationStore.updateGovernor(msg.data); break
    case 'interview_token': interviewStore.appendToken(msg.data); break
  }
})

// Send commands to server
function injectShock(text: string) {
  send(JSON.stringify({ type: 'inject_shock', data: { text } }))
}
```

### Pinia Simulation Store (`stores/simulation.ts`)

```typescript
export const useSimulationStore = defineStore('simulation', () => {
  const agents = ref(new Map<string, AgentState>())
  const phase = ref<SimulationPhase>('IDLE')
  const round = ref(0)
  const governorMetrics = ref<GovernorMetrics | null>(null)
  const bracketSummaries = ref<BracketSummary[]>([])
  const selectedAgentId = ref<string | null>(null)

  // Derived state (computed)
  const agentsByBracket = computed(() => groupBy(agents.value, 'bracket'))
  const signalDistribution = computed(() => countSignals(agents.value))
  const selectedAgent = computed(() =>
    selectedAgentId.value ? agents.value.get(selectedAgentId.value) ?? null : null
  )

  function applySnapshot(snapshot: StateSnapshot) {
    phase.value = snapshot.phase
    round.value = snapshot.round_num
    for (const [id, state] of Object.entries(snapshot.agent_states)) {
      agents.value.set(id, state)
    }
    bracketSummaries.value = snapshot.bracket_summaries
    governorMetrics.value = snapshot.governor_metrics
  }

  return { agents, phase, round, selectedAgentId, agentsByBracket,
           signalDistribution, selectedAgent, applySnapshot }
})
```

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Vue ^3.5.32 | Pinia ^3.0.4 | Pinia 3.x requires Vue 3.5+ (dropped Vue 2 support) |
| Vue ^3.5.32 | @vueuse/core ^14.2.0 | VueUse 14.x requires Vue 3.5+ |
| Vue ^3.5.32 | vue-router ^5.0.4 | Router 5.x is the Vue 3 line |
| Vite ^8.0.0 | Node.js >=20.19 or >=22.12 | Vite 8 dropped Node 18 support |
| FastAPI >=0.135.0 | Python >=3.10 | Project uses 3.11+, compatible |
| FastAPI >=0.135.0 | uvicorn >=0.44.0 | Recommended ASGI server per FastAPI docs |
| FastAPI >=0.135.0 | starlette (auto-installed) | FastAPI pins its Starlette version internally |
| d3-force ^3.0.0 | d3-selection ^3.0.0 | Both D3 v7 era modules, compatible |
| d3-force ^3.0.0 | d3-force-clustering ^1.0.0 | d3-force-clustering designed as d3-force plugin |
| @types/d3-force | d3-force ^3.0.0 | DefinitelyTyped definitions match d3-force v3 API |

---

## Integration with Existing Codebase

### StateStore -> WebSocket Bridge

The existing `StateStore` class (state.py line 87) produces `StateSnapshot` frozen dataclasses via `snapshot()`. The WebSocket layer wraps this:

1. `StateStore.snapshot()` returns `StateSnapshot` (existing, unchanged)
2. New: `snapshot_to_dict()` serializer -- use `dataclasses.asdict()` with custom enum handling, or a parallel Pydantic model
3. New: `WebSocketBroadcaster` asyncio background task calls `store.snapshot()` at 200ms intervals and broadcasts via ConnectionManager

### Existing HSL Color Logic Ports Directly

The `compute_cell_color()` function in tui.py (line 47) uses HSL color mapping:
- BUY: `hsl(120, 60%, 20-50%)` green, lightness scaled by confidence
- SELL: `hsl(0, 70%, 20-50%)` red, lightness scaled by confidence
- HOLD: `#555555` fixed grey
- PENDING: `#333333` dim grey

This maps directly to SVG `fill` attributes. Use `d3.scaleLinear` for confidence -> lightness, producing CSS `hsl()` strings that work identically in SVG.

### Files That Change

| File | Change | Scope |
|------|--------|-------|
| `state.py` | Add `snapshot_to_dict()` or Pydantic serializer for StateSnapshot | ~20 lines added |
| `simulation.py` | Add event hooks for edge creation, per-agent decisions (push to WebSocket) | ~30 lines added |
| `app.py` | New FastAPI application factory, mount WebSocket + REST routes | New file or major refactor |
| `tui.py` | **Delete entirely** (~800+ lines) | Full removal |
| `cli.py` | Update entrypoints: `start` launches uvicorn instead of Textual app | Small refactor |
| `pyproject.toml` | Add fastapi + uvicorn, remove textual, update `[project.scripts]` | Small edit |

---

## Development Tooling

| Tool | Purpose | Configuration |
|------|---------|---------------|
| Vite dev server | Frontend HMR + API proxy | `vite.config.ts`: proxy `/api/*` and `/ws/*` to `localhost:8000` |
| uvicorn `--reload` | Backend hot-reload during dev | `uvicorn alphaswarm.web:app --reload --port 8000` |
| Vue DevTools (browser extension) | Pinia store inspection, component tree, reactivity tracking | Install for Chrome or Firefox |
| wscat | WebSocket testing from CLI | `npx wscat -c ws://localhost:8000/ws/simulation` |
| Vitest | Vue component unit tests | Ships with `create-vue` scaffold |
| pytest-asyncio | FastAPI endpoint and WebSocket tests (existing) | Already in dev dependencies |

---

## Sources

- [D3 Force Module -- official docs](https://d3js.org/d3-force) -- Force API, available forces, velocity Verlet integrator (HIGH confidence)
- [D3 Force Simulation -- official docs](https://d3js.org/d3-force/simulation) -- Alpha/decay, tick events, restart, node positioning API (HIGH confidence)
- [FastAPI WebSocket -- official docs](https://fastapi.tiangolo.com/advanced/websockets/) -- ConnectionManager pattern, broadcast, websockets requirement (HIGH confidence)
- [Pinia -- official docs](https://pinia.vuejs.org/) -- v3.0.4, official Vue 3 state management (HIGH confidence)
- [VueUse useWebSocket](https://vueuse.org/core/usewebsocket/) -- Auto-reconnect, heartbeat, reactive refs API (HIGH confidence)
- [Cytoscape.js performance docs](https://github.com/cytoscape/cytoscape.js/blob/master/documentation/md/performance.md) -- Edge rendering cost warnings (HIGH confidence)
- [d3-force-clustering -- GitHub](https://github.com/vasturiano/d3-force-clustering) -- Bracket clustering force plugin (MEDIUM confidence -- third-party)
- [SVG edge animation technique](https://www.visualcinnamon.com/2016/01/animating-dashed-line-d3/) -- stroke-dasharray + dashoffset pattern (HIGH confidence -- established technique)
- [FastAPI 0.135.3 -- PyPI](https://pypi.org/project/fastapi/) -- Latest version April 2026 (HIGH confidence)
- [uvicorn 0.44.0 -- PyPI](https://pypi.org/project/uvicorn/) -- Latest version April 2026 (HIGH confidence)
- [Vue 3.5.32 -- npm](https://www.npmjs.com/package/vue) -- Latest stable April 2026 (HIGH confidence)
- [vue-router 5.0.4 -- npm](https://www.npmjs.com/package/vue-router) -- Latest March 2026 (HIGH confidence)
- [Pinia 3.0.4 -- npm](https://www.npmjs.com/package/pinia) -- Latest November 2025 (HIGH confidence)
- [VueUse 14.2.1 -- npm](https://www.npmjs.com/package/@vueuse/core) -- Latest February 2026 (HIGH confidence)
- [Vite 8.0 -- releases](https://vite.dev/releases) -- Latest major 2026 (MEDIUM confidence -- exact minor unverified)
- [D3 7.9.0 -- npm](https://www.npmjs.com/package/d3) -- Umbrella package version (HIGH confidence)
- [Cytoscape.js 3.33.2 -- npm](https://www.npmjs.com/package/cytoscape) -- Evaluated and rejected for this use case (HIGH confidence)
- [SSE vs WebSocket 2026](https://dev.to/polliog/server-sent-events-beat-websockets-for-95-of-real-time-apps-heres-why-a4l) -- Bidirectional requirement justifies WebSocket (MEDIUM confidence)

---
*Stack research for: AlphaSwarm v5.0 Web UI*
*Researched: 2026-04-12*
*Supersedes: v2.0 stack research from 2026-03-31*
*Builds on: v1-v4 validated stack (Python 3.11+, asyncio, Ollama, Neo4j, pydantic, structlog)*
