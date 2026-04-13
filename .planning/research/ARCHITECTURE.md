# Architecture Research: v2.0 Engine Depth

**Domain:** Local-first multi-agent LLM financial simulation engine (feature expansion)
**Researched:** 2026-03-31
**Confidence:** HIGH

This document focuses exclusively on the architectural integration of five new v2.0 features into the existing AlphaSwarm codebase. It maps new components, identifies modification points in existing code, defines data flows, and recommends a dependency-aware build order.

## Existing Architecture Baseline

The v1 architecture is a pipeline-with-feedback-loop across five subsystems:

```
CLI/TUI Entry
    |
    v
AppState (DI container: settings, governor, state_store, ollama_client, model_manager, graph_manager)
    |
    v
SeedInjector (inject_seed) --> Orchestrator LLM --> Neo4j (Cycle + Entity nodes)
    |
    v
SimulationEngine (run_simulation) --> 3x dispatch_wave() --> Neo4j (Decision + INFLUENCED_BY)
    |                                       |
    v                                       v
StateStore (mutable) <--- per-agent writes  ResourceGovernor (TokenPool, 5-state machine)
    |
    v (200ms poll)
TUI (snapshot-based rendering)
```

**Key integration constraints from existing code:**
- `AppState` is the sole DI container. All new components MUST be wirable through it.
- `StateStore.snapshot()` is the only TUI data path. New UI data goes through `StateStore`.
- `GraphStateManager` uses session-per-method pattern. New queries add methods, not new managers.
- `dispatch_wave()` is the ONLY batch inference path. New inference patterns (interviews, reports) use `OllamaClient.chat()` directly through `agent_worker` or a new dedicated path.
- `ResourceGovernor` must gate ALL inference. Post-simulation features (interviews, reports) must respect concurrency limits.

## System Overview: v2.0 Extended Architecture

```
                            +---------------------+
                            |  CLI/TUI Entry      |
                            +----------+----------+
                                       |
                                       v
                            +---------------------+
                            |  AppState Container  |
                            |  + interview_engine  |  NEW
                            |  + report_generator  |  NEW
                            |  + persona_generator |  NEW
                            +----------+----------+
                                       |
             +-------------------------+-------------------------+
             |                         |                         |
             v                         v                         v
  +------------------+     +---------------------+    +--------------------+
  | PersonaGenerator |     | SeedInjector        |    | SimulationEngine   |
  | (PERSONA-01/02)  |     | (existing)          |    | (existing)         |
  |                  |     |                     |    |                    |
  | extract entities |     | + enriched entities |    | + rationale_post   |
  | generate dynamic |     |   for persona gen   |    |   write during     |
  | personas from    |     |                     |    |   inference        |
  | seed context     |     |                     |    | + narrative edges  |
  +--------+---------+     +----------+----------+    | + PUBLISHED_POST   |
           |                          |               +--------+-----------+
           |    +---------------------+                        |
           |    |                                              |
           v    v                                              v
  +------------------+                              +--------------------+
  | GraphStateManager|                              | AgentWorker.infer()|
  | + write_rationale|  NEW                         | + emit rationale   |
  | + write_narrative|  NEW                         |   post to Neo4j   |
  | + read_agent_ctx |  NEW (for interviews)        | + read peer posts |
  | + query_for_rpt  |  NEW (for reports)           +--------------------+
  +--------+---------+
           |
           v
  +------------------+           +---------------------+
  | Neo4j Graph      |           | InterviewEngine      |
  | + RationalePost  |  NEW      | (INT-01/02/03)       |
  | + PUBLISHED_POST |  NEW      |                      |  POST-SIMULATION
  | + READ_POST      |  NEW      | async chat loop      |
  | + NARRATIVE       |  NEW      | with persona context |
  +------------------+           +----------+----------+
                                            |
                                            v
                                 +---------------------+
                                 | ReportGenerator     |
                                 | (REPORT-01/02/03)   |  POST-SIMULATION
                                 |                     |
                                 | ReACT loop:         |
                                 |  Think -> Query ->  |
                                 |  Observe -> Write   |
                                 +---------------------+
```

## Component Responsibilities

### New Components

| Component | Responsibility | Implementation | Wired Via |
|-----------|---------------|----------------|-----------|
| **PersonaGenerator** | Extract entities from seed rumor, generate situation-specific personas that supplement or replace static bracket personas | New module `persona_gen.py` | `AppState.persona_generator` |
| **InterviewEngine** | Post-simulation async chat with any agent using full persona, decision history, and rationale context from Neo4j | New module `interview.py` | `AppState.interview_engine` |
| **ReportGenerator** | ReACT agent that queries Neo4j graph and generates structured market analysis markdown | New module `report.py` | `AppState.report_generator` |

### Modified Components

| Component | Current File | What Changes | Why |
|-----------|-------------|-------------|-----|
| **GraphStateManager** | `graph.py` | Add 5-6 new methods for rationale posts, narrative edges, interview context reads, and report queries | New node/edge types need Cypher operations |
| **AgentWorker** | `worker.py` | `infer()` returns richer output including raw rationale for post storage; optional rationale post emission | Richer agent interactions need rationale capture at inference time |
| **StateStore** | `state.py` | Add interview state, report progress, new phase values | TUI needs to reflect post-simulation states |
| **SimulationEngine** | `simulation.py` | Wire rationale post writes after each agent inference; add narrative edge computation after each round | Live graph memory requires real-time writes during simulation |
| **Types** | `types.py` | Add `SimulationPhase.INTERVIEWING`, `SimulationPhase.REPORTING`; new data types for rationale posts | New lifecycle phases |
| **CLI** | `cli.py` | Add `interview` and `report` subcommands | Entry points for new features |
| **TUI** | `tui.py` | Add interview panel/chat widget; add report progress indicator | Visual feedback for new features |
| **Config** | `config.py` | Add interview settings, report settings, persona gen settings | Configuration for new components |

## Feature-by-Feature Architecture

### Feature 1: Dynamic Persona Generation (PERSONA-01, PERSONA-02)

**What it does:** Instead of always using the static 100 personas from bracket configs, the system extracts entities from the seed rumor and generates situation-specific personas. For example, a rumor about "Apple acquiring OpenAI" would generate personas like "Apple institutional shareholder," "OpenAI employee with equity," and "NVIDIA competitor analyst."

**New module:** `src/alphaswarm/persona_gen.py`

**Integration point:** Between `inject_seed()` and `run_simulation()`. The persona generator receives the `ParsedSeedResult` (which already contains extracted entities) and produces supplemental personas.

**Design decision: Supplement, not replace.** The 100 static bracket personas provide reliable baseline diversity. Dynamic personas should ADD 10-20 situation-specific agents (total swarm grows to 110-120) OR REPLACE a subset of the generic personas within each bracket (maintain 100 total). Recommendation: **replace within brackets** to keep the 100-agent grid invariant for the TUI. Replace the most "generic" personas in relevant brackets -- e.g., for an Apple rumor, replace 2 Quants agents with Apple-specific quants.

```python
# persona_gen.py
@dataclass(frozen=True)
class DynamicPersonaSpec:
    """Specification for a dynamically generated persona."""
    target_bracket: BracketType
    replaces_agent_id: str  # Which static persona this replaces
    entity_context: str      # Which seed entity this persona relates to
    custom_system_prompt: str

class PersonaGenerator:
    def __init__(self, ollama_client: OllamaClient) -> None:
        self._client = ollama_client

    async def generate(
        self,
        parsed_result: ParsedSeedResult,
        brackets: list[BracketConfig],
        personas: list[AgentPersona],
        settings: AppSettings,
    ) -> list[AgentPersona]:
        """Generate situation-specific personas from seed entities.

        Uses orchestrator model to create custom system prompts
        for agents most relevant to the extracted entities.

        Returns a NEW list of personas with some replaced.
        """
        ...
```

**Data flow:**
```
inject_seed() -> ParsedSeedResult
    |
    v
PersonaGenerator.generate(parsed_result, brackets, personas)
    |
    v
Modified personas list (still 100 agents, some with entity-specific prompts)
    |
    v
run_simulation(personas=modified_personas, ...)
```

**Orchestrator model usage:** This requires the orchestrator model (large model) to generate custom system prompts. The model lifecycle is:
1. `inject_seed()` loads orchestrator, parses seed, unloads
2. `PersonaGenerator.generate()` loads orchestrator, generates prompts, unloads
3. `run_simulation()` loads worker model for rounds

This adds one extra orchestrator cold-load cycle (~30s). Optimization: keep the orchestrator loaded between `inject_seed()` and `PersonaGenerator.generate()` by moving the unload to after persona generation.

**Changes to existing code:**
- `seed.py`: Do NOT unload orchestrator after inject (or provide option to keep loaded)
- `simulation.py` or `cli.py`: Call `PersonaGenerator.generate()` between inject and simulate
- `config.py`: Add `PersonaGenSettings` with `enabled: bool`, `max_replacements: int`, `entity_relevance_threshold: float`

### Feature 2: Live Graph Memory (GRAPH-01, GRAPH-02, GRAPH-03)

**What it does:** During simulation, each agent's rationale is stored as a `RationaleEpisode` node in Neo4j with rich metadata. Narrative edges (`NARRATIVE`) connect sequential rationale episodes for the same agent across rounds. Rationale posts are separate from decisions -- they capture the "story" of an agent's reasoning journey.

**No new module needed.** This extends `GraphStateManager` and modifies the simulation write path.

**New Neo4j schema:**

```cypher
// New node type
(:RationaleEpisode {
    episode_id: str,     // uuid4
    agent_id: str,
    cycle_id: str,
    round: int,
    rationale_text: str, // Full rationale (not truncated)
    signal: str,
    confidence: float,
    sentiment: float,
    cited_agents: [str],
    created_at: datetime
})

// New relationship types
(Agent)-[:AUTHORED]->(RationaleEpisode)
(RationaleEpisode)-[:FOR_CYCLE]->(Cycle)
(RationaleEpisode)-[:NARRATIVE {sequence: int}]->(RationaleEpisode)
    // Connects agent's R1 episode -> R2 episode -> R3 episode
```

**Integration into simulation pipeline:**

The key modification is in the write path after `dispatch_wave()`. Currently, `write_decisions()` persists Decision nodes. The live graph memory adds a parallel write for `RationaleEpisode` nodes.

```python
# In simulation.py, after dispatch_wave() returns:
agent_decisions = [...]  # existing

# NEW: Write rationale episodes (batch, same pattern as write_decisions)
await graph_manager.write_rationale_episodes(agent_decisions, cycle_id, round_num)

# NEW: Write narrative edges (only for rounds 2+, linking to previous round's episodes)
if round_num > 1:
    await graph_manager.write_narrative_edges(cycle_id, round_num)
```

**New GraphStateManager methods:**

```python
async def write_rationale_episodes(
    self,
    agent_decisions: list[tuple[str, AgentDecision]],
    cycle_id: str,
    round_num: int,
) -> None:
    """Batch-write RationaleEpisode nodes via UNWIND."""
    ...

async def write_narrative_edges(
    self,
    cycle_id: str,
    round_num: int,
) -> None:
    """Create NARRATIVE edges from round N-1 episodes to round N episodes for same agent."""
    # Single Cypher: MATCH episodes for this agent in rounds N-1 and N, CREATE edge
    ...

async def read_agent_rationale_history(
    self,
    agent_id: str,
    cycle_id: str,
) -> list[RationaleEpisode]:
    """Read full rationale history for an agent in a cycle. Used by InterviewEngine."""
    ...
```

**Index additions:**
```cypher
CREATE INDEX episode_agent_cycle IF NOT EXISTS
    FOR (e:RationaleEpisode) ON (e.agent_id, e.cycle_id, e.round)
```

**Memory impact:** Writing 100 additional nodes + edges per round is negligible compared to inference cost. The batch UNWIND pattern keeps it to 1-2 extra transactions per round.

### Feature 3: Richer Agent Interactions (SOCIAL-01, SOCIAL-02)

**What it does:** Agents publish "rationale posts" that other agents can read and react to, creating social influence dynamics beyond the current peer-decision-reading pattern. An agent's post is a structured summary of their reasoning, published to the graph. Other agents' prompts include a selection of these posts.

**This builds on Feature 2 (Live Graph Memory).** The `RationaleEpisode` nodes from Feature 2 serve double duty as the "posts" that peers read. The new element is the `READ_POST` relationship tracking which agents read which posts, and the `REACTED_TO` relationship capturing agreement/disagreement.

**New Neo4j relationships:**
```cypher
(Agent)-[:READ_POST {cycle_id, round}]->(RationaleEpisode)
(Decision)-[:REACTED_TO {stance: "agree"|"disagree"|"neutral"}]->(RationaleEpisode)
```

**Modified agent prompt construction:**

Currently, `_format_peer_context()` in `simulation.py` formats peer decisions as simple signal+confidence+rationale strings. The richer interaction pattern enhances this:

```python
def _format_peer_posts(
    posts: list[RationaleEpisode],
    source_round: int,
) -> str:
    """Format peer rationale posts for agent context injection.

    Richer than _format_peer_context() -- includes full rationale narrative
    and allows agents to cite specific posts by episode_id.
    """
    if not posts:
        return ""

    lines = [f"Market Discussion (Round {source_round}):"]
    for i, post in enumerate(posts, 1):
        lines.append(
            f'{i}. [{post.bracket}] {post.signal.upper()} '
            f'(conf: {post.confidence:.2f})\n'
            f'   Post #{post.episode_id[:8]}: "{post.rationale_text[:200]}"'
        )
    lines.append(
        "\nThese are peer perspectives for context. "
        "You may cite specific posts by their ID if they influence your reasoning."
    )
    return "\n".join(lines)
```

**Dependency chain:** Feature 3 REQUIRES Feature 2 (RationaleEpisode nodes must exist before peers can read them). Build Feature 2 first.

**Modified dispatch path:** In `_dispatch_round()`, instead of (or in addition to) `read_peer_decisions()`, call `read_peer_rationale_posts()` to get richer context.

### Feature 4: Agent Interviews (INT-01, INT-02, INT-03)

**What it does:** After simulation completes, the user can select any agent and have a live conversational Q&A. The interview uses the agent's full persona prompt, decision history across all 3 rounds, rationale episodes, and influence relationships as context.

**New module:** `src/alphaswarm/interview.py`

**Architecture pattern: Stateful chat session with graph-backed context.**

```python
# interview.py
@dataclass
class InterviewSession:
    """Active interview session with a single agent."""
    agent_id: str
    persona: AgentPersona
    cycle_id: str
    conversation_history: list[dict[str, str]]  # message list for Ollama
    context_loaded: bool = False

class InterviewEngine:
    def __init__(
        self,
        ollama_client: OllamaClient,
        model_manager: OllamaModelManager,
        graph_manager: GraphStateManager,
        governor: ResourceGovernor,
        personas: list[AgentPersona],
    ) -> None:
        self._client = ollama_client
        self._model_manager = model_manager
        self._graph = graph_manager
        self._governor = governor
        self._personas = {p.id: p for p in personas}
        self._session: InterviewSession | None = None

    async def start_session(self, agent_id: str, cycle_id: str) -> InterviewSession:
        """Initialize interview session: load context from Neo4j, build system prompt."""
        persona = self._personas[agent_id]

        # Load agent's full history from graph
        decisions = await self._graph.read_agent_decisions(agent_id, cycle_id)
        rationale_history = await self._graph.read_agent_rationale_history(agent_id, cycle_id)
        influence_data = await self._graph.read_agent_influence_data(agent_id, cycle_id)

        # Build enriched system prompt
        interview_system_prompt = self._build_interview_prompt(
            persona, decisions, rationale_history, influence_data,
        )

        session = InterviewSession(
            agent_id=agent_id,
            persona=persona,
            cycle_id=cycle_id,
            conversation_history=[
                {"role": "system", "content": interview_system_prompt},
            ],
            context_loaded=True,
        )
        self._session = session
        return session

    async def ask(self, question: str) -> str:
        """Send a question to the interviewed agent, return response."""
        assert self._session is not None

        self._session.conversation_history.append(
            {"role": "user", "content": question}
        )

        # Use governor to respect concurrency limits
        await self._governor.acquire()
        try:
            response = await self._client.chat(
                model=self._model_manager.worker_alias_or_orchestrator,
                messages=self._session.conversation_history,
                think=True,  # Enable reasoning for deeper answers
            )
        finally:
            self._governor.release(success=True)

        answer = response.message.content or ""
        self._session.conversation_history.append(
            {"role": "assistant", "content": answer}
        )
        return answer
```

**Model choice for interviews:** Interviews require deeper reasoning than simulation decisions. Two options:
1. **Worker model (7B)** -- faster, stays loaded, but shallower responses
2. **Orchestrator model (32B)** -- richer responses, requires model swap

**Recommendation:** Use the orchestrator model for interviews. Post-simulation is not latency-sensitive, and the interview quality benefits from the larger model. The model swap adds ~30s but only happens once per interview session.

**TUI integration:** Add an interview panel with Input widget + response display.

```python
# New TUI screen or mode
class InterviewPanel(Widget):
    """Interactive chat panel for agent interviews."""

    def compose(self) -> ComposeResult:
        yield Static("Interview", id="interview-header")
        yield RichLog(id="interview-log")  # Conversation history
        yield Input(placeholder="Ask a question...", id="interview-input")
```

**New SimulationPhase values:**
```python
class SimulationPhase(str, Enum):
    ...
    INTERVIEWING = "interviewing"   # NEW
    REPORTING = "reporting"         # NEW
```

**CLI entry point:**
```bash
python -m alphaswarm interview --agent quants_03 --cycle <cycle_id>
```

### Feature 5: Post-Simulation Report (REPORT-01, REPORT-02, REPORT-03)

**What it does:** A ReACT (Reasoning + Acting) agent queries the Neo4j graph to generate a structured market analysis report. The agent iteratively: (1) reasons about what data it needs, (2) executes a Cypher query tool, (3) observes the results, (4) decides whether to continue querying or write the report.

**New module:** `src/alphaswarm/report.py`

**Architecture pattern: Tool-augmented LLM loop.**

The ReACT agent does NOT use LangChain or LangGraph. It is a lightweight loop implemented directly with OllamaClient, keeping the dependency footprint minimal and consistent with the existing codebase philosophy.

```python
# report.py
@dataclass(frozen=True)
class ReportTool:
    """A tool the ReACT agent can invoke."""
    name: str
    description: str
    handler: Callable[[str], Awaitable[str]]

class ReportGenerator:
    MAX_ITERATIONS = 10  # Safety cap on ReACT loop

    def __init__(
        self,
        ollama_client: OllamaClient,
        model_manager: OllamaModelManager,
        graph_manager: GraphStateManager,
        governor: ResourceGovernor,
    ) -> None:
        self._client = ollama_client
        self._model_manager = model_manager
        self._graph = graph_manager
        self._governor = governor
        self._tools = self._register_tools()

    def _register_tools(self) -> list[ReportTool]:
        return [
            ReportTool(
                name="query_consensus",
                description="Get final consensus distribution across all brackets",
                handler=self._tool_query_consensus,
            ),
            ReportTool(
                name="query_shifts",
                description="Get signal transition counts between rounds",
                handler=self._tool_query_shifts,
            ),
            ReportTool(
                name="query_influence_leaders",
                description="Get most influential agents and their positions",
                handler=self._tool_query_influence_leaders,
            ),
            ReportTool(
                name="query_bracket_narratives",
                description="Get rationale themes per bracket",
                handler=self._tool_query_bracket_narratives,
            ),
            ReportTool(
                name="query_convergence",
                description="Analyze convergence patterns across rounds",
                handler=self._tool_query_convergence,
            ),
            ReportTool(
                name="write_report",
                description="Write the final structured report",
                handler=self._tool_write_report,
            ),
        ]

    async def generate(self, cycle_id: str) -> str:
        """Execute ReACT loop to generate market analysis report.

        Returns markdown string of the completed report.
        """
        system_prompt = REACT_SYSTEM_PROMPT  # Describes available tools and report format
        messages = [{"role": "system", "content": system_prompt}]

        for iteration in range(self.MAX_ITERATIONS):
            # Think: ask the LLM what to do next
            await self._governor.acquire()
            try:
                response = await self._client.chat(
                    model=self._model_manager.orchestrator_alias,
                    messages=messages,
                    format="json",
                    think=True,
                )
            finally:
                self._governor.release(success=True)

            action = parse_react_action(response.message.content)

            if action.tool == "write_report":
                return action.input  # The report content

            # Act: execute the tool
            tool_result = await self._execute_tool(action.tool, action.input)

            # Observe: add tool result to context
            messages.append({"role": "assistant", "content": response.message.content})
            messages.append({"role": "user", "content": f"Tool Result:\n{tool_result}"})

        # Safety: if max iterations exceeded, generate report from whatever we have
        return await self._force_report(messages)
```

**Tool implementations are Cypher queries against GraphStateManager:**

```python
async def _tool_query_consensus(self, cycle_id: str) -> str:
    """Query final round consensus from Neo4j."""
    async with self._graph._driver.session(database=self._graph._database) as session:
        result = await session.run("""
            MATCH (a:Agent)-[:MADE]->(d:Decision)
            WHERE d.cycle_id = $cycle_id AND d.round = 3
            RETURN a.bracket AS bracket, d.signal AS signal,
                   avg(d.confidence) AS avg_conf, count(*) AS count
            ORDER BY bracket, signal
        """, cycle_id=cycle_id)
        records = [dict(r) async for r in result]
    return json.dumps(records, indent=2)
```

**Alternatively**, and more cleanly, expose query methods on `GraphStateManager` rather than having `ReportGenerator` use the driver directly. This maintains the session-per-method encapsulation:

```python
# In graph.py -- add report-specific query methods
async def report_consensus_distribution(self, cycle_id: str) -> list[dict]:
    """Get per-bracket signal distribution for final round."""
    ...

async def report_influence_leaders(self, cycle_id: str, limit: int = 10) -> list[dict]:
    """Get top-N most cited agents across all rounds."""
    ...

async def report_rationale_themes(self, cycle_id: str) -> list[dict]:
    """Get representative rationale snippets grouped by bracket and signal."""
    ...
```

**Model choice for reports:** Use the orchestrator model (32B). The ReACT loop requires complex reasoning about what data to query and how to synthesize it. The report is generated post-simulation, so latency is acceptable.

**Output format:** Markdown file saved to `results/report_{cycle_id}_{timestamp}.md`.

## Recommended Project Structure Changes

```
src/alphaswarm/
    __init__.py
    __main__.py
    app.py             # MODIFIED: add new optional components to AppState
    batch_dispatcher.py
    cli.py             # MODIFIED: add interview, report subcommands
    config.py          # MODIFIED: add new settings models
    errors.py
    governor.py
    graph.py           # MODIFIED: add ~8 new methods for new node/edge types
    interview.py       # NEW: InterviewEngine + InterviewSession
    logging.py
    memory_monitor.py
    miro.py
    ollama_client.py
    ollama_models.py
    parsing.py         # MODIFIED: add parse_react_action() for report ReACT loop
    persona_gen.py     # NEW: PersonaGenerator
    report.py          # NEW: ReportGenerator + ReACT tools
    seed.py            # MODIFIED: option to keep orchestrator loaded
    simulation.py      # MODIFIED: add rationale episode writes, narrative edges
    state.py           # MODIFIED: add interview state, report progress
    tui.py             # MODIFIED: add interview panel, report indicator
    types.py           # MODIFIED: add new phases, data types
    utils.py
    worker.py          # MODIFIED: richer inference output
```

### Structure Rationale

- **No new subdirectories.** The codebase is flat (22 modules). Three new modules (`interview.py`, `persona_gen.py`, `report.py`) maintain this flat convention. At 25 modules the flat structure is still navigable.
- **Graph methods stay in `graph.py`.** Despite adding ~8 new methods, keeping all Cypher operations in one module maintains the session-per-method pattern and makes query review straightforward. If `graph.py` exceeds ~800 lines, split into `graph_core.py` (existing) and `graph_v2.py` (new methods) with a shared base class, but this is unlikely to be needed.
- **Interview and Report as independent modules.** They share no state and operate in different lifecycle phases (post-simulation). No shared base class needed.

## Data Flow: v2.0 Extended

### Simulation Phase (Modified)

```
inject_seed()
    |
    v
ParsedSeedResult (existing)
    |
    v
PersonaGenerator.generate() --- NEW: uses orchestrator model
    |
    v
Modified personas list (100 agents, some with entity-specific prompts)
    |
    v
run_simulation()
    |
    +-- for each round:
    |       dispatch_wave() -> agent_decisions
    |       write_decisions()               (existing)
    |       write_rationale_episodes()      --- NEW: full rationale to Neo4j
    |       write_narrative_edges()         --- NEW: R(N-1) -> R(N) links
    |       compute_influence_edges()       (existing)
    |       compute_bracket_summaries()     (existing)
    |       _push_top_rationales()          (existing)
    |
    v
SimulationResult (existing, unchanged)
```

### Post-Simulation Phase (New)

```
SimulationResult
    |
    +----> InterviewEngine (user-initiated)
    |           |
    |           v
    |       start_session(agent_id, cycle_id)
    |           |-- read_agent_decisions()      from Neo4j
    |           |-- read_agent_rationale_history()  from Neo4j
    |           |-- read_agent_influence_data()     from Neo4j
    |           v
    |       InterviewSession (stateful chat)
    |           |
    |           v
    |       ask(question) -> response
    |           |-- OllamaClient.chat() with full context
    |           v
    |       (repeat until user exits)
    |
    +----> ReportGenerator (auto or user-initiated)
                |
                v
            generate(cycle_id)
                |-- ReACT loop (max 10 iterations)
                |   |-- Think: LLM reasons about what to query
                |   |-- Act: execute tool (Cypher query via GraphStateManager)
                |   |-- Observe: add results to context
                |   v
                |   (repeat until write_report tool called)
                v
            Markdown report string
                |
                v
            Save to results/report_{cycle_id}_{timestamp}.md
```

### State Management (Extended)

```
StateStore (modified)
    |
    +-- Existing: agent_states, phase, round, governor_metrics, tps, rationale_queue, bracket_summaries
    |
    +-- NEW: interview_active: bool
    +-- NEW: interview_agent_id: str | None
    +-- NEW: interview_messages: list[tuple[str, str]]  (role, content) for TUI display
    +-- NEW: report_progress: ReportProgress | None
    |        ReportProgress(iteration: int, max_iterations: int, current_tool: str, status: str)
    |
    v (200ms poll, unchanged)
    TUI reads snapshot including new fields
```

## Architectural Patterns

### Pattern 1: Graph-Backed Conversational Context

**What:** Build conversational context for interviews from Neo4j graph traversal rather than in-memory state. Load the agent's full decision history, rationale episodes, and influence relationships into the system prompt.

**When:** Starting an interview session post-simulation.

**Trade-offs:**
- Pro: Context survives process restarts; interview can happen days after simulation
- Pro: Graph queries return exactly the relationships that matter
- Con: Adds ~50-100ms latency for initial context load (acceptable for interactive use)
- Con: Context window may fill quickly with 3 rounds of full rationale

**Prompt budget:** With the orchestrator model (32B, ~8K context typical), budget:
- System prompt (persona): ~300 tokens
- Decision history (3 rounds): ~150 tokens
- Rationale episodes (3 rounds): ~600 tokens
- Influence data: ~200 tokens
- Conversation history: ~6,750 tokens remaining
- At ~150 tokens per exchange, this allows ~22 back-and-forth turns before context truncation is needed

### Pattern 2: Lightweight ReACT Without Framework Dependencies

**What:** Implement the ReACT (Reason-Act-Observe) loop as a simple while loop with tool dispatch, using OllamaClient directly. No LangChain, LangGraph, or other agent framework dependencies.

**When:** Report generation.

**Trade-offs:**
- Pro: Zero new dependencies, consistent with codebase philosophy
- Pro: Full control over prompt engineering and tool dispatch
- Pro: Easy to test (mock OllamaClient, mock tool handlers)
- Con: Must implement tool parsing manually (JSON action format)
- Con: No built-in retry/fallback for malformed tool calls (must handle in parse_react_action)

**Why not LangChain/LangGraph:** The existing codebase has zero framework dependencies beyond Ollama, Textual, Neo4j, and Pydantic. Adding LangChain would introduce a large transitive dependency tree (~50+ packages) for a single feature. The ReACT pattern is simple enough to implement in ~100 lines.

### Pattern 3: Persona Replacement Within Fixed Grid

**What:** Dynamic personas replace specific agents within existing brackets rather than adding new agents. The 100-agent count stays fixed, preserving the TUI's 10x10 grid layout.

**When:** Dynamic persona generation.

**Trade-offs:**
- Pro: TUI grid invariant preserved (no layout changes needed)
- Pro: Bracket distribution stays balanced
- Pro: StateStore agent count assumption (100) unchanged
- Con: Reduces diversity within replaced bracket positions
- Con: Requires "replaceability ranking" logic for each bracket

**Replacement algorithm:**
1. For each seed entity, identify 1-3 most relevant brackets
2. Within each relevant bracket, select agents with the most generic modifier (last in round-robin sequence)
3. Generate custom system prompts that incorporate entity context
4. Create new AgentPersona objects with same IDs but custom prompts

### Pattern 4: Post-Simulation Phase Extension

**What:** Extend the `SimulationPhase` enum to include `INTERVIEWING` and `REPORTING` phases. The TUI HeaderBar displays the current phase, and StateStore tracks progress.

**When:** After simulation completes.

**Trade-offs:**
- Pro: TUI stays informative during post-simulation activities
- Pro: Governor can adjust behavior for interview vs report phases
- Con: Phase transitions become more complex (not just linear progression)

## Anti-Patterns

### Anti-Pattern 1: Separate GraphManager for v2 Features

**What people do:** Create a new `GraphStateManagerV2` class to avoid modifying the existing one.

**Why it's wrong:** Two managers sharing the same Neo4j driver creates session management confusion. Schema management (`ensure_schema()`) would need to run on both. Query optimization requires holistic index strategy.

**Do this instead:** Add new methods to existing `GraphStateManager`. Group them with clear section comments (`# --- Report queries (Phase 2) ---`). Add new index statements to `SCHEMA_STATEMENTS`.

### Anti-Pattern 2: Loading Full Rationale History Into Every Agent Prompt

**What people do:** For richer interactions, inject all 100 agents' full rationale texts into each prompt.

**Why it's wrong:** 100 rationales x 200 tokens = 20,000 tokens. The 7B worker model context window (~4-8K) cannot handle this. Even if it could, inference latency scales with context length.

**Do this instead:** Select top-5 peer rationale posts using the existing `select_diverse_peers()` function. Truncate each to 200 characters. Total injection: ~500 tokens per agent.

### Anti-Pattern 3: Blocking TUI During Interview Chat

**What people do:** Run the interview LLM call synchronously, freezing the TUI while waiting for a response.

**Why it's wrong:** Textual requires all long-running operations to be async Workers or run in background threads. A blocking call on the main event loop freezes all widgets.

**Do this instead:** Run interview inference as a Textual Worker. Push responses to StateStore. TUI polls and renders when ready.

### Anti-Pattern 4: Implementing ReACT with Raw String Parsing

**What people do:** Parse tool calls from LLM output using regex or string splitting.

**Why it's wrong:** LLM outputs are unpredictable. Regex-based tool parsing is fragile and leads to cascading parse failures.

**Do this instead:** Require the ReACT agent to output JSON (`format="json"` in Ollama call). Parse with Pydantic model validation, same 3-tier fallback pattern used in `parsing.py`. Define a `ReACTAction` Pydantic model.

```python
class ReACTAction(BaseModel, frozen=True):
    """Structured ReACT agent action output."""
    thought: str
    tool: str
    input: str  # Tool input / query parameter
```

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Neo4j (existing) | Session-per-method via AsyncDriver | Add ~8 new methods, ~4 new index statements |
| Ollama (existing) | OllamaClient.chat() for interviews + reports | Post-sim uses orchestrator model, needs model swap |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| PersonaGenerator -> SimulationEngine | Returns modified `list[AgentPersona]` passed to `run_simulation()` | One-shot, no ongoing communication |
| SimulationEngine -> GraphStateManager | New `write_rationale_episodes()` and `write_narrative_edges()` calls in round loop | Adds 2 async calls per round to existing pipeline |
| InterviewEngine -> GraphStateManager | `read_agent_decisions()`, `read_agent_rationale_history()`, `read_agent_influence_data()` at session start | One-time context load, then pure OllamaClient chat |
| InterviewEngine -> StateStore | Pushes interview messages for TUI display | Uses same pattern as rationale queue |
| ReportGenerator -> GraphStateManager | Tool handlers query graph via public methods | Each ReACT iteration may call 1-2 graph methods |
| ReportGenerator -> StateStore | Pushes `ReportProgress` for TUI indicator | Lightweight progress updates |

## Suggested Build Order

Build order follows dependency chains and maximizes testability at each step.

### Phase 1: Live Graph Memory (GRAPH-01, GRAPH-02, GRAPH-03)

**Why first:** All other features depend on richer graph data. Richer interactions need rationale episodes. Interviews need rationale history. Reports query rationale data.

**Components:**
1. Add `RationaleEpisode` dataclass to `types.py`
2. Add new schema statements to `graph.py` SCHEMA_STATEMENTS
3. Implement `write_rationale_episodes()` in `GraphStateManager`
4. Implement `write_narrative_edges()` in `GraphStateManager`
5. Implement `read_agent_rationale_history()` in `GraphStateManager`
6. Wire into `simulation.py` round loop (after `write_decisions()`)
7. Tests: verify episodes and narrative edges written correctly

**Existing code changes:**
- `graph.py`: Add 3 methods + schema statements
- `simulation.py`: Add 2 calls in round loop
- `types.py`: Add `RationaleEpisode` dataclass

**Risk:** LOW. Pattern mirrors existing `write_decisions()`. No API changes, no TUI changes.

### Phase 2: Richer Agent Interactions (SOCIAL-01, SOCIAL-02)

**Why second:** Depends on Phase 1 (RationaleEpisode nodes). Enhances the simulation data quality that interviews and reports will later consume.

**Components:**
1. Implement `read_peer_rationale_posts()` in `GraphStateManager`
2. Add `_format_peer_posts()` to `simulation.py`
3. Modify `_dispatch_round()` to optionally use rationale posts instead of plain peer decisions
4. Add `READ_POST` relationship write
5. Tests: verify enriched peer context injection

**Existing code changes:**
- `graph.py`: Add 2 methods (read posts, write READ_POST edges)
- `simulation.py`: Modify `_dispatch_round()` to use richer context

**Risk:** MEDIUM. Modifying the dispatch path affects core simulation behavior. Needs careful testing to ensure richer context does not degrade agent output quality or blow context windows.

### Phase 3: Dynamic Persona Generation (PERSONA-01, PERSONA-02)

**Why third:** Independent of Phases 1-2 in code, but benefits from being tested against the richer graph data they produce. Also, this feature modifies the input to the simulation, which is less risky than modifying the simulation loop itself.

**Components:**
1. Create `persona_gen.py` with `PersonaGenerator` class
2. Add `PersonaGenSettings` to `config.py`
3. Modify `seed.py` to optionally keep orchestrator loaded
4. Wire into CLI and TUI launch paths (between inject and simulate)
5. Add to `AppState` as optional component
6. Tests: verify persona replacement logic, prompt generation

**Existing code changes:**
- `config.py`: Add settings
- `seed.py`: Add `keep_orchestrator_loaded` parameter
- `cli.py`: Call persona generator in run/tui paths
- `app.py`: Add `persona_generator` field

**Risk:** LOW. Additive feature that modifies input, not core loop.

### Phase 4: Agent Interviews (INT-01, INT-02, INT-03)

**Why fourth:** Depends on Phase 1 (rationale history in graph) for rich context. Post-simulation feature, so does not affect core simulation reliability.

**Components:**
1. Create `interview.py` with `InterviewEngine` + `InterviewSession`
2. Add interview-specific read methods to `GraphStateManager`
3. Add `InterviewSettings` to `config.py`
4. Add `INTERVIEWING` to `SimulationPhase`
5. Add interview state to `StateStore`
6. Add `interview` CLI subcommand
7. Add interview panel to TUI (Input + response display)
8. Tests: verify context loading, multi-turn conversation

**Existing code changes:**
- `types.py`: Add phase enum value
- `state.py`: Add interview state fields
- `graph.py`: Add read methods (decisions, rationale, influence for single agent)
- `config.py`: Add settings
- `cli.py`: Add subcommand
- `tui.py`: Add interview widget/mode
- `app.py`: Add `interview_engine` field

**Risk:** MEDIUM. TUI changes require careful Textual widget integration. The interview panel introduces user input handling in a previously output-only TUI.

### Phase 5: Post-Simulation Report (REPORT-01, REPORT-02, REPORT-03)

**Why last:** Depends on Phase 1 (rationale data in graph). The ReACT pattern is the most complex new component. It benefits from all prior phases providing richer graph data to query.

**Components:**
1. Create `report.py` with `ReportGenerator`, `ReACTAction`, tool registry
2. Add `parse_react_action()` to `parsing.py`
3. Add report query methods to `GraphStateManager`
4. Add `ReportSettings` to `config.py`
5. Add `REPORTING` to `SimulationPhase`
6. Add report progress to `StateStore`
7. Add `report` CLI subcommand
8. Add report progress indicator to TUI
9. Tests: verify ReACT loop, tool dispatch, report output format

**Existing code changes:**
- `types.py`: Add phase enum value
- `state.py`: Add report progress fields
- `graph.py`: Add 4-5 report query methods
- `parsing.py`: Add ReACT action parsing
- `config.py`: Add settings
- `cli.py`: Add subcommand
- `tui.py`: Add progress indicator
- `app.py`: Add `report_generator` field

**Risk:** MEDIUM-HIGH. The ReACT loop is iterative and depends on LLM output quality for tool selection. Needs robust fallback for malformed tool calls and a hard iteration cap.

### Build Order Dependency Graph

```
Phase 1: Live Graph Memory
    |
    +-------+-------+
    |               |
    v               v
Phase 2:        Phase 3:
Richer          Dynamic Persona
Interactions    Generation
    |
    v
Phase 4: Agent Interviews
    |
    v
Phase 5: Post-Simulation Report
```

**Phase ordering rationale:**
- Phase 1 is foundational -- all features read from the richer graph data it produces
- Phases 2 and 3 are independent of each other and can be built in parallel
- Phase 4 depends on Phase 1 for context data; placed after Phase 2 because richer interactions improve interview context quality
- Phase 5 depends on Phase 1; placed last because it is the most complex (ReACT loop) and benefits from all prior phases providing maximum graph data

## Scaling Considerations

| Concern | 100 agents (current) | Notes |
|---------|---------------------|-------|
| Rationale episode writes | +100 nodes + 100 edges per round (trivial) | UNWIND batch, same pattern as decisions |
| Narrative edges | +100 edges per round for R2 and R3 | Single Cypher statement |
| Interview context load | ~3 graph reads (decisions, rationale, influence) | <100ms total |
| ReACT loop | 5-10 LLM calls + 5-10 graph queries | ~30-60s total, acceptable post-sim |
| Persona generation | 1 LLM call to generate 10-20 custom prompts | ~5-10s, one-time cost |
| Neo4j storage per sim | ~600 additional nodes (rationale episodes) | Negligible disk impact |

## Sources

- [Neo4j Text2Cypher ReACT agent example](https://github.com/neo4j-field/text2cypher-react-agent-example) -- Pattern reference for ReACT + Neo4j integration
- [MAGMA: Multi-Graph Agentic Memory Architecture](https://arxiv.org/abs/2601.03236) -- Multi-graph memory patterns for agent systems
- [DPRF: Dynamic Persona Refinement Framework](https://arxiv.org/abs/2510.14205) -- Dynamic persona generation and refinement patterns
- [Textual framework documentation](https://textual.textualize.io/) -- Widget composition, async Workers, Input handling
- [Neo4j async driver documentation](https://neo4j.com/docs/api/python-driver/current/async_api.html) -- Session-per-method pattern
- [ReACT: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) -- Original ReACT paper

---
*Architecture research for: AlphaSwarm v2.0 Engine Depth*
*Researched: 2026-03-31*
