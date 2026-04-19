---
phase: 35
reviewers: [gemini, codex]
reviewed_at: 2026-04-15T00:00:00Z
plans_reviewed: [35-01-PLAN.md, 35-02-PLAN.md, 35-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 35

## Gemini Review

### Summary
The plan follows a robust **Backend (Plan 01) -> Frontend (Plan 02) -> Verification (Plan 03)** sequence. It correctly identifies the need for session persistence in the browser via a module-scoped Map and addresses backend state management using the `app.state` pattern. The inclusion of TDD (Wave 0) tests ensures the API contract is solid before frontend development begins.

### Strengths
- **Persistence Logic:** The use of a module-scoped `Map` in `InterviewPanel.vue` is an elegant way to preserve conversation history across panel toggles without polluting global state or requiring LocalStorage.
- **Architectural Consistency:** The backend endpoint design mirrors the `replay.py` and `simulation.py` patterns, utilizing `app.state` for singletons and `structlog` for traceability.
- **Robust Error Handling:** The plan explicitly accounts for service unavailability (503) and missing data (404), providing a reliable fallback for the UI.
- **Optimistic UI:** The frontend task includes optimistic message updates and auto-scrolling, critical for a "chat-like" feel in LLM interactions.
- **TDD Approach:** Wave 0 test scaffolds ensure edge cases are handled before logic is implemented.

### Concerns
- **[MEDIUM] Session Cleanup Gap:** Plan 01 does not include `src/alphaswarm/simulation.py` in its `files_modified` list. Without clearing `interview_sessions` on new simulation start, interviews in a second run could reuse an old `InterviewEngine` if the `agent_id` matches.
- **[LOW] Agent ID Validation:** If `read_agent_interview_context` is called with a non-existent `agent_id`, it should return 404. It is unclear if the method handles this or if the route needs an extra guard.
- **[LOW] Replay Mode Ambiguity:** D-08 resolves `cycle_id` from the "most recent completed cycle." If a user is in Replay Mode (Phase 34) viewing an older cycle, clicking "Interview" may unexpectedly use context from the newest cycle instead of the replayed one.

### Suggestions
- Implement session cleanup when a new simulation starts — either hook into `SimulationManager._run()` or key sessions by `(cycle_id, agent_id)`.
- Add a 404 guard when `read_agent_interview_context` returns an empty or None context.
- Document the replay-mode limitation in Plan 03 verification checklist.

### Risk Assessment
**LOW.** The plan is well-designed and the concerns are minor edge cases. The core implementation is sound.

---

## Codex Review

### Summary
The three-plan split is sensible: backend API first, frontend integration second, human end-to-end verification third. The plans are detailed and mostly aligned with the phase goal. However, there are several correctness risks that should be addressed before execution, especially around backend session lifecycle, API phase gating, concurrent interview calls, and a current frontend mismatch where `complete` state appears to hide the graph. As written, the implementation is likely to pass the planned narrow tests but may fail the actual browser workflow.

### Plan 01 Strengths
- Clear backend/frontend separation; Plan 02 can depend cleanly on the `/api/interview/{agent_id}` contract.
- Uses existing `InterviewEngine.ask()` and `read_agent_interview_context(agent_id, cycle_id)` contracts correctly.
- Tests cover happy path, session creation/reuse, missing Neo4j/Ollama, no completed cycles, and production route registration.
- Follows existing `app.state` singleton style consistent with `sim_manager`, `replay_manager`, and `connection_manager`.

### Plan 01 Concerns
- **[HIGH] No backend phase guard.** The frontend hides the button outside `complete`, but the API still allows interviews during active simulations. It uses the most recent completed cycle, which may be stale and competes with active simulation inference on the local Ollama instance.
- **[HIGH] Session lifecycle underspecified.** The threat model says sessions clear on new simulation start, but the plan does not implement this. Same `agent_id` can reuse an old `InterviewEngine` after a new simulation completes.
- **[HIGH] No per-agent lock around `InterviewEngine.ask()`.** The engine mutates `_history`; concurrent requests for the same agent can interleave history writes and produce inconsistent conversation windows.
- **[MEDIUM] Lazy session creation has a race.** Two simultaneous first requests for the same `agent_id` can both reconstruct context and create separate engines.
- **[MEDIUM] Invalid `agent_id` may not return 404.** Graph context reconstruction can return an empty `InterviewContext`; the route would still instantiate an engine with no persona/details.
- **[MEDIUM] Request validation is too loose.** `message: str` accepts empty strings and unbounded payloads.
- **[MEDIUM] Neo4j and Ollama failures not mapped to user-facing HTTP errors.** They will likely surface as 500s, while the frontend expects clean inline error behavior.

### Plan 01 Suggestions
- Add backend availability gating: return `409` or `403` unless current state phase is `complete`.
- Key sessions by `(cycle_id, agent_id)`, not only `agent_id`, or clear `app.state.interview_sessions` on `/api/simulate/start`.
- Store session objects with an `asyncio.Lock` — e.g. `{engine, lock, cycle_id}` — and lock around `ask()`.
- Add a global interview semaphore to avoid multiple simultaneous Ollama calls on local hardware.
- Validate request body: `Field(min_length=1, max_length=4000)`.
- Return `404` when context has no agent name/persona/decisions.
- Catch graph/Ollama exceptions and return structured `503`/`502` details.

### Plan 02 Strengths
- Implements the locked decision that the Interview button lives inside `AgentSidebar`.
- Maintains single right-side panel slot instead of stacking panels.
- Non-blocking UI with optimistic user message, disabled input, and loading text.
- Inline error handling; avoids `v-html` so agent responses render safely as text.
- Reuses existing sidebar transition and width behavior.

### Plan 02 Concerns
- **[HIGH] `App.vue` hides graph in `complete` state.** Current `App.vue` uses `isIdle = phase === 'idle' || phase === 'complete'`, so the force graph is hidden exactly when the Interview button should appear. The planned flow may be impossible without fixing this condition.
- **[HIGH] `onSelectAgent()` does not clear `interviewAgentId`.** If the interview panel is open and the graph remains clickable, selecting another node can leave stale `selectedAgentId`; closing the interview may unexpectedly show the wrong sidebar.
- **[MEDIUM] Module-level plain `Map` is not reactive.** May work incidentally because other refs trigger re-renders, but is fragile and does not match D-05's intent of "Vue reactive state." Use `reactive(new Map())`.
- **[MEDIUM] Unused imports `watch` and `PropType`.** The repo has `noUnusedLocals: true`; `vue-tsc` will fail unless these are removed.
- **[MEDIUM] `fetch` URL not encoded.** `fetch(`/api/interview/${props.agentId}`)` should use `encodeURIComponent(props.agentId)`.
- **[MEDIUM] Frontend/backend history divergence on refresh.** Backend retains session history; frontend loses it on page refresh. Creates hidden server-side conversation state.

### Plan 02 Suggestions
- Fix the `complete` state display condition in `App.vue`: show empty state only when `phase === 'idle'` and there are no `agent_states`. Do not treat `complete` as idle.
- In `onSelectAgent()`, clear `interviewAgentId` per D-04 — or explicitly ignore graph clicks while interview panel is open.
- Use `reactive(new Map<string, ChatMessage[]>())` for the conversation store.
- Remove unused imports (`watch`, `PropType`) from `InterviewPanel.vue`.
- Use `encodeURIComponent(props.agentId)` in the fetch call.

### Plan 03 Concerns
- **[HIGH] "While simulation is idle, click any agent node" is impossible** — idle state has no force graph or nodes.
- **[HIGH] No explicit prerequisites** for a completed simulation (Neo4j running, Ollama running, model pulled, at least one completed cycle present).
- **[MEDIUM] "Sidebar remains interactive behind it" contradicts D-03** — the interview panel replaces the sidebar, not overlays it.
- **[MEDIUM] Frontend startup command is vague** — should include `cd frontend && npm run dev` or equivalent.

### Plan 03 Suggestions
- Replace the idle-node check with verifying the Interview button is absent during `active` or `replay` phases.
- Add explicit prerequisites block to the verification checklist.
- Fix the "sidebar behind it" language to match D-03 (mutual exclusion, not overlay).

### Plan 03 Risk Assessment
**MEDIUM.** Checklist contains at least one impossible step (idle-state nodes). Needs tightening after Plans 01/02 address the `complete`-state graph issue.

### Overall Risk Assessment
**MEDIUM-HIGH.** The route will likely pass the proposed unit tests, but the tests do not cover the main operational risks: stale sessions, wrong-phase access, and concurrent mutation of interview state. The `App.vue` complete-state issue is a potential execution blocker.

---

## Consensus Summary

### Agreed Strengths (both reviewers)
- Backend/frontend wave ordering is correct and clean
- `app.state` singleton pattern for `interview_sessions` is consistent with existing codebase
- TDD Wave 0 test scaffolding is appropriate
- Error handling (503/404) is well-planned at the route level

### Agreed Concerns (raised by both)
1. **Session cleanup / lifecycle** — `interview_sessions` are not cleared when a new simulation starts; both reviewers flagged this as a gap. Gemini rated MEDIUM; Codex rated HIGH.
2. **Invalid `agent_id` validation** — route may proceed with empty context instead of returning 404.
3. **Replay Mode cycle conflict** — `cycle_id` always resolves to most recent cycle, not the replayed one.

### Critical Issues (Codex only — HIGH severity)
1. **`App.vue` hides graph in `complete` state** — the force graph is invisible exactly when the Interview button appears. This is an execution blocker.
2. **No backend phase guard** — API is callable during active simulation, competing with inference on local hardware.
3. **No per-agent `asyncio.Lock`** — concurrent requests can corrupt `InterviewEngine._history`.
4. **`onSelectAgent()` does not clear `interviewAgentId`** — mutual exclusion between sidebar and interview panel is incomplete.

### Divergent Views
- **Overall risk level:** Gemini rates LOW (concerns are minor edge cases); Codex rates MEDIUM-HIGH (believes `App.vue` complete-state issue is a blocking bug). The `App.vue` `isIdle` condition should be verified against current source before planning revision — if `complete` already shows the graph, Codex's highest concern is moot.
- **Module-scoped Map reactivity:** Gemini calls it "elegant"; Codex flags it as fragile. A `reactive(Map)` wrapper resolves both views.
