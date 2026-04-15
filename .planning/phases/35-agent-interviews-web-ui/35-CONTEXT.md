# Phase 35: Agent Interviews Web UI - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Click any agent node in the post-simulation force graph to open a live multi-turn interview panel backed by the existing `InterviewEngine`. The panel replaces `AgentSidebar` in the right-side slot. Conversation history persists within the browser session (survives panel close/reopen). Only available in the `complete` phase.

</domain>

<decisions>
## Implementation Decisions

### Panel Trigger
- **D-01:** The "Interview" button lives **inside AgentSidebar**, at the bottom of the panel. Node click still opens AgentSidebar (signal, bracket, rationale). Clicking "Interview Agent NN" closes the sidebar and opens the interview panel in its place.
- **D-02:** No change to the ForceGraph node-click event (`@select-agent`). The trigger upgrade is entirely inside AgentSidebar — no new graph interaction needed.

### Sidebar Coexistence
- **D-03:** Interview panel **replaces** AgentSidebar — single panel at a time in the right-side slot. When the user closes the interview panel (`X` button), they return to the empty/normal state (no sidebar). If they want AgentSidebar again, they click the node again.
- **D-04:** `App.vue` uses `interviewAgentId` ref (distinct from `selectedAgentId`). When `interviewAgentId` is set, `InterviewPanel` renders instead of `AgentSidebar`. Setting `interviewAgentId` clears `selectedAgentId` and vice versa.

### Session Lifecycle
- **D-05:** Conversation history persists **in Vue reactive state** (`Map<string, Message[]>` keyed by `agent_id`), not on the server. Closing and reopening the panel for the same agent continues the conversation. Page refresh clears all history.
- **D-06:** Backend maintains one `InterviewEngine` instance per `agent_id` in a dict on `app.state` (e.g., `app.state.interview_sessions: dict[str, InterviewEngine]`). Frontend history is for display; backend engine holds the actual LLM conversation window. Both reset on server restart/page refresh — consistent behavior.

### Interview Availability
- **D-07:** The "Interview" button inside AgentSidebar is only visible when `snapshot.phase === 'complete'`. During `active`, `replay`, or any other phase, AgentSidebar renders without the button.

### Backend Endpoint Design
- **D-08:** Single endpoint: `POST /api/interview/{agent_id}` accepts `{ message: str }`. On first call for an agent, reconstructs `InterviewContext` via `graph_manager.read_agent_interview_context(agent_id)` and creates a new `InterviewEngine`. Subsequent calls use the existing engine. Returns `{ response: str }`.
- **D-09:** New route file: `src/alphaswarm/web/routes/interview.py`. Router registered in `app.py` under `/api`.

### Frontend Component
- **D-10:** New `InterviewPanel.vue` component. Structure: agent name header + close button → scrollable message history → text input + Send button at bottom. Same right-side slide-in transition as `AgentSidebar`.
- **D-11:** Non-blocking: while LLM responds, the Send button shows a loading state and input is disabled. No spinner overlay — just button state change.

### Claude's Discretion
- Exact styling of the Interview button in AgentSidebar (ghost button, same width as panel)
- Message bubble styling (user vs agent visual distinction — color difference or alignment)
- Error handling for failed `/api/interview` calls (show inline error message in chat, don't crash panel)
- Whether to include a "New conversation" button to reset history for the current agent mid-session

</decisions>

<specifics>
## Specific Ideas

- The interview panel header should show the agent name ("Agent 07") so the user knows who they're talking to after the sidebar closes.
- "Interview Agent NN" button at bottom of AgentSidebar — consistent with the existing sidebar close button styling family.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### InterviewEngine (core — read before any backend work)
- `src/alphaswarm/interview.py` — `InterviewEngine` class, `InterviewContext`, `RoundDecision` types; `WINDOW_SIZE = 10`; `turn()` method signature
- `src/alphaswarm/graph.py` line ~1032 — `read_agent_interview_context(agent_id)` — reconstructs full `InterviewContext` from Neo4j

### Frontend integration points
- `frontend/src/components/AgentSidebar.vue` — to be extended with Interview button (only in complete phase); existing inject pattern (`snapshot`, `latestRationales`)
- `frontend/src/App.vue` — where `interviewAgentId` ref lives and `InterviewPanel` is mounted; existing `selectedAgentId` / `sidebarOpen` pattern to mirror
- `frontend/src/types.ts` — `StateSnapshot`, `AgentState` types

### Web infrastructure (patterns to follow)
- `src/alphaswarm/web/app.py` — lifespan pattern for mounting singletons on `app.state`; router registration
- `src/alphaswarm/web/routes/simulation.py` — REST endpoint pattern (request body, response model, accessing `app.state`)
- `frontend/src/components/CyclePicker.vue` — fetch-on-open pattern, loading state management
- `frontend/src/components/ShockDrawer.vue` — slide-in panel with `<Transition>` from within ControlBar (structural reference)

### Phase context
- `.planning/phases/34-replay-mode-web-ui/34-CONTEXT.md` — established patterns for ControlBar state management and Vue SFC conventions
- `.planning/ROADMAP.md` §"Phase 35: Agent Interviews Web UI" — success criteria SC-1 through SC-5

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `InterviewEngine` (`interview.py:65`): fully built — `turn(message: str) -> str` method handles the full LLM call, sliding window, and summarization. Backend just needs to instantiate it per agent and store it.
- `read_agent_interview_context()` (`graph.py:1032`): returns `InterviewContext` with persona, decision narrative, and all 3 rounds of decisions — ready to pass to `InterviewEngine.__init__()`
- `AgentSidebar.vue`: already injects `snapshot` — can compute `isComplete = snapshot.value.phase === 'complete'` to gate the Interview button

### Established Patterns
- Backend singletons on `app.state`: `sim_manager`, `replay_manager`, `connection_manager` — add `interview_sessions: dict[str, InterviewEngine]` initialized as `{}` in lifespan
- Vue right-side panels: `AgentSidebar` uses `<Transition name="sidebar">` wrapper in `App.vue` — `InterviewPanel` uses the same transition
- REST calls from Vue: `fetch('/api/...')` with `async/await`, loading ref toggled around the call (see `CyclePicker.vue` fetch-on-open pattern)

### Integration Points
- `App.vue`: add `interviewAgentId = ref<string | null>(null)`; v-if/v-else between `AgentSidebar` and `InterviewPanel` based on which is set
- `AgentSidebar.vue`: add `@open-interview` emit; `InterviewPanel` button visible when `snapshot.value.phase === 'complete'`
- `app.py` lifespan: initialize `app.state.interview_sessions = {}`; import and register interview router

</code_context>

<deferred>
## Deferred Ideas

- Auto-playback / timer-based interview advancement — out of scope
- Persistent interview history across page refreshes (LocalStorage or Neo4j) — future phase
- Multi-agent simultaneous interviews — out of scope

</deferred>

---

*Phase: 35-agent-interviews-web-ui*
*Context gathered: 2026-04-15*
