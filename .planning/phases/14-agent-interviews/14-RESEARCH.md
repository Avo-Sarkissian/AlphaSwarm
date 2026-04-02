# Phase 14: Agent Interviews - Research

**Researched:** 2026-04-02
**Domain:** Post-simulation interactive agent interviews via TUI (Textual Screen overlay + Ollama chat + Neo4j context reconstruction)
**Confidence:** HIGH

## Summary

Phase 14 adds a post-simulation interview feature where users click any agent in the 10x10 grid after simulation completes, opening a full-screen conversational Q&A panel. The agent answers in character using the worker LLM with its original system prompt (minus JSON output instructions) and full decision context injected from Neo4j.

The implementation requires three distinct pieces: (1) a Neo4j read method on `GraphStateManager` that reconstructs an agent's full interview context (persona, decision_narrative, 3 rounds of decisions), (2) a standalone interview engine module that manages the multi-turn conversation with sliding window history management and summary generation, and (3) a Textual `Screen` overlay (`InterviewScreen`) with `RichLog` for the Q&A transcript and `Input` for user messages, pushed via `app.push_screen()` from `AgentCell.on_click`.

**Primary recommendation:** Implement as three layers -- graph read method, interview engine module, TUI screen widget -- with the engine as a dependency-injected class that the TUI drives. Use `@work` decorator or `run_worker` for LLM calls to keep the TUI responsive. The critical gap to address is that `cycle_id` is not currently stored on `StateStore` or `AppState` post-simulation; it must be captured from `SimulationResult` in the TUI worker callback.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Full-screen Textual `Screen` overlay via `app.push_screen()`. Same pattern as `RumorInputScreen`. Agent ID in header bar, scrollable Q&A transcript, input box at bottom. Escape or `[Exit Interview]` button pops the screen.
- **D-02:** `AgentCell.on_click` gated on `SimulationPhase.COMPLETE` -- clicking during simulation does nothing (or shows brief status message).
- **D-03:** No CLI interview subcommand. TUI click is the only entry point. Interview engine is a standalone module exposed only through the TUI.
- **D-04:** Hybrid context model with 3 layers: (1) persona system_prompt, (2) decision_narrative property from Agent node, (3) raw Decision nodes with round/signal/confidence/sentiment/rationale.
- **D-05:** Strip `JSON_OUTPUT_INSTRUCTIONS` from persona system_prompt before interview use. Interviews are conversational prose, not JSON.
- **D-06:** New `read_agent_interview_context(agent_id, cycle_id)` method on `GraphStateManager`. Returns persona fields, decision_narrative, and 3 Decision nodes. `peer_context_received` NOT included by default.
- **D-07:** `cycle_id` retrieved from `AppState` or `StateStore` (already tracked). No user input needed.
- **D-08:** 10-turn sliding window (10 user+agent message pairs = 20 messages). System prompt + context always kept. Oldest pair dropped with 1-sentence summary.
- **D-09:** Summary injection: `{"role": "system", "content": "[Earlier: {summary}]"}` prepended to remaining history after drop.
- **D-10:** Summary generation uses worker model. Synchronous within interview loop.
- **D-11:** No streaming -- full response per turn is acceptable.
- **D-12:** Worker model assumed available. Loads if not loaded (~5-10s delay acceptable).
- **D-13:** Interview uses `OllamaClient.chat()` directly (NOT `agent_worker()` context manager). No governor involvement. Sequential single-user interaction.

### Claude's Discretion
- Exact `InterviewScreen` widget layout (header, scroll area proportions, input styling) within clean minimalist aesthetic
- Whether to use `RichLog` or `ScrollableContainer` with `Static` widgets for Q&A transcript
- `read_agent_interview_context()` Cypher query design (single query vs multi-step)
- How to extract `cycle_id` from existing `AppState` / `StateStore`
- How to strip `JSON_OUTPUT_INSTRUCTIONS` (substring match vs stored flag)
- Error handling if Neo4j unavailable when interview launched

### Deferred Ideas (OUT OF SCOPE)
- CLI interview subcommand
- Streaming token-by-token interview responses
- Multi-agent simultaneous interviews
- Displaying `peer_context_received` on demand
- Interview transcript export to file
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INT-01 | Agent context reconstruction from Neo4j -- full persona, all 3 rounds of decisions, peer influences received, rationale history | Graph read method pattern from `read_peer_decisions()` (graph.py:605); Cypher query design for Agent+Decision+narrative traversal; `InterviewContext` dataclass design |
| INT-02 | Conversational interview loop using worker LLM with agent's original system prompt restored, answering in character | `OllamaClient.chat()` direct usage (bypassing governor); sliding window history management; `JSON_OUTPUT_INSTRUCTIONS` stripping from `config.py:95`; worker model lifecycle from D-12 |
| INT-03 | TUI interview mode -- click any agent in grid post-simulation to open interactive Q&A panel | `RumorInputScreen` pattern (tui.py:356) for Screen overlay; `AgentCell.on_click` handler gated on `SimulationPhase.COMPLETE`; `RichLog` widget for scrollable transcript; `@work` decorator for non-blocking LLM calls |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
- **Local First:** All inference local via Ollama. No cloud APIs. Max 2 models loaded simultaneously.
- **Memory Safety:** Monitor RAM via `psutil`. Dynamic throttling at 90% utilization.
- **Runtime:** Python 3.11+ (strict typing), `uv` (package manager), `pytest-asyncio`.
- **Inference:** `ollama-python` (>=0.6.1) via `OllamaClient` wrapper. Worker model: `qwen3.5:9b`.
- **State/Memory:** Neo4j Community (Docker) via `neo4j` async driver.
- **UI:** `textual` (>=8.1.1) for clean, minimalist terminal dashboard.
- **Validation/Config:** `pydantic`, `pydantic-settings`.
- **Logging:** `structlog` with component-scoped loggers.
- **GSD Workflow:** All work through GSD commands.

## Standard Stack

### Core (already installed, no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 8.1.1 | TUI framework for InterviewScreen overlay | Already used for dashboard; Screen push/pop is built-in |
| ollama | >=0.6.1 | Direct `OllamaClient.chat()` for interview LLM calls | Already used throughout; chat method supports multi-turn message lists |
| neo4j | >=5.28,<6.0 | Async Cypher reads for agent context reconstruction | Already used; async driver pattern established |
| pydantic | >=2.12.5 | `InterviewContext` data validation | Already used for all domain types |
| structlog | >=25.5.0 | Interview module logging (`component="interview"`) | Already used project-wide |

### Supporting (no new installs)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | (bundled with textual) | `Text` and `Panel` formatting for Q&A transcript rendering in `RichLog` | Formatting agent/user messages with Rich markup |

**Installation:** No new dependencies required. All libraries already in `pyproject.toml`.

## Architecture Patterns

### Recommended Module Structure
```
src/alphaswarm/
    interview.py       # NEW: InterviewEngine class + InterviewContext/RoundDecision dataclasses
    graph.py           # EXTEND: read_agent_interview_context() method
    tui.py             # EXTEND: InterviewScreen class + AgentCell.on_click handler
    config.py          # READ: JSON_OUTPUT_INSTRUCTIONS constant for stripping
    state.py           # EXTEND: cycle_id storage (or capture from SimulationResult in TUI)
```

### Pattern 1: Interview Engine (Standalone Module)
**What:** A class that manages the multi-turn conversation state, including message history, sliding window, summary generation, and LLM calls via `OllamaClient.chat()`.
**When to use:** Always -- this is the core of INT-02.
**Example:**
```python
# Source: Established project pattern from worker.py + OllamaClient.chat() API
@dataclass(frozen=True)
class InterviewContext:
    """Agent context reconstructed from Neo4j for interview mode."""
    agent_id: str
    agent_name: str
    bracket: str
    interview_system_prompt: str  # persona system_prompt with JSON_OUTPUT_INSTRUCTIONS stripped
    decision_narrative: str       # pre-computed narrative from Agent node
    decisions: list[RoundDecision]  # 3 rounds of structured decisions

@dataclass(frozen=True)
class RoundDecision:
    """A single round's decision data from Neo4j."""
    round_num: int
    signal: str
    confidence: float
    sentiment: float
    rationale: str

class InterviewEngine:
    """Manages multi-turn agent interview conversation."""

    WINDOW_SIZE = 10  # max user+agent pairs

    def __init__(
        self,
        context: InterviewContext,
        ollama_client: OllamaClient,
        model: str,
    ) -> None:
        self._context = context
        self._client = ollama_client
        self._model = model
        self._history: list[dict[str, str]] = []
        self._summary: str | None = None

    async def ask(self, user_message: str) -> str:
        """Send user message, get agent response, manage sliding window."""
        self._history.append({"role": "user", "content": user_message})

        # Build message list: system + context + optional summary + history
        messages = self._build_messages()

        response = await self._client.chat(
            model=self._model,
            messages=messages,
            think=False,
        )
        assistant_content = response.message.content or ""
        self._history.append({"role": "assistant", "content": assistant_content})

        # Trim if over window
        await self._trim_window()

        return assistant_content
```

### Pattern 2: Textual Screen Overlay (InterviewScreen)
**What:** Full-screen `Screen` class pushed on top of the dashboard via `app.push_screen()`. Contains `RichLog` for Q&A history and `Input` for user messages.
**When to use:** When user clicks an agent cell post-simulation.
**Example:**
```python
# Source: Existing RumorInputScreen pattern (tui.py:356) + Textual RichLog docs
class InterviewScreen(Screen[None]):
    """Full-screen agent interview overlay."""

    BINDINGS = [("escape", "exit_interview", "Exit")]

    def __init__(
        self,
        agent_id: str,
        context: InterviewContext,
        engine: InterviewEngine,
    ) -> None:
        super().__init__()
        self._agent_id = agent_id
        self._context = context
        self._engine = engine

    def compose(self) -> ComposeResult:
        yield Static(f"Interview: {self._context.agent_name}", id="interview-header")
        yield RichLog(id="transcript", markup=True, wrap=True, auto_scroll=True)
        yield Input(placeholder="Ask a question...", id="interview-input")

    @work(exclusive=True)
    async def _send_message(self, user_message: str) -> None:
        """Worker: send message to LLM, write response to transcript."""
        transcript = self.query_one("#transcript", RichLog)
        transcript.write(f"[#4FC3F7]You:[/] {user_message}")
        response = await self._engine.ask(user_message)
        transcript.write(f"[#66BB6A]{self._context.agent_name}:[/] {response}")
        self.query_one("#interview-input", Input).focus()
```

### Pattern 3: Non-Blocking LLM Calls in TUI
**What:** Use Textual's `@work(exclusive=True)` decorator or `run_worker()` to run LLM inference without freezing the UI event loop.
**When to use:** Every interview turn where `OllamaClient.chat()` is called (typically 2-10 seconds per response).
**Critical detail:** Per CLAUDE.md, 100% async is required. The `@work` decorator creates a Textual Worker that runs the coroutine concurrently with the UI event loop. `exclusive=True` ensures sequential message processing (no race conditions from rapid typing).

### Anti-Patterns to Avoid
- **Awaiting LLM calls in on_input_submitted:** This would freeze the entire TUI for 2-10 seconds per response. Always offload to a Worker.
- **Using `agent_worker()` context manager:** Per D-13, this is coupled to the simulation governor. Interviews are sequential single-user interactions; governor overhead is unnecessary and would interfere with post-simulation state.
- **Building message history from scratch each turn:** The sliding window + summary approach (D-08/D-09) is required to prevent context overflow. The system prompt + context block alone is ~1000-2000 tokens; 20+ turns of conversation would easily exceed the model's context window.
- **Forgetting to strip JSON_OUTPUT_INSTRUCTIONS:** The original persona system_prompt ends with structured JSON output instructions. Without stripping, the agent would respond in JSON format, breaking the conversational interview experience.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scrollable chat transcript | Custom Widget with manual scroll management | `RichLog(markup=True, wrap=True, auto_scroll=True)` | Built-in auto-scroll, Rich markup support, no manual scroll position tracking needed |
| Screen overlay lifecycle | Manual widget show/hide + state tracking | `app.push_screen()` / `screen.dismiss()` | Textual handles screen stack, focus management, key binding isolation |
| Non-blocking LLM calls | Manual asyncio.Task creation + UI callbacks | `@work(exclusive=True)` decorator | Handles cancellation, state tracking, exclusive serialization built-in |
| Multi-turn conversation state | Ad-hoc message list management | Dedicated `InterviewEngine` class with `_history` + `_trim_window()` | Encapsulates sliding window logic, summary generation, and system prompt assembly |

**Key insight:** Textual provides `RichLog`, `Screen`, and `Worker` primitives that match exactly the needs of a chat-style interview panel. The only custom logic needed is the interview engine (conversation state + sliding window) and the Neo4j context reconstruction query.

## Common Pitfalls

### Pitfall 1: cycle_id Not Available Post-Simulation
**What goes wrong:** `cycle_id` is returned as part of `SimulationResult` from `run_simulation()`, but the TUI's `_run_simulation()` Worker method (tui.py:553) does not capture or store it. When the user clicks an agent for interview, `cycle_id` is unavailable.
**Why it happens:** `cycle_id` was not needed by the TUI previously -- it's a graph-layer concept. The TUI Worker's result is not accessed after simulation completes.
**How to avoid:** Store `cycle_id` on `AlphaSwarmApp` or `AppState` after simulation completes. The cleanest approach: modify `_run_simulation()` to capture the `SimulationResult` and store `self._cycle_id = result.cycle_id`. Alternatively, add `cycle_id` as an optional field on `StateStore` and set it during simulation.
**Warning signs:** `AttributeError` or `None` when trying to pass `cycle_id` to `read_agent_interview_context()`.

### Pitfall 2: JSON_OUTPUT_INSTRUCTIONS Stripping Edge Cases
**What goes wrong:** Simple `str.replace(JSON_OUTPUT_INSTRUCTIONS, "")` might fail if the system prompt has been modified by Phase 13 modifiers or if there are whitespace differences.
**Why it happens:** `JSON_OUTPUT_INSTRUCTIONS` is appended as the last element in `generate_personas()` (config.py:628). The exact string is known and stable. However, the `system_prompt` stored on `AgentPersona` is the fully assembled prompt.
**How to avoid:** Use exact string matching via `system_prompt.replace(JSON_OUTPUT_INSTRUCTIONS, "")`. The constant is imported from `config.py`. This is reliable because the constant is appended verbatim in `generate_personas()`. Verify stripping succeeded (e.g., assert the prompt no longer contains `"Respond ONLY with a JSON object"`).
**Warning signs:** Agent responds in JSON format during interviews instead of conversational prose.

### Pitfall 3: Worker Model Not Loaded Post-Simulation
**What goes wrong:** After simulation completes, `_run_simulation()` (simulation.py:1100) calls `model_manager.unload_model(worker_alias)` in the `finally` block. The worker model is NOT warm when the user clicks for an interview.
**Why it happens:** The simulation lifecycle explicitly unloads the worker model to free memory after the 3-round cascade completes.
**How to avoid:** Per D-12, the interview triggers a worker model load if not loaded. Use `model_manager.load_model(worker_alias)` at interview start. The ~5-10s delay is acceptable (show "Loading model..." in the transcript). Alternatively, check `model_manager.current_model` before starting.
**Warning signs:** First interview message takes 15+ seconds (model load time + inference time) with no UI feedback. User thinks the app is frozen.

### Pitfall 4: Blocking the TUI Event Loop During Interview
**What goes wrong:** If `OllamaClient.chat()` is awaited directly in an `on_input_submitted` handler, the entire TUI freezes for 2-10 seconds per response.
**Why it happens:** Textual's message handlers run on the main event loop. A long-running await blocks all UI updates, input handling, and rendering.
**How to avoid:** Use `@work(exclusive=True)` on the method that calls `OllamaClient.chat()`. This runs the coroutine as a Textual Worker, keeping the UI responsive. Show a "Thinking..." indicator in the transcript while waiting.
**Warning signs:** TUI becomes unresponsive after sending an interview message; no cursor, no key responses until the LLM returns.

### Pitfall 5: Context Window Overflow Without Sliding Window
**What goes wrong:** Each interview turn appends ~100-500 tokens (user message + agent response). The system prompt + context block is ~1000-2000 tokens. After 15-20 turns, the total exceeds the model's context window (8192 tokens for qwen3.5:9b default, or custom Modelfile setting).
**Why it happens:** Accumulating full conversation history without trimming.
**How to avoid:** Implement the sliding window per D-08: keep 10 most recent pairs, summarize dropped pairs per D-09/D-10. The system prompt + context block is always preserved. Ensure summary generation uses the worker model (already loaded).
**Warning signs:** Model responses become incoherent, repetitive, or truncated after many turns. Ollama may also return errors or very slow responses.

### Pitfall 6: Race Condition on AgentCell Click During Simulation
**What goes wrong:** If `on_click` is not properly gated, clicking an agent during an active simulation could attempt to open an interview with incomplete data (no decision_narrative, incomplete decisions).
**Why it happens:** `SimulationPhase` transitions happen asynchronously via `StateStore`.
**How to avoid:** Per D-02, gate `on_click` on `SimulationPhase.COMPLETE` by reading the current snapshot phase. Only push `InterviewScreen` when phase is COMPLETE. Show a brief notification ("Simulation in progress") otherwise.
**Warning signs:** Neo4j query returns null decision_narrative or fewer than 3 Decision nodes.

## Code Examples

Verified patterns from the existing codebase:

### Context Reconstruction Cypher Query
```python
# Source: Established pattern from read_peer_decisions() (graph.py:605)
# and write_decision_narratives() (graph.py:811)
#
# Single Cypher query fetching Agent properties + 3 Decision nodes for a cycle:
"""
MATCH (a:Agent {id: $agent_id})
OPTIONAL MATCH (a)-[:MADE]->(d:Decision)
WHERE d.cycle_id = $cycle_id
RETURN a.id AS agent_id,
       a.name AS name,
       a.bracket AS bracket,
       a.decision_narrative AS decision_narrative,
       d.round AS round_num,
       d.signal AS signal,
       d.confidence AS confidence,
       d.sentiment AS sentiment,
       d.rationale AS rationale
ORDER BY d.round
"""
# Returns 3 rows (one per Decision round) with Agent fields repeated.
# First row provides Agent-level data; all rows provide Decision data.
```

### System Prompt Stripping
```python
# Source: config.py:95 (JSON_OUTPUT_INSTRUCTIONS constant) and
# config.py:628 (generate_personas assembly)
from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS

def _strip_json_instructions(system_prompt: str) -> str:
    """Remove JSON output instructions from persona system prompt for interview mode."""
    return system_prompt.replace(JSON_OUTPUT_INSTRUCTIONS, "").rstrip()
```

### Sliding Window Message Assembly
```python
# Source: D-08/D-09 from CONTEXT.md, ollama-python chat API
def _build_messages(self) -> list[dict[str, str]]:
    """Assemble message list for OllamaClient.chat()."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": self._system_prompt},
    ]
    # Inject context block (narrative + decisions)
    messages.append({"role": "system", "content": self._context_block})
    # Inject summary of earlier conversation if present
    if self._summary:
        messages.append({"role": "system", "content": f"[Earlier: {self._summary}]"})
    # Append recent conversation history (within window)
    messages.extend(self._history)
    return messages
```

### AgentCell Click Handler
```python
# Source: Existing AgentCell (tui.py:72), SimulationPhase check pattern
from textual.events import Click

class AgentCell(Widget):
    # ... existing code ...

    def on_click(self, event: Click) -> None:
        """Open interview for this agent if simulation is complete."""
        app = self.app
        if not isinstance(app, AlphaSwarmApp):
            return
        snapshot = app.app_state.state_store.snapshot()
        if snapshot.phase != SimulationPhase.COMPLETE:
            app.notify("Simulation in progress", severity="warning")
            return
        # Push interview screen
        app.action_open_interview(self.agent_id)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Textual Screen[str] for simple returns | Screen[None] for fire-and-forget overlays | Textual 0.40+ | InterviewScreen uses Screen[None] since it doesn't return a value |
| Manual scroll tracking in chat UIs | RichLog with auto_scroll=True | Textual 0.44+ | Eliminates custom scroll management for interview transcript |
| Thread workers for blocking I/O | Async workers via @work for coroutines | Textual 0.30+ | LLM calls via OllamaClient are async; use @work not thread=True |

**Deprecated/outdated:**
- `Log` widget: simpler but lacks Rich markup support; `RichLog` is the correct choice for styled chat transcripts
- `ScrollableContainer` with manual `Static` mounting: works but `RichLog.write()` is more efficient for append-only chat patterns

## Open Questions

1. **cycle_id Storage Location**
   - What we know: `cycle_id` is returned in `SimulationResult` from `run_simulation()`. The TUI's `_run_simulation()` does not capture it. CONTEXT.md D-07 says "retrieved from `AppState` or `StateStore` (already tracked)" -- but inspection shows it is NOT currently tracked on either.
   - What's unclear: Whether to add `cycle_id` to `StateStore` (set during simulation) or capture it in `AlphaSwarmApp` from the Worker result.
   - Recommendation: Store `cycle_id` on `AlphaSwarmApp` instance after `_run_simulation()` completes. This is simpler than modifying `StateStore` (which is the simulation-TUI bridge, not a post-simulation state container). Capture it by modifying `_run_simulation()` to store the `SimulationResult.cycle_id` on `self`.

2. **RichLog vs ScrollableContainer for Transcript**
   - What we know: `RichLog` supports `write()` with auto-scroll and Rich markup. `ScrollableContainer` + `Static` widgets allows more per-message styling but requires manual mount/scroll.
   - What's unclear: Whether `RichLog` formatting is rich enough for distinct user/agent message styling.
   - Recommendation: Use `RichLog(markup=True, wrap=True)`. Rich markup supports `[color]text[/]` patterns for user vs agent differentiation. This matches the project's existing `RationaleSidebar` approach (rich.text.Text rendering). The append-only write pattern is a natural fit for chat transcripts.

3. **Worker Model Load Timing**
   - What we know: Worker model is unloaded after simulation (simulation.py:1100). Interview needs it loaded. D-12 accepts 5-10s delay.
   - What's unclear: Whether to pre-load at interview screen mount or lazy-load on first message.
   - Recommendation: Load on `InterviewScreen.on_mount()` via a Worker. Show "Loading agent context..." message in transcript. This provides user feedback and overlaps model load time with context reconstruction from Neo4j.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Neo4j (Docker) | Context reconstruction (INT-01) | Assumed (used in prior phases) | 5.x | Show error in interview panel |
| Ollama server | LLM inference (INT-02) | Assumed (used in prior phases) | Local | Show error in interview panel |
| Worker model (qwen3.5:9b) | Interview responses | Available (may need load) | via Modelfile | Load on demand per D-12 |

**Missing dependencies with no fallback:** None -- all dependencies are already required by the simulation engine.

**Missing dependencies with fallback:**
- Worker model not loaded post-simulation: Load on demand with "Loading model..." feedback (D-12).
- Neo4j connection lost post-simulation: Show error message in interview panel, allow exit back to dashboard.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode = "auto") |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_interview.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INT-01 | read_agent_interview_context returns InterviewContext with persona, narrative, 3 decisions | unit (mock Neo4j) | `uv run pytest tests/test_interview.py::test_read_interview_context -x` | Wave 0 |
| INT-01 | InterviewContext dataclass fields correct types | unit | `uv run pytest tests/test_interview.py::test_interview_context_fields -x` | Wave 0 |
| INT-01 | Cypher query handles missing decision_narrative gracefully | unit | `uv run pytest tests/test_interview.py::test_missing_narrative -x` | Wave 0 |
| INT-02 | InterviewEngine.ask() returns conversational response (mock OllamaClient) | unit | `uv run pytest tests/test_interview.py::test_engine_ask -x` | Wave 0 |
| INT-02 | JSON_OUTPUT_INSTRUCTIONS stripped from system prompt | unit | `uv run pytest tests/test_interview.py::test_strip_json_instructions -x` | Wave 0 |
| INT-02 | Sliding window trims at 10 pairs and generates summary | unit | `uv run pytest tests/test_interview.py::test_sliding_window_trim -x` | Wave 0 |
| INT-02 | System prompt + context block always in message list | unit | `uv run pytest tests/test_interview.py::test_message_assembly -x` | Wave 0 |
| INT-03 | AgentCell.on_click gated on SimulationPhase.COMPLETE | unit (headless TUI) | `uv run pytest tests/test_tui.py::test_agent_cell_click_gated -x` | Wave 0 |
| INT-03 | InterviewScreen composes with RichLog + Input widgets | unit (headless TUI) | `uv run pytest tests/test_tui.py::test_interview_screen_compose -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_interview.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_interview.py` -- covers INT-01 (context reconstruction), INT-02 (engine, sliding window, prompt stripping)
- [ ] `tests/test_tui.py` additions -- covers INT-03 (click gating, screen compose)
- [ ] Framework install: already configured -- no gaps

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `tui.py` (AgentCell, RumorInputScreen, AlphaSwarmApp), `graph.py` (GraphStateManager, read_peer_decisions pattern), `config.py` (JSON_OUTPUT_INSTRUCTIONS, generate_personas), `simulation.py` (SimulationResult, cycle_id flow, worker model lifecycle), `ollama_client.py` (OllamaClient.chat API), `worker.py` (agent_worker pattern to avoid), `state.py` (StateStore, StateSnapshot), `app.py` (AppState), `types.py` (SimulationPhase, AgentPersona)
- [Textual Screens Guide](https://textual.textualize.io/guide/screens/) -- push_screen, dismiss, Screen[T], ModalScreen
- [Textual RichLog Widget](https://textual.textualize.io/widgets/rich_log/) -- write(), auto_scroll, markup support
- [Textual Workers Guide](https://textual.textualize.io/guide/workers/) -- @work decorator, run_worker, exclusive mode

### Secondary (MEDIUM confidence)
- [Textual Chat UI Pattern (Medium)](https://oneryalcin.medium.com/building-a-responsive-textual-chat-ui-with-long-running-processes-c0c53cd36224) -- Worker + RichLog chat architecture pattern
- [ollama-python GitHub](https://github.com/ollama/ollama-python) -- AsyncClient.chat() multi-turn message format

### Tertiary (LOW confidence)
- None -- all findings verified against codebase and official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already installed and in use; no new dependencies
- Architecture: HIGH - Patterns (Screen overlay, RichLog, Worker) directly map to existing codebase patterns (RumorInputScreen, RationaleSidebar); all integration points verified via code inspection
- Pitfalls: HIGH - Identified through direct codebase inspection (cycle_id gap verified, worker model unload confirmed, JSON_OUTPUT_INSTRUCTIONS constant located)

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable -- all dependencies pinned, Textual API stable at 8.1.1)
