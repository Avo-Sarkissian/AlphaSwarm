# Phase 35: Agent Interviews Web UI - Research

**Researched:** 2026-04-15
**Domain:** FastAPI REST endpoints + Vue 3 SFC for multi-turn LLM interview chat
**Confidence:** HIGH

## Summary

This phase wires the existing `InterviewEngine` (Phase 14) into the web UI via a new REST endpoint and a new Vue panel. The backend work is straightforward: a single `POST /api/interview/{agent_id}` route that lazily creates `InterviewEngine` instances per agent, stored in `app.state.interview_sessions`. The frontend work is a new `InterviewPanel.vue` SFC that replaces `AgentSidebar` in the right-side slot, with a chat-style message list and text input.

All core building blocks exist: `InterviewEngine.ask()` handles the full LLM conversation loop with sliding window; `GraphStateManager.read_agent_interview_context()` reconstructs agent context from Neo4j; the Vue app already has the sidebar slot pattern with `<Transition>`. The primary complexity is (1) resolving the `cycle_id` for context reconstruction since `StateStore` does not track it, and (2) managing the Vue reactive state for the panel/sidebar mutual exclusion.

**Primary recommendation:** Follow existing patterns exactly -- route file mirrors `replay.py`, component mirrors `AgentSidebar.vue` structure, and `App.vue` uses a second ref (`interviewAgentId`) to toggle between the two panels.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The "Interview" button lives **inside AgentSidebar**, at the bottom of the panel. Node click still opens AgentSidebar. Clicking "Interview Agent NN" closes the sidebar and opens the interview panel in its place.
- **D-02:** No change to the ForceGraph node-click event (`@select-agent`). The trigger upgrade is entirely inside AgentSidebar.
- **D-03:** Interview panel **replaces** AgentSidebar -- single panel at a time in the right-side slot. Closing the interview panel returns to the empty state. Re-clicking a node re-opens AgentSidebar.
- **D-04:** `App.vue` uses `interviewAgentId` ref (distinct from `selectedAgentId`). When `interviewAgentId` is set, `InterviewPanel` renders instead of `AgentSidebar`. Setting one clears the other.
- **D-05:** Conversation history persists in Vue reactive state (`Map<string, Message[]>` keyed by `agent_id`). Closing and reopening the panel for the same agent continues the conversation. Page refresh clears all history.
- **D-06:** Backend maintains one `InterviewEngine` instance per `agent_id` in a dict on `app.state` (e.g., `app.state.interview_sessions: dict[str, InterviewEngine]`). Frontend history is for display; backend engine holds the actual LLM conversation window. Both reset on server restart/page refresh.
- **D-07:** The "Interview" button inside AgentSidebar is only visible when `snapshot.phase === 'complete'`. During `active`, `replay`, or any other phase, AgentSidebar renders without the button.
- **D-08:** Single endpoint: `POST /api/interview/{agent_id}` accepts `{ message: str }`. On first call for an agent, reconstructs `InterviewContext` via `graph_manager.read_agent_interview_context(agent_id)` and creates a new `InterviewEngine`. Subsequent calls use the existing engine. Returns `{ response: str }`.
- **D-09:** New route file: `src/alphaswarm/web/routes/interview.py`. Router registered in `app.py` under `/api`.
- **D-10:** New `InterviewPanel.vue` component. Structure: agent name header + close button, scrollable message history, text input + Send button at bottom. Same right-side slide-in transition as `AgentSidebar`.
- **D-11:** Non-blocking: while LLM responds, Send button shows loading state and input is disabled. No spinner overlay.

### Claude's Discretion
- Exact styling of the Interview button in AgentSidebar (ghost button, same width as panel)
- Message bubble styling (user vs agent visual distinction -- color difference or alignment)
- Error handling for failed `/api/interview` calls (show inline error message in chat)
- Whether to include a "New conversation" button to reset history for the current agent mid-session

### Deferred Ideas (OUT OF SCOPE)
- Auto-playback / timer-based interview advancement
- Persistent interview history across page refreshes (LocalStorage or Neo4j)
- Multi-agent simultaneous interviews

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WEB-06 | Post-simulation views -- agent interview panel | Backend: `InterviewEngine` + `read_agent_interview_context()` fully built. Frontend: `AgentSidebar.vue` pattern, `App.vue` sidebar slot. Route pattern from `replay.py`. |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async. No blocking I/O on the main event loop. The `InterviewEngine.ask()` method is already async.
- **Local First:** All inference via Ollama. InterviewEngine uses `OllamaClient.chat()` directly.
- **Runtime:** Python 3.11+ strict typing, `uv` package manager, `pytest-asyncio`.
- **Memory Safety:** `InterviewEngine` instances accumulate in `app.state.interview_sessions` -- plan should consider cleanup on simulation restart.
- **GSD Workflow:** All edits through GSD commands.
- **Developer preference:** Clean, minimalist aesthetic. Step-by-step explanations.

## Standard Stack

### Core (already installed -- no new packages)

| Library | Purpose | Why Standard |
|---------|---------|--------------|
| FastAPI | REST endpoint for interview | Already the backend framework (Phase 29) |
| Pydantic | Request/response models | Already used for all REST endpoints |
| Vue 3 | InterviewPanel.vue SFC | Already the frontend framework (Phase 31) |
| structlog | Backend logging | Already the project logging library |

### Supporting (already installed)

| Library | Purpose | When to Use |
|---------|---------|-------------|
| `InterviewEngine` (internal) | Multi-turn LLM conversation with sliding window | Backend endpoint creates one per agent |
| `GraphStateManager` (internal) | `read_agent_interview_context()` for Neo4j reads | On first interview call per agent |
| `OllamaClient` (internal) | `chat()` for LLM inference | Passed to InterviewEngine constructor |

**Installation:** No new packages required. All dependencies are already in the project.

## Architecture Patterns

### Backend Route Structure

New file: `src/alphaswarm/web/routes/interview.py`

Follow the exact pattern from `simulation.py` and `replay.py`:

```python
# Source: src/alphaswarm/web/routes/simulation.py (verified)
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter()

class InterviewRequest(BaseModel):
    message: str

class InterviewResponse(BaseModel):
    response: str

@router.post("/interview/{agent_id}", response_model=InterviewResponse)
async def interview_agent(agent_id: str, body: InterviewRequest, request: Request) -> InterviewResponse:
    # Access singletons from app.state
    app_state = request.app.state.app_state
    sessions = request.app.state.interview_sessions
    # ...
```

### Lifespan Registration Pattern

```python
# Source: src/alphaswarm/web/app.py (verified)
# In lifespan():
app.state.interview_sessions = {}  # dict[str, InterviewEngine]

# In create_app():
from alphaswarm.web.routes.interview import router as interview_router
app.include_router(interview_router, prefix="/api")
```

### Vue Panel Mutual Exclusion Pattern

```typescript
// Source: src/App.vue (verified) -- existing pattern
const selectedAgentId = ref<string | null>(null)
// NEW:
const interviewAgentId = ref<string | null>(null)

// Mutual exclusion: setting one clears the other
function onOpenInterview(agentId: string) {
  selectedAgentId.value = null
  interviewAgentId.value = agentId
}

function onCloseInterview() {
  interviewAgentId.value = null
}
```

### Vue Sidebar Transition Reuse

```html
<!-- Source: src/App.vue (verified) -- existing transition -->
<Transition name="sidebar">
  <AgentSidebar v-if="selectedAgentId && !interviewAgentId"
    :agentId="selectedAgentId" @close="onCloseSidebar"
    @open-interview="onOpenInterview" />
</Transition>

<Transition name="sidebar">
  <InterviewPanel v-if="interviewAgentId"
    :agentId="interviewAgentId" @close="onCloseInterview" />
</Transition>
```

### REST Fetch Pattern from Vue

```typescript
// Source: frontend/src/components/CyclePicker.vue (verified)
const loading = ref(false)
const error = ref<string | null>(null)

async function sendMessage() {
  if (!input.value.trim() || loading.value) return
  loading.value = true
  error.value = null
  try {
    const res = await fetch(`/api/interview/${props.agentId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: input.value.trim() }),
    })
    if (!res.ok) throw new Error('request failed')
    const data = await res.json()
    // append to message history
  } catch {
    error.value = 'Failed to get response. Try again.'
  } finally {
    loading.value = false
  }
}
```

### Anti-Patterns to Avoid
- **WebSocket for interviews:** Do not use WebSocket for interview messages. REST POST per turn is simpler, matches the request-response nature of interviews, and the existing fetch pattern in Vue is well-established.
- **Blocking interview calls:** Never use synchronous HTTP calls. `InterviewEngine.ask()` is already async and calls `OllamaClient.chat()` which has built-in backoff.
- **Global interview state in StateStore:** Do not put interview state in `StateStore`. Per D-06, interview sessions live in their own `app.state.interview_sessions` dict. StateStore is for simulation/replay state broadcasting.
- **Clearing interview_sessions in wrong lifecycle:** Do not clear sessions on every snapshot broadcast. Only clear on explicit reset (new simulation start or server restart).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM conversation window management | Custom sliding window + summarization | `InterviewEngine` (already built) | Handles 10-turn window, automatic summarization of dropped pairs, system prompt construction |
| Agent context reconstruction | Manual Cypher queries | `graph_manager.read_agent_interview_context()` | Already reconstructs persona, narrative, and all 3 rounds of decisions from Neo4j |
| Retry/backoff for Ollama | Custom retry logic | `OllamaClient.chat()` with `backoff` decorator | Already handles `ResponseError`, `ConnectionError`, `httpx.ConnectError` with exponential backoff |
| CSS design tokens | Hardcoded colors/spacing | CSS custom properties from `variables.css` | All values (`--color-bg-secondary`, `--space-md`, `--sidebar-width`, etc.) already defined |
| Panel slide animation | Custom JS animation | Vue `<Transition name="sidebar">` | Already defined in App.vue with enter/leave CSS |

**Key insight:** Phase 14 already built the hard part (InterviewEngine with sliding window, summarization, and context reconstruction). This phase is purely integration plumbing.

## Common Pitfalls

### Pitfall 1: cycle_id Resolution
**What goes wrong:** `read_agent_interview_context(agent_id, cycle_id)` requires a `cycle_id` parameter, but `StateStore` does not track the current cycle_id. The endpoint cannot determine which simulation cycle to use.
**Why it happens:** The simulation flow generates `cycle_id` in `inject_seed()` and passes it through the pipeline, but `SimulationManager` does not persist it on `app.state`.
**How to avoid:** On first interview call, query `graph_manager.read_completed_cycles(limit=1)` to get the most recent completed cycle's `cycle_id`. Cache it alongside the session in the `interview_sessions` dict. The replay manager similarly tracks `cycle_id` as a property.
**Warning signs:** 503 errors or empty interview context when the endpoint cannot determine the cycle.

### Pitfall 2: Stale InterviewEngine Sessions After New Simulation
**What goes wrong:** If the user runs a new simulation, the `interview_sessions` dict still holds engines from the previous cycle. Asking Agent 01 would continue the old conversation with old context.
**Why it happens:** `interview_sessions` is initialized once in lifespan and never cleared.
**How to avoid:** Clear `interview_sessions` when a new simulation starts. The cleanest approach: `SimulationManager._run()` can clear `request.app.state.interview_sessions = {}` or the interview endpoint can compare the stored cycle_id with the latest completed cycle and invalidate stale sessions.
**Warning signs:** Interview responses reference the wrong simulation/rumor.

### Pitfall 3: OllamaClient / graph_manager Being None
**What goes wrong:** In test mode or when services are down, `app_state.ollama_client` is `None` and `app_state.graph_manager` is `None`. The interview endpoint would crash with `AttributeError`.
**Why it happens:** `create_app_state(with_ollama=False, with_neo4j=False)` used in tests.
**How to avoid:** Guard both at the top of the endpoint handler. Return 503 if either is None (same pattern as `replay.py` line 78-82 for graph_manager).
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'chat'` in test runs.

### Pitfall 4: Two Transitions With Same Name Cause Vue Warnings
**What goes wrong:** Two `<Transition name="sidebar">` wrappers in App.vue with different v-if conditions may cause Vue to issue warnings about duplicate transition nodes.
**Why it happens:** Vue expects Transition to wrap a single conditional element.
**How to avoid:** Use a single `<Transition>` wrapping both components with v-if/v-else-if, or use two Transitions with distinct names (though the same CSS classes can apply to both). The cleanest: use v-if/v-else inside a single Transition since only one panel ever shows at a time.
**Warning signs:** Console warnings about "Component inside <Transition> renders non-element root node."

### Pitfall 5: Worker Model Not Loaded After Simulation Completes
**What goes wrong:** After simulation completes, the OllamaModelManager may have already unloaded the worker model. `InterviewEngine.ask()` calls `OllamaClient.chat(model=...)` which triggers Ollama to reload the model, causing a long delay on the first interview request.
**Why it happens:** The simulation pipeline manages model loading/unloading. Post-simulation, the worker model may not be in memory.
**How to avoid:** The Ollama server handles model loading transparently -- the first call will be slow (~10-30s) but will succeed. The non-blocking loading indicator (D-11) handles UX. No code change needed, but the delay should be expected and the loading state must be visible.
**Warning signs:** First interview takes 20+ seconds (model loading), subsequent calls are fast.

### Pitfall 6: AgentSidebar Emitting to App.vue
**What goes wrong:** The new `@open-interview` event from AgentSidebar needs to propagate to App.vue, but AgentSidebar currently only emits `@close`.
**Why it happens:** New emit needs to be declared in `defineEmits` and the parent template needs to listen for it.
**How to avoid:** Add `'open-interview': [agentId: string]` to `AgentSidebar`'s `defineEmits`, emit it from the button click handler, and listen for it in `App.vue`'s template: `@open-interview="onOpenInterview"`.
**Warning signs:** Clicking the Interview button does nothing (emit silently ignored).

## Code Examples

### Backend: Interview Route (complete pattern)

```python
# Source: Pattern from src/alphaswarm/web/routes/replay.py + interview.py types
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
import structlog

from alphaswarm.interview import InterviewEngine

log = structlog.get_logger(component="web.interview")
router = APIRouter()

class InterviewRequest(BaseModel):
    message: str

class InterviewResponse(BaseModel):
    response: str

@router.post("/interview/{agent_id}", response_model=InterviewResponse)
async def interview_agent(
    agent_id: str, body: InterviewRequest, request: Request,
) -> InterviewResponse:
    app_state = request.app.state.app_state
    graph_manager = app_state.graph_manager
    ollama_client = app_state.ollama_client

    if graph_manager is None or ollama_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "services_unavailable", "message": "..."},
        )

    sessions: dict[str, InterviewEngine] = request.app.state.interview_sessions

    if agent_id not in sessions:
        # Resolve cycle_id from most recent completed cycle
        cycles = await graph_manager.read_completed_cycles(limit=1)
        if not cycles:
            raise HTTPException(status_code=404, detail={"error": "no_completed_cycle"})
        cycle_id = cycles[0]["cycle_id"]
        context = await graph_manager.read_agent_interview_context(agent_id, cycle_id)
        engine = InterviewEngine(
            context=context,
            ollama_client=ollama_client,
            model=app_state.settings.ollama.worker_model_alias,
        )
        sessions[agent_id] = engine

    engine = sessions[agent_id]
    response_text = await engine.ask(body.message)
    return InterviewResponse(response=response_text)
```

### Frontend: InterviewPanel.vue (structural skeleton)

```vue
<script setup lang="ts">
import { ref, reactive, nextTick, inject, type Ref } from 'vue'
import type { StateSnapshot } from '../types'

const props = defineProps<{ agentId: string }>()
const emit = defineEmits<{ close: [] }>()

interface ChatMessage {
  role: 'user' | 'agent'
  content: string
}

// Per D-05: Map<agentId, messages[]> persists across panel close/reopen
const allConversations = reactive(new Map<string, ChatMessage[]>())

const messages = computed(() => allConversations.get(props.agentId) || [])
const input = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return

  if (!allConversations.has(props.agentId)) {
    allConversations.set(props.agentId, [])
  }
  const history = allConversations.get(props.agentId)!
  history.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  error.value = null

  try {
    const res = await fetch(`/api/interview/${props.agentId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
    if (!res.ok) throw new Error('request failed')
    const data = await res.json()
    history.push({ role: 'agent', content: data.response })
  } catch {
    error.value = 'Failed to get response. Try again.'
  } finally {
    loading.value = false
    await nextTick()
    // auto-scroll to bottom
  }
}
</script>
```

### Frontend: AgentSidebar.vue Interview Button Addition

```vue
<!-- Added at bottom of AgentSidebar template, gated on phase === 'complete' -->
<button
  v-if="snapshot.phase === 'complete'"
  class="sidebar__interview-btn"
  @click="emit('open-interview', props.agentId)"
>
  Interview {{ agentName }}
</button>
```

### App.vue: Panel Mutual Exclusion

```vue
<!-- In template: replace current AgentSidebar Transition -->
<Transition name="sidebar">
  <AgentSidebar
    v-if="selectedAgentId && !interviewAgentId"
    :agentId="selectedAgentId"
    @close="onCloseSidebar"
    @open-interview="onOpenInterview"
  />
</Transition>

<Transition name="sidebar">
  <InterviewPanel
    v-if="interviewAgentId"
    :agentId="interviewAgentId"
    @close="onCloseInterview"
  />
</Transition>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TUI interview mode (Phase 14) | Web interview panel (Phase 35) | Phase 35 | Same InterviewEngine, different frontend |
| Per-request model loading | Ollama auto-loads on first chat call | Ollama design | First interview request slow, subsequent fast |

**No deprecated patterns:** All dependencies (FastAPI, Vue 3, Pydantic) are current. No API changes needed.

## Open Questions

1. **cycle_id on new simulation start**
   - What we know: `read_completed_cycles(limit=1)` returns the most recent cycle. If a user runs a new simulation, the most recent cycle changes.
   - What's unclear: Should the interview endpoint detect a cycle change and invalidate cached sessions? Or should we clear `interview_sessions` when a new simulation completes?
   - Recommendation: Clear `interview_sessions` dict when `SimulationManager._run()` enters its first line (new simulation starting). This is the simplest approach and matches the "both reset on server restart" behavior from D-06.

2. **Conversation state ownership**
   - What we know: D-05 says frontend keeps display history in a `Map<string, Message[]>`. D-06 says backend keeps the LLM conversation context in `InterviewEngine._history`.
   - What's unclear: If the frontend has 5 messages displayed but the backend is restarted, the frontend would try to continue but the backend engine is gone -- responses would lose context.
   - Recommendation: This is acceptable per D-06 ("both reset on server restart/page refresh"). If backend restarts, first call creates a fresh engine. Frontend messages are still visible but backend context is lost. Document this as known behavior.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (auto mode) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_web.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WEB-06-SC1 | POST /api/interview/{agent_id} returns agent response | unit (mocked engine) | `uv run pytest tests/test_web_interview.py::test_interview_endpoint_returns_response -x` | Wave 0 |
| WEB-06-SC2 | Clicking node in complete state opens interview panel | manual (browser) | N/A -- Vue component visual test | manual-only |
| WEB-06-SC3 | Multi-turn conversation: each message appends response | unit (mocked engine) | `uv run pytest tests/test_web_interview.py::test_interview_multi_turn -x` | Wave 0 |
| WEB-06-SC4 | Panel dismissible, force graph interactive behind it | manual (browser) | N/A -- Vue layout test | manual-only |
| WEB-06-SC5 | Loading indicator while LLM responds | manual (browser) | N/A -- Vue UI state test | manual-only |

### Additional Backend Tests
| Behavior | Test Type | Automated Command |
|----------|-----------|-------------------|
| 503 when graph_manager is None | unit | `uv run pytest tests/test_web_interview.py::test_interview_503_no_graph -x` |
| 503 when ollama_client is None | unit | `uv run pytest tests/test_web_interview.py::test_interview_503_no_ollama -x` |
| 404 when no completed cycles | unit | `uv run pytest tests/test_web_interview.py::test_interview_404_no_cycles -x` |
| Session reuse on second call | unit | `uv run pytest tests/test_web_interview.py::test_interview_session_reuse -x` |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_web_interview.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_web_interview.py` -- covers WEB-06 SC-1, SC-3, and error cases
- [ ] Test helper updates in `_make_test_app()` to register interview router and init `interview_sessions`

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/interview.py` -- InterviewEngine class, InterviewContext, RoundDecision types; WINDOW_SIZE = 10; `ask()` method signature verified
- `src/alphaswarm/graph.py:1032` -- `read_agent_interview_context(agent_id, cycle_id)` signature and Cypher query verified
- `src/alphaswarm/web/app.py` -- lifespan pattern, router registration pattern verified
- `src/alphaswarm/web/routes/simulation.py` -- REST endpoint pattern (request body, response model, app.state access) verified
- `src/alphaswarm/web/routes/replay.py` -- 503 guard for graph_manager, cycle query pattern verified
- `frontend/src/App.vue` -- selectedAgentId/sidebarOpen pattern, Transition name="sidebar", component structure verified
- `frontend/src/components/AgentSidebar.vue` -- inject pattern, emit pattern, sidebar CSS structure verified
- `frontend/src/components/CyclePicker.vue` -- fetch-on-open pattern, loading state management verified
- `frontend/src/components/ShockDrawer.vue` -- slide-in panel with Transition, button styling pattern verified
- `frontend/src/types.ts` -- StateSnapshot with phase field verified
- `frontend/src/assets/variables.css` -- all design tokens verified

### Secondary (MEDIUM confidence)
- `src/alphaswarm/config.py` -- `worker_model_alias` field name verified as `"alphaswarm-worker"` default
- `src/alphaswarm/ollama_client.py` -- `chat()` signature and backoff behavior verified
- `tests/test_web.py` -- `_make_test_app()` helper pattern for unit testing endpoints verified
- `tests/test_interview.py` -- Existing InterviewEngine test patterns verified

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all components already exist in the project, no new libraries
- Architecture: HIGH -- every pattern directly mirrors existing code (replay routes, sidebar components)
- Pitfalls: HIGH -- cycle_id resolution gap verified by reading StateStore source; all other pitfalls identified from code inspection

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (stable -- no external dependency changes expected)
