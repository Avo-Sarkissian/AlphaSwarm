# Requirements: AlphaSwarm v5.0 Web UI

**Defined:** 2026-04-12
**Core Value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — the simulation engine is the product

## v5.0 Requirements

### Backend Foundation

- [ ] **BE-01**: FastAPI app factory with Uvicorn lifespan owning the asyncio event loop (StateStore, Governor, Neo4j driver all created inside lifespan context)
- [ ] **BE-02**: StateStore.snapshot() refactored to non-destructive so WebSocket broadcast does not drain the rationale queue
- [ ] **BE-03**: Per-client WebSocket queue — bounded asyncio queue + dedicated writer task per client; slow clients cannot stall the simulation
- [ ] **BE-04**: WebSocket /ws/state broadcasts StateSnapshot JSON at 5Hz to all connected clients

### REST Control API

- [ ] **BE-05**: POST /api/simulate/start — begins simulation with seed rumor payload
- [ ] **BE-06**: POST /api/shock — injects shock text mid-simulation with concurrent-request guard (returns 409 if already open)
- [ ] **BE-07**: GET /api/edges/{cycle_id}?round=N — returns INFLUENCED_BY edges for a given round (separate from snapshot)
- [ ] **BE-08**: GET /api/replay/cycles — lists completed cycles eligible for replay
- [ ] **BE-09**: POST /api/replay/start/{cycle_id} — enters replay mode for a past cycle
- [ ] **BE-10**: POST /api/replay/advance — advances replay by one round
- [ ] **BE-11**: WebSocket /ws/interview/{agent_id} — streams InterviewEngine token responses to browser

### Force-Directed Graph

- [ ] **VIS-01**: Vue 3 SPA (Vite) with useForceGraph composable keeping D3 node data outside Vue reactivity (shallowRef / markRaw)
- [ ] **VIS-02**: 100 agent nodes clustered by bracket using forceX/forceY; node color and size encode signal (buy=green, sell=red, hold=gray) and bracket archetype
- [ ] **VIS-03**: INFLUENCED_BY edges animate in on round transition, fetched from GET /api/edges after each round completes
- [ ] **VIS-04**: Click agent node opens agent detail sidebar with name, bracket, current signal, and current-round rationale text

### Monitoring Panels

- [ ] **MON-01**: Bracket summary bar — per-bracket buy/sell/hold distribution updated live from WebSocket state stream
- [ ] **MON-02**: Rationale sidebar — selected agent's full reasoning text for the active round, updated on round transitions
- [ ] **MON-03**: Telemetry strip — RAM %, active semaphore count, simulation phase label, current round indicator

### Simulation Controls

- [ ] **CTL-01**: Simulation control bar — seed rumor text input + start button; disabled during active simulation
- [ ] **CTL-02**: Shock injection drawer — opens mid-simulation only, free-text input, submit sends POST /api/shock; closes and shows confirmation on success
- [ ] **CTL-03**: Replay player — cycle picker dropdown, round stepper (manual next-round button + auto-advance toggle), round progress display

### Agent Interview

- [ ] **INT-01**: Interview chat panel — available post-simulation; click agent in graph or detail sidebar to open; streams responses token-by-token via /ws/interview/{agent_id}
- [ ] **INT-02**: Interview gated to COMPLETE simulation phase only — panel disabled with explanatory tooltip during active simulation

### Report

- [ ] **RPT-01**: Generate report button — triggers report generation via CLI wrapper, shows loading state, then opens the generated HTML file in a new browser tab via FastAPI static file serving

## Future Requirements

### Cleanup (v5.1+)

- **KILL-01**: Delete tui.py and remove Textual dependency from pyproject.toml once all web UI panels are verified as complete replacements

### Enhancements (v5.1+)

- **ENH-01**: Delta compression for WebSocket payloads (only changed agent fields)
- **ENH-02**: Replay scrubber — seek to any round directly (vs step-by-step)
- **ENH-03**: Export graph as PNG/SVG from the browser
- **ENH-04**: Multi-simulation comparison view

## Out of Scope

| Feature | Reason |
|---------|--------|
| Kill tui.py in v5.0 | TUI kept as fallback while web UI is built and verified |
| Miro API integration | Replaced by embedded force-directed graph |
| 3D force graph | Unnecessary complexity at 100 nodes; interaction becomes harder |
| Per-token simulation streaming | Ollama token stream bypasses governor; use 200ms snapshot cadence |
| Editable topology | Influence edges emerge from simulation; manual editing contradicts model |
| Interview during active simulation | InterviewEngine bypasses governor; gate to post-simulation to prevent Ollama contention |
| Multi-user / network access | Single-operator local-first design — FastAPI on localhost only |
| orjson serialization | At 4KB payloads / 5Hz over localhost, stdlib json.dumps < 0.1ms |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BE-01 | TBD | Pending |
| BE-02 | TBD | Pending |
| BE-03 | TBD | Pending |
| BE-04 | TBD | Pending |
| BE-05 | TBD | Pending |
| BE-06 | TBD | Pending |
| BE-07 | TBD | Pending |
| BE-08 | TBD | Pending |
| BE-09 | TBD | Pending |
| BE-10 | TBD | Pending |
| BE-11 | TBD | Pending |
| VIS-01 | TBD | Pending |
| VIS-02 | TBD | Pending |
| VIS-03 | TBD | Pending |
| VIS-04 | TBD | Pending |
| MON-01 | TBD | Pending |
| MON-02 | TBD | Pending |
| MON-03 | TBD | Pending |
| CTL-01 | TBD | Pending |
| CTL-02 | TBD | Pending |
| CTL-03 | TBD | Pending |
| INT-01 | TBD | Pending |
| INT-02 | TBD | Pending |
| RPT-01 | TBD | Pending |

**Coverage:**
- v5.0 requirements: 24 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 24 ⚠️

---
*Requirements defined: 2026-04-12*
*Last updated: 2026-04-12 after initial definition*
