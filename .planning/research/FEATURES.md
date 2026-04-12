# Feature Landscape: v5.0 Web UI

**Domain:** Real-time multi-agent simulation visualization dashboard (browser-based, replacing Textual TUI)
**Researched:** 2026-04-12
**Overall confidence:** HIGH (graph rendering at 100 nodes is well-trodden territory; WebSocket patterns are commodity)

## Existing Foundation (Already Built -- NOT Re-Researched)

These are shipped and validated. Listed only to establish data dependencies for new features.

| Feature | Source | Data Contract |
|---------|--------|---------------|
| 100-agent 3-round consensus cascade | `simulation.py` | `run_simulation()` writes to `StateStore` |
| StateStore snapshot (200ms tick) | `state.py` | `StateSnapshot` frozen dataclass |
| ReplayStore (non-destructive snapshot) | `state.py` | Same `StateSnapshot` interface |
| ResourceGovernor (5-state machine) | `governor.py` | `GovernorMetrics` in snapshot |
| Neo4j graph state (decisions, influence edges, posts) | `graph.py` | `GraphStateManager` async methods |
| Agent interviews (conversational Q&A) | `interview.py` | `InterviewEngine` stateful session |
| Report generation (ReACT + Jinja2) | `report.py` | `ReportEngine` + `ReportAssembler` |
| Shock injection + impact analysis | `graph.py` | `read_shock_event()`, `read_shock_impact()` |
| Simulation replay from Neo4j | `graph.py` + `state.py` | `read_full_cycle_signals()` + `ReplayStore` |

---

## Table Stakes

Features users expect. Missing = the web UI feels incomplete relative to the TUI it replaces.

| Feature | Why Expected | Complexity | Phase | Notes |
|---------|--------------|------------|-------|-------|
| Live agent state grid/graph | TUI had a 10x10 color-coded grid. Web UI replaces with force graph. | High | 3 | Hero feature. d3-force + Canvas. |
| WebSocket real-time state stream | TUI polled at 200ms. Web must push state over WebSocket. | Medium | 2 | asyncio.Event bridge + StateRelay broadcast. |
| Start simulation from browser | TUI had rumor input screen. Web needs equivalent. | Low | 4 | REST POST endpoint + text input UI. |
| Bracket signal distribution panel | TUI had BracketPanel widget. | Low | 5 | Reads `brackets` from snapshot. |
| Rationale feed panel | TUI had scrolling rationale sidebar. | Low | 5 | Reads `rationale` from snapshot. Rolling window. |
| Telemetry footer (TPS, elapsed, governor state) | TUI had telemetry bar. | Low | 5 | Reads `tps`, `elapsed`, `governor` from snapshot. |
| Shock injection during simulation | TUI had ShockInputScreen modal. | Medium | 4 | REST POST + governor suspend/resume. |
| Simulation replay mode | TUI had CyclePickerScreen + round auto-advance. | Medium | 6 | REST endpoints + StateRelay dual-source. |
| Agent interview panel | TUI had InterviewScreen overlay. | Medium | 7 | WebSocket session wrapping InterviewEngine. |
| Agent click-to-inspect | TUI had rationale sidebar on cell click. | Low | 3 | Canvas hit detection + tooltip/panel. |

## Differentiators

Features that go beyond TUI parity. Not expected for MVP, but make the web UI demonstrably superior.

| Feature | Value Proposition | Complexity | Phase | Notes |
|---------|-------------------|------------|-------|-------|
| Force-directed influence topology | See INFLUENCED_BY edges animate as agents cite each other. The TUI grid showed no edges. | High | 3 | d3-force links with weight-based distance + opacity. |
| Bracket clustering in graph | Agents visually cluster by bracket type. TUI grid was fixed 10x10. | Medium | 3 | forceX/forceY with bracket-specific targets. |
| Edge animation on new influence | When an agent cites another, the edge pulses/glows briefly. | Medium | 5 | Canvas animation triggered by round transition. |
| Smooth state transitions | Agent nodes fade between colors (pending -> signal) instead of instant swap. | Low | 5 | Canvas interpolation on d3 tick. |
| Report viewer in browser | TUI had no report viewer -- CLI only. | Low | 8 | Render markdown in browser panel. |
| Zoom and pan on graph | Navigate dense areas of the 100-node topology. | Low | 3 | d3-zoom composable on Canvas. |
| Agent search/filter | Find specific agents by bracket or ID. | Low | 5 | Filter in Pinia store, highlight in graph. |
| Round-by-round edge diff in replay | Show which edges were added/removed between rounds. | Medium | 6 | Compare edge sets across rounds, color new edges. |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Multi-user collaboration | Out of scope per PROJECT.md. Single-operator local tool. | Serve on localhost only. No auth system. |
| Persistent dashboard state | No need to save layout/preferences across sessions. | Default layout every time. Keep it simple. |
| Drag-to-rearrange panels | Adds docking/layout complexity. Minimalist aesthetic. | Fixed panel layout. Clean and predictable. |
| 3D graph visualization | d3-force-3d exists but adds WebGL complexity for no analytical value at 100 nodes. | 2D force-directed is sufficient and more readable. |
| Real-time token streaming in interview | Streaming LLM tokens over WebSocket is complex and Ollama streaming support varies. | Send complete response after inference finishes. Can add streaming later. |
| Dark/light theme toggle | The TUI had a single dark theme. Maintaining two themes doubles CSS work. | Dark theme only. Matches existing aesthetic. |
| Export graph as image | Nice-to-have but adds Canvas-to-PNG export plumbing. | Users can screenshot. Add if requested. |
| Mobile responsiveness | Local-only tool. Developer runs it on their workstation. | Desktop-only layout. Minimum 1280px width. |

---

## Feature Dependencies

```
FastAPI Skeleton (P1) ──> WebSocket State Stream (P2) ──> Vue SPA + ForceGraph (P3)
                                                              |
                                                              ├──> REST Control + ControlBar (P4)
                                                              |         |
                                                              |         └──> Shock Injection (P4)
                                                              |
                                                              ├──> Panels: Bracket, Rationale, Telemetry (P5)
                                                              |         |
                                                              |         └──> Edge Animation, Smooth Transitions (P5)
                                                              |
                                                              ├──> Replay Mode (P6)
                                                              |         |
                                                              |         └──> Round-by-round edge diff (P6)
                                                              |
                                                              ├──> Interview WebSocket (P7)
                                                              |
                                                              └──> Report Viewer + Kill TUI (P8)
```

Key dependency: **Everything depends on Phases 1-2 (server + data pipe).** Phases 3-7 depend on the Vue SPA scaffold (Phase 3). Phases 5-7 are somewhat parallelizable.

---

## MVP Recommendation

The MVP that proves the architecture works end-to-end:

1. **WebSocket state stream** (Phase 2) -- data flows from simulation to browser.
2. **Force-directed graph with live agent updates** (Phase 3) -- 100 nodes change color as decisions arrive.
3. **Start simulation from browser** (Phase 4) -- no longer dependent on CLI to trigger simulation.

This MVP lets you launch a simulation from the browser and watch 100 agents reason and form consensus in real-time on a force-directed graph. Everything else is polish and feature parity.

**Defer:**
- Interview panel (Phase 7): Requires completed simulation. Add after core loop works.
- Report generation (Phase 8): Least interactive feature. Can always use existing CLI path.
- Edge animation/smooth transitions (Phase 5): Visual polish. Core graph works without it.

---

## Graph Edge Data Gap

**Important finding:** The current `StateSnapshot` does NOT contain influence edge data. The TUI grid never showed edges. The force-directed graph needs edges (INFLUENCED_BY relationships with weights) to draw links between nodes.

**Resolution options:**

1. **Supplement WebSocket with edge push after each round.** After `compute_influence_edges()` in `run_simulation()`, push edge data through a separate WebSocket message type or an additional field on the snapshot.
2. **REST endpoint for edges.** `GET /api/edges/{cycle_id}?round=N` fetches edges on demand. Vue app polls after round transitions detected in snapshot.
3. **Add edges to StateStore/StateSnapshot.** Modify StateStore to hold current edges. Cleanest but highest modification cost.

**Recommendation:** Option 2 (REST endpoint). Edges change only once per round (not per agent tick). A REST fetch on round transition is efficient and avoids modifying StateStore's hot-path contract. The Vue app watches `snapshot.round` and fetches edges when it changes.

---

## Sources

- [d3-force module](https://d3js.org/d3-force)
- [D3.js Force-Directed Graph 2025](https://dev.to/nigelsilonero/how-to-implement-a-d3js-force-directed-graph-in-2025-5cl1)
- [Vue 3 Composition API with D3](https://dev.to/muratkemaldar/using-vue-3-with-d3-composition-api-3h1g)
- [Building Interactive Force-Directed Graphs with D3.js, Vue 3](https://medium.com/@jeashan999/building-interactive-force-directed-graphs-with-d3-js-vue-3-and-ruby-on-rails-193caea58e65)
- [FastAPI WebSocket documentation](https://fastapi.tiangolo.com/advanced/websockets/)
- [Managing Multiple WebSocket Clients in FastAPI](https://hexshift.medium.com/managing-multiple-websocket-clients-in-fastapi-ce5b134568a2)
