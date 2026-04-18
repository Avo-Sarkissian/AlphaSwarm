# Milestones

## v5.0 Web UI (Shipped: 2026-04-18)

**Phases completed:** 8 phases (29, 31, 32, 33, 34, 35, 35.1, 36), 20 plans
**Timeline:** 2026-04-12 → 2026-04-18 (7 days)
**Requirements:** 6/6 v5 requirements satisfied (WEB-01 through WEB-06)
**Audit:** see `milestones/v5.0-MILESTONE-AUDIT.md` — status `tech_debt`, no critical blockers

**Key accomplishments:**

- **Phase 29 — FastAPI Skeleton:** FastAPI app with lifespan, WebSocket state stream, and shared event-loop wiring for SimulationManager.
- **Phase 31 — Vue SPA + Force Graph:** Vue 3 + Vite SPA with D3 force-directed agent graph, AgentSidebar, and reactive WebSocket composable (`useWebSocket`) driving live state updates.
- **Phase 32 — REST Controls + Control Bar:** Start/stop/shock REST endpoints with fire-and-forget `create_task` pattern, done-callback phase reset on cancel/failure, replay contract stubs, and Vue control bar with ShockDrawer.
- **Phase 33 — Web Monitoring Panels:** D3 stacked bracket bars with animated width transitions + rationale feed with dedup accumulator (20-entry cap, idle-reset), viewBox-only responsive sizing, defensive injection guards.
- **Phase 34 — Replay Mode Web UI:** `ReplayManager` class with asyncio.Lock lifecycle, 3 replay REST endpoints (start/advance/stop) loading Neo4j signals into `ReplayStore`, replay-aware broadcaster, amber REPLAY badge, round stepping UI.
- **Phase 35 — Agent Interviews Web UI:** `POST /api/interview/{agent_id}` proxying to `InterviewEngine`, slide-in `InterviewPanel.vue` with multi-turn conversation, AgentSidebar entry point, non-blocking loading indicator.
- **Phase 35.1 — Shock Injection Wiring:** Bugfix closure — wired shock drawer submission into ShockEvent persistence (Neo4j), end-to-end verification from UI click to graph write.
- **Phase 36 — Report Viewer:** `ReportViewer.vue` modal with `marked` + `DOMPurify` markdown rendering (XSS defense), Report button in control bar, polling-state fix for 404 ticks during generation, 500 `report_generation_failed` termination.

**Tech debt carried forward:**

- Phase 29 planning artifacts backfill (no PLAN/SUMMARY — predates full GSD adoption)
- Nyquist `VALIDATION.md` backfill for phases 29, 31, 35.1
- Human UAT items for phases 32, 34, 36 (9 items total — see audit report)

---
