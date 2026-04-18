# Milestones

## v5.0 Web UI (Shipped: 2026-04-18)

**Phases completed:** 8 phases (29–36 + 35.1 insertion), ~20 plans

**Key accomplishments:**

- FastAPI + uvicorn skeleton with lifespan, async event loop foundation, and WebSocket connection manager broadcasting StateSnapshot at ~5Hz
- Vue 3 + Vite SPA with D3 force-directed "mirofish" agent graph — color-coded by signal/confidence, Bezier influence edges, WebSocket composable
- REST simulation controls (start/stop/shock) + Vue ControlBar with ShockDrawer; replay contract stubs wired to replayManager
- Web monitoring panels — live rationale feed with CSS slide-in animation (capped at 20 entries) + D3 bracket sentiment bars updating from snapshot
- Replay mode web UI — CyclePicker modal, round-by-round step controls, force graph re-render from Neo4j stored state without re-inference
- Agent interviews web UI — click any post-simulation graph node to open multi-turn interview panel proxying to InterviewEngine; non-blocking LLM calls with loading indicator
- Report viewer — marked + DOMPurify render pipeline, polling state machine, ControlBar Report button gated on simulation phase='complete'; production build 80 kB gzip
- Shock injection wiring (B1 closure) — ShockEvent nodes persisted to Neo4j end-to-end; governor suspend/resume guards around shock window

---

## v6.0 Real Data + Advisory (In Progress)

**Started:** 2026-04-18

**Phase 37 complete:** Isolation foundation — frozen type contracts (`Holding`, `PortfolioSnapshot`, `ContextPacket`, `MarketSlice`, `NewsSlice`), provider protocols + fakes, PII redaction processor, pytest-socket global gate, importlinter holdings isolation contract with drift-resistant coverage test

---
