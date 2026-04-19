# Phase 14: Agent Interviews - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 14 adds post-simulation agent interviews to the TUI. After a simulation completes (`SimulationPhase.COMPLETE`), the user clicks any `AgentCell` in the 10x10 grid to open an interview panel where they can conduct a live multi-turn conversation with that agent. The agent answers in character using the worker LLM with its original system prompt restored and full decision context injected. Interview sessions are self-contained — no new graph writes, no simulation state changes, no new panels added to the main dashboard. CLI interview subcommand is explicitly out of scope.

</domain>

<decisions>
## Implementation Decisions

### TUI Panel Layout
- **D-01:** Full-screen Textual `Screen` overlay, pushed on top of the simulation dashboard using `app.push_screen()`. Same pattern as `RumorInputScreen` (tui.py:356). Agent ID displayed in a header bar. Scrollable Q&A transcript area. Input box at the bottom. `Escape` or a `[Exit Interview]` button pops the screen and returns to the grid exactly as left.
- **D-02:** `AgentCell.on_click` is gated on `SimulationPhase.COMPLETE` — clicking during simulation does nothing (or shows a brief "Simulation in progress" status message). Only active when phase is `COMPLETE`.
- **D-03:** No CLI `interview` subcommand. TUI click is the only entry point. The interview engine (context reconstruction + LLM loop) is implemented as a standalone module but exposed only through the TUI.

### Agent Context Reconstruction
- **D-04:** Hybrid context model for the agent's interview system prompt:
  - **Layer 1 (system prompt):** Agent's original `persona.system_prompt` (unchanged, restores full in-character identity including bracket, modifier, and JSON output instructions stripped — see note below)
  - **Layer 2 (context block):** `decision_narrative` property from the Agent node (pre-computed Phase 11 summary of the 3-round arc) — narrative prose summary
  - **Layer 3 (raw decisions):** The 3 `Decision` nodes (round, signal, confidence, sentiment, rationale text) — structured block the agent can cite precisely
  - Combined into a single context injection block appended to the system prompt before the first user message.
- **D-05:** The interview system prompt strips `JSON_OUTPUT_INSTRUCTIONS` from the original persona system_prompt before use — interviews are conversational prose, not JSON-structured decisions. All other persona content (bracket description, modifier, risk profile framing) is preserved.
- **D-06:** Context is reconstructed from Neo4j at interview start via a new `read_agent_interview_context(agent_id, cycle_id)` method on `GraphStateManager`. Returns: agent persona fields, `decision_narrative`, and the 3 Decision nodes (signal, confidence, rationale per round). `RationaleEpisode.peer_context_received` is NOT included in the default context (would bloat the prompt significantly) — it's available if the agent references peer influences.
- **D-07:** `cycle_id` for the most recent completed simulation is retrieved from `AppState` or `StateStore` (already tracked). No user input needed to identify the cycle.

### Sliding Window Conversation History
- **D-08:** 10-turn window (10 user+agent message pairs = 20 messages). System prompt + context block always kept. When the window exceeds 10 pairs, drop the oldest pair and generate a 1-sentence summary via the worker model.
- **D-09:** Summary injection format: a `{"role": "system", "content": "[Earlier: {summary}]"}` message prepended to the remaining history after the drop. This keeps the agent aware of earlier discussion without blowing the context window.
- **D-10:** Summary generation uses the worker model (already loaded for the interview session). No orchestrator model involvement. Summary prompt instructs: "In one sentence, summarize what the user asked and what you said in the following exchange: [dropped pair]". Synchronous within the interview loop (no governor needed for a single call).
- **D-11:** `AsyncGenerator`-based or simple `async for` streaming is NOT required for interview responses — full response per turn is acceptable. Token streaming is a future enhancement.

### Worker Model Lifecycle
- **D-12:** Interview mode assumes the worker model is available (loads if not loaded). After simulation completes, the worker model is typically still warm. If the app is restarted and no simulation was run, the interview triggers a worker model load — expected behavior, ~5-10s delay acceptable.
- **D-13:** The interview loop does NOT use `agent_worker()` context manager (which is coupled to the simulation governor). Instead it uses `OllamaClient.chat()` directly with the worker model alias, using a dedicated interview session that is NOT resource-governed (interviews are sequential single-user interactions, not batch inference).

### Claude's Discretion
- Exact `InterviewScreen` widget layout (header, scroll area proportions, input styling) within the clean minimalist aesthetic
- Whether to use `RichLog` or `ScrollableContainer` with `Static` widgets for the Q&A transcript
- `read_agent_interview_context()` Cypher query design (single query vs multi-step)
- How to extract `cycle_id` from existing `AppState` / `StateStore`
- How to strip `JSON_OUTPUT_INSTRUCTIONS` from the persona system prompt (substring match vs stored flag)
- Error handling if Neo4j is unavailable when interview is launched (show error message in panel)

</decisions>

<specifics>
## Specific Ideas

- The interview screen should feel like the existing `RumorInputScreen` — clean, focused, minimal chrome. One input line, scrollable history above it.
- The agent should answer naturally in the first person ("I chose to BUY because...") rather than reproducing JSON structure.
- On first open, the interview screen could display a brief intro line: "[quants_01] is ready to discuss their simulation decisions." before the user's first message.
- `JSON_OUTPUT_INSTRUCTIONS` stripping is important — the original system prompt ends with structured output instructions that would make the agent respond in JSON format, which is wrong for conversational interview mode.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — INT-01 (context reconstruction from Neo4j), INT-02 (conversational interview loop, worker LLM in character), INT-03 (TUI interview mode, click agent cell)
- `.planning/ROADMAP.md` — Phase 14 success criteria (4 criteria including sliding window mandate), "UI hint: yes"

### TUI Implementation (Primary)
- `src/alphaswarm/tui.py` — `AgentCell` (line 72, widget to add `on_click` to), `RumorInputScreen` (line 356, Screen overlay pattern to replicate for `InterviewScreen`), `AlphaSwarmApp` (line 450, `BINDINGS` and `push_screen` entry point), `compute_cell_color` (line 41), `SimulationPhase` usage
- `src/alphaswarm/app.py` — `AppState` dataclass (line 24, contains `cycle_id` and graph reference), `create_app_state()` (line 43)

### Graph Layer (Primary)
- `src/alphaswarm/graph.py` — `GraphStateManager` (line 77, new `read_agent_interview_context()` method goes here), `write_decision_narratives()` (line 811, confirms `decision_narrative` property on Agent nodes), `write_rationale_episodes()` (line 677, confirms `RationaleEpisode` schema with `peer_context_received`)
- `src/alphaswarm/graph.py` — `read_peer_decisions()` (line 605, reference for async Cypher read method pattern)

### Worker LLM (Primary)
- `src/alphaswarm/worker.py` — `AgentWorker` (line 46), `agent_worker()` context manager (line 123), `WorkerPersonaConfig` (line 30) — D-13 explicitly opts OUT of `agent_worker()` for interviews; read to understand what NOT to use and why
- `src/alphaswarm/ollama_client.py` — Direct `OllamaClient.chat()` usage pattern for interview (bypass governor)

### Prior Phase Decisions
- `.planning/phases/11-live-graph-memory/11-CONTEXT.md` — D-10 (`decision_narrative` on Agent nodes, post-simulation narrative generation), D-05 (`peer_context_received` on RationaleEpisode)
- `.planning/phases/09-tui-core-dashboard/09-CONTEXT.md` — TUI aesthetic and component patterns
- `src/alphaswarm/config.py` — `JSON_OUTPUT_INSTRUCTIONS` constant (line 89, must be stripped from interview system prompt per D-05), `generate_personas()` (line 441, shows how system_prompt is assembled)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RumorInputScreen` (tui.py:356) — Full-screen Screen overlay pattern with `BINDINGS = [("escape", "quit")]`, Input widget, `on_mount`, and `on_input_submitted`. Direct structural template for `InterviewScreen`.
- `AlphaSwarmApp.push_screen()` — Textual's built-in screen stack. `InterviewScreen` gets pushed from `AgentCell.on_click` handler, popped on exit.
- `RationaleSidebar` (tui.py:179) — `RichLog`-style scrollable text widget, relevant for Q&A transcript rendering.
- `AgentCell` (tui.py:72) — Currently has `render()` and `update_color()` but no click handler. Phase 14 adds `on_click` gated on `SimulationPhase.COMPLETE`.

### Established Patterns
- Async graph reads: `read_peer_decisions()` (graph.py:605) — `async def`, takes `session` from `AsyncSession`, returns typed dataclass list. New `read_agent_interview_context()` follows same pattern.
- Screen-level async work: `_run_simulation()` (tui.py:553) runs as a `Worker` thread. Interview LLM calls should similarly run in a non-blocking worker to keep the TUI responsive.
- `structlog` component-scoped logger: all source files use `logger = structlog.get_logger(component="X")` — interview module should use `component="interview"`.

### Integration Points
- `AgentCell.on_click` → check `SimulationPhase` via `AppState.state_store.snapshot().phase` → if COMPLETE, call `app.push_screen(InterviewScreen(agent_id, cycle_id, graph_manager, ollama_client))`
- `GraphStateManager` gains new method: `read_agent_interview_context(agent_id: str, cycle_id: str) -> InterviewContext`
- `InterviewContext` dataclass (new type): `agent_id`, `persona_system_prompt`, `decision_narrative`, `decisions: list[RoundDecision]`
- `RoundDecision` dataclass (new type): `round: int`, `signal: SignalType`, `confidence: float`, `sentiment: float`, `rationale: str`

</code_context>

<deferred>
## Deferred Ideas

- CLI `interview` subcommand (`uv run python -m alphaswarm interview <agent_id> --cycle <cycle_id>`) — explicitly out of scope, can be added later
- Streaming token-by-token interview responses — future enhancement
- Multi-agent simultaneous interviews — out of scope
- Displaying `peer_context_received` on demand ("what did your peers say?") — could be a future follow-up question feature
- Interview transcript export to file — future enhancement

</deferred>

---

*Phase: 14-agent-interviews*
*Context gathered: 2026-04-01*
