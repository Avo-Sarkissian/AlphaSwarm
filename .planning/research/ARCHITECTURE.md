# Architecture Patterns

**Domain:** Local-first multi-agent LLM financial simulation engine
**Researched:** 2026-03-24

## Recommended Architecture

### High-Level System Overview

AlphaSwarm is a **pipeline-with-feedback-loop** architecture. The simulation flows linearly through three cascade rounds, but within each round, agents read peer state from a shared graph (Neo4j), creating a feedback topology. The system has five major subsystems, each isolated behind async interfaces.

```
                    +------------------+
                    |  Seed Injector   |  (Llama 4 orchestrator)
                    |  Entity Extract  |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    | Simulation Engine|  (3-round cascade controller)
                    |  Round Manager   |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
              v                             v
    +------------------+          +------------------+
    | Agent Swarm Pool |          | Resource Governor |
    | 100 agents via   |  <----  | psutil + dynamic  |
    | Ollama AsyncClient|         | semaphore         |
    +--------+---------+          +------------------+
             |
             v
    +------------------+
    | Neo4j Graph State|  (cycle-scoped sentiment + influence edges)
    +--------+---------+
             |
             v
    +------------------+
    | Textual TUI      |  (snapshot-based 200ms tick rendering)
    | Dashboard        |
    +------------------+
```

### Component Boundaries

| Component | Responsibility | Communicates With | Async Interface |
|-----------|---------------|-------------------|-----------------|
| **SeedInjector** | Parse rumor via Llama 4, extract entities, produce structured SeedEvent | SimulationEngine, Neo4j | `async def inject(rumor: str) -> SeedEvent` |
| **SimulationEngine** | Orchestrate 3-round cascade, manage round transitions, collect results | AgentPool, Neo4j, TUI StateStore | `async def run_simulation(seed: SeedEvent) -> SimResult` |
| **AgentPool** | Manage 100 agent instances, dispatch inference batches through ResourceGovernor | Ollama AsyncClient, ResourceGovernor, Neo4j | `async def process_round(round_ctx: RoundContext) -> list[AgentDecision]` |
| **ResourceGovernor** | Monitor memory via psutil, dynamically adjust concurrency semaphore, enforce backpressure | AgentPool (controls its throughput), TUI StateStore (telemetry) | `async def acquire() -> None` / `release()` |
| **GraphStateManager** | All Neo4j reads/writes: agent states, influence edges, sentiment history | Neo4j AsyncDriver, AgentPool, SimulationEngine | `async def write_decisions(...)` / `async def read_peer_state(...)` |
| **TUI Dashboard** | Render 10x10 grid, rationale sidebar, telemetry footer from shared snapshot | StateStore (read-only), Textual event loop | `set_interval(0.2, self.refresh_from_snapshot)` |
| **StateStore** | Thread-safe shared state object: agent statuses, telemetry, latest rationales | Written by SimulationEngine/AgentPool/ResourceGovernor, read by TUI | Dataclass with `asyncio.Lock` guarded writes |
| **MiroBatcher** | (Stubbed Phase 1) Bulk Miro API calls with 2s buffer. Full implementation deferred. | Miro REST API v2 | `async def flush_batch()` |

## Data Flow

### Round-by-Round Cascade Flow

```
ROUND 1: Initial Reaction
  SeedEvent --> AgentPool dispatches 100 agents in batches of ~16
    Each agent receives: seed_entities, persona_prompt, bracket_archetype
    Each agent produces: Decision(BUY|SELL|HOLD), sentiment_score, rationale_text
    Results --> Neo4j: CREATE (:Agent)-[:DECIDED {cycle_id, round: 1}]->(:Decision)

ROUND 2: Peer Influence
  SimulationEngine queries Neo4j for Round 1 peer decisions
    Influence reads scoped: top-K peers by bracket + random cross-bracket sampling
    Each agent receives: own_r1_decision, peer_decisions[], influence_weights
    Each agent produces: updated Decision, rationale citing peers
    Results --> Neo4j: CREATE (:Agent)-[:DECIDED {cycle_id, round: 2}]->(:Decision)
                       CREATE (:Agent)-[:INFLUENCED_BY {cycle_id, round: 2}]->(:Agent)

ROUND 3: Final Consensus Lock
  SimulationEngine queries Neo4j for Round 2 decisions + influence topology
    Consensus pressure: agents see aggregate sentiment shift
    Each agent produces: FINAL Decision (locked), confidence_score, final_rationale
    Results --> Neo4j: CREATE (:Agent)-[:DECIDED {cycle_id, round: 3, locked: true}]->(:Decision)
    INFLUENCED_BY edges finalized for this cycle

POST-ROUND: Aggregation
  SimulationEngine reads full cycle from Neo4j
  Computes: consensus distribution, bracket-level sentiment, influence clusters
  Pushes summary to StateStore --> TUI renders final state
```

### Data Flow Between Components

```
User Input (rumor text)
  |
  v
SeedInjector --[SeedEvent]--> SimulationEngine
  |                                |
  |                    (for each of 3 rounds)
  |                                |
  |                                v
  |                         AgentPool.process_round()
  |                           |            ^
  |                           |            |
  |                    ResourceGovernor    ResourceGovernor
  |                    (acquire/release)  (backpressure signal)
  |                           |
  |                           v
  |                    Ollama AsyncClient.chat() x N
  |                           |
  |                           v
  |                    GraphStateManager.write_decisions()
  |                           |
  |                           v
  |                    Neo4j (persisted state)
  |                           |
  |                           v
  |                    GraphStateManager.read_peer_state()
  |                           |
  |                    (feeds into next round)
  |
  v (throughout)
StateStore <-- telemetry, agent statuses, rationales
  |
  v (every 200ms)
TUI Dashboard renders snapshot
```

## Component Deep Dives

### 1. SeedInjector

**Purpose:** Transform raw rumor text into a structured event that all 100 agents can process uniformly.

**Implementation pattern:**
```python
@dataclass
class SeedEvent:
    raw_text: str
    entities: list[Entity]       # ticker symbols, company names, sectors
    sentiment_hint: float        # orchestrator's initial read (-1.0 to 1.0)
    rumor_type: RumorType        # EARNINGS, GEOPOLITICAL, REGULATORY, etc.
    timestamp: datetime

class SeedInjector:
    def __init__(self, ollama: AsyncClient):
        self._ollama = ollama
        self._model = "llama4:70b"

    async def inject(self, rumor: str) -> SeedEvent:
        # Single Llama 4 call with structured output prompt
        response = await self._ollama.chat(
            model=self._model,
            messages=[{"role": "system", "content": SEED_PARSE_PROMPT},
                      {"role": "user", "content": rumor}],
            format="json"
        )
        return SeedEvent.from_llm_response(response)
```

**Key constraint:** This is a single sequential call (not parallelized). The 70B model will be loaded for this step, then kept warm for post-round aggregation. Worker agents use qwen3.5:7b -- the two-model limit means these models must be carefully sequenced.

### 2. SimulationEngine (Round Manager)

**Purpose:** Orchestrate the 3-round cascade, manage model loading transitions, and coordinate between AgentPool and GraphStateManager.

**Architecture pattern:** State machine with explicit round transitions.

```python
class SimulationPhase(Enum):
    IDLE = "idle"
    SEED_INJECTION = "seed_injection"
    ROUND_1_INITIAL = "round_1_initial"
    ROUND_2_INFLUENCE = "round_2_influence"
    ROUND_3_CONSENSUS = "round_3_consensus"
    AGGREGATION = "aggregation"
    COMPLETE = "complete"

class SimulationEngine:
    async def run_simulation(self, seed: SeedEvent) -> SimResult:
        cycle_id = uuid4()

        # Phase 1: Seed injection (uses llama4:70b)
        seed_event = await self._injector.inject(seed.raw_text)
        await self._graph.persist_seed(cycle_id, seed_event)

        # Model transition: llama4:70b stays loaded but idle
        # qwen3.5:7b loads for worker agents (both within 2-model limit)

        # Phases 2-4: Three cascade rounds
        for round_num in (1, 2, 3):
            round_ctx = await self._build_round_context(cycle_id, round_num)
            decisions = await self._agent_pool.process_round(round_ctx)
            await self._graph.write_decisions(cycle_id, round_num, decisions)
            await self._state_store.update_round_complete(round_num, decisions)

        # Phase 5: Aggregation (uses llama4:70b for summary)
        return await self._aggregate(cycle_id)
```

**Critical design decision:** The engine does NOT directly manage Ollama concurrency. It delegates batch dispatch to AgentPool, which delegates concurrency control to ResourceGovernor. This separation of concerns prevents the orchestration logic from being entangled with resource management.

### 3. AgentPool and Agent Instances

**Purpose:** Manage 100 agent personas and dispatch inference requests through the ResourceGovernor.

**Agent identity model:**

```python
@dataclass(frozen=True)
class AgentPersona:
    id: str                    # e.g., "quant_03"
    bracket: BracketType       # QUANT, DEGEN, SOVEREIGN, etc.
    name: str
    risk_profile: float        # 0.0 (conservative) to 1.0 (aggressive)
    system_prompt: str         # Pre-built persona prompt
    influence_weight: float    # Initial weight, evolves with topology

class AgentPool:
    def __init__(self, agents: list[AgentPersona], governor: ResourceGovernor,
                 ollama: AsyncClient, graph: GraphStateManager):
        self._agents = agents
        self._governor = governor
        self._ollama = ollama
        self._graph = graph

    async def process_round(self, ctx: RoundContext) -> list[AgentDecision]:
        tasks = [self._process_agent(agent, ctx) for agent in self._agents]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_agent(self, agent: AgentPersona, ctx: RoundContext) -> AgentDecision:
        async with self._governor:  # Backpressure gate
            peer_state = await self._graph.read_peer_state(
                ctx.cycle_id, ctx.round_num, agent
            )
            messages = build_agent_prompt(agent, ctx.seed, peer_state)
            response = await self._ollama.chat(
                model="qwen3.5:7b",
                messages=messages,
                format="json"
            )
            return AgentDecision.from_response(agent, ctx.round_num, response)
```

**Concurrency model:** All 100 agents are dispatched as concurrent coroutines via `asyncio.gather`. The ResourceGovernor semaphore gates actual Ollama calls to ~16 at a time (dynamically adjusted). This means up to 84 agents are queued in Python asyncio waiting on the semaphore while 16 are actively inferring.

### 4. ResourceGovernor

**Purpose:** Dynamic concurrency control based on real-time memory pressure. This is the critical component preventing OOM crashes on M1 Max 64GB.

**Architecture pattern:** Adaptive semaphore with psutil-driven feedback loop.

```python
class ResourceGovernor:
    """Async context manager that gates concurrency based on system resources."""

    def __init__(self, baseline_parallel: int = 16, check_interval: float = 2.0):
        self._baseline = baseline_parallel
        self._current_limit = baseline_parallel
        self._semaphore = asyncio.Semaphore(baseline_parallel)
        self._pressure_threshold = 0.90  # 90% memory utilization
        self._check_interval = check_interval
        self._monitor_task: asyncio.Task | None = None

    async def start_monitoring(self):
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        while True:
            mem = psutil.virtual_memory()
            if mem.percent >= self._pressure_threshold * 100:
                await self._shrink()
            elif mem.percent < (self._pressure_threshold - 0.10) * 100:
                await self._grow()
            await asyncio.sleep(self._check_interval)

    async def _shrink(self):
        """Reduce concurrency by acquiring extra semaphore slots."""
        new_limit = max(4, self._current_limit // 2)
        # Acquire (current - new) slots to reduce parallelism
        ...

    async def __aenter__(self):
        await self._semaphore.acquire()

    async def __aexit__(self, *args):
        self._semaphore.release()
```

**Key design note:** Python's `asyncio.Semaphore` has a fixed internal counter set at init. To dynamically shrink concurrency, the governor must "consume" surplus slots by acquiring them and holding them. To grow, it releases previously held surplus slots. This is a well-known pattern for adaptive semaphores but requires careful bookkeeping to avoid deadlocks.

**Alternative considered:** Using `asyncio.Queue` with a bounded size as a token pool. Simpler to reason about for dynamic resizing (just add/remove tokens), but less idiomatic. **Recommendation:** Use the queue-based token pool pattern instead of semaphore hacking -- it is cleaner for dynamic adjustment.

```python
class ResourceGovernor:
    """Token-pool based concurrency limiter with dynamic adjustment."""

    def __init__(self, baseline: int = 16):
        self._pool = asyncio.Queue(maxsize=0)  # Unbounded queue of tokens
        for _ in range(baseline):
            self._pool.put_nowait(True)
        self._current_limit = baseline

    async def acquire(self):
        await self._pool.get()  # Blocks if no tokens available

    def release(self):
        self._pool.put_nowait(True)

    async def shrink(self, amount: int):
        """Remove tokens from pool (acquire and discard them)."""
        for _ in range(amount):
            await asyncio.wait_for(self._pool.get(), timeout=0.1)
            self._current_limit -= 1

    def grow(self, amount: int):
        """Add tokens to pool."""
        for _ in range(amount):
            self._pool.put_nowait(True)
            self._current_limit += 1
```

### 5. GraphStateManager (Neo4j)

**Purpose:** All graph reads and writes. Encapsulates Cypher queries and manages session lifecycle.

**Graph data model:**

```
(:Agent {id, name, bracket, risk_profile, influence_weight})
    -[:DECIDED {cycle_id, round, timestamp}]->
(:Decision {action: BUY|SELL|HOLD, sentiment: float, confidence: float, rationale: str})

(:Agent)-[:INFLUENCED_BY {cycle_id, round, weight: float, citation: str}]->(:Agent)

(:Cycle {id, seed_text, started_at, completed_at, consensus_result})
    -[:HAS_ROUND {round_num}]->
(:Round {num, started_at, completed_at, aggregate_sentiment})
```

**Index strategy for sub-5ms queries:**

```cypher
// Composite indexes for cycle-scoped reads (the hot path)
CREATE INDEX agent_decision_cycle FOR ()-[r:DECIDED]-() ON (r.cycle_id, r.round)
CREATE INDEX influence_cycle FOR ()-[r:INFLUENCED_BY]-() ON (r.cycle_id, r.round)
CREATE INDEX agent_id FOR (a:Agent) ON (a.id)
```

**Critical async pattern:** Neo4j AsyncSession objects are NOT concurrency-safe. Each concurrent coroutine must use its own session. The driver handles connection pooling internally.

```python
class GraphStateManager:
    def __init__(self, driver: AsyncDriver):
        self._driver = driver

    async def write_decisions(self, cycle_id: str, round_num: int,
                               decisions: list[AgentDecision]):
        """Batch write all decisions for a round in a single transaction."""
        async with self._driver.session() as session:
            await session.execute_write(
                self._write_decisions_tx, cycle_id, round_num, decisions
            )

    @staticmethod
    async def _write_decisions_tx(tx, cycle_id, round_num, decisions):
        # UNWIND for batch insert -- single Cypher statement for all 100 decisions
        await tx.run("""
            UNWIND $decisions AS d
            MATCH (a:Agent {id: d.agent_id})
            CREATE (a)-[:DECIDED {cycle_id: $cycle_id, round: $round}]->
                   (:Decision {action: d.action, sentiment: d.sentiment,
                               confidence: d.confidence, rationale: d.rationale})
        """, cycle_id=cycle_id, round=round_num,
             decisions=[d.to_dict() for d in decisions])

    async def read_peer_state(self, cycle_id: str, round_num: int,
                               agent: AgentPersona) -> list[PeerDecision]:
        """Read peer decisions for influence round. One session per call."""
        async with self._driver.session() as session:
            result = await session.execute_read(
                self._read_peers_tx, cycle_id, round_num - 1, agent
            )
            return result
```

**Batch write pattern:** Always use UNWIND to batch 100 decisions into a single Cypher statement per round. Never write agent-by-agent -- that creates 100 separate transactions with 100x the overhead.

### 6. TUI Dashboard (Textual)

**Purpose:** Real-time visualization of simulation state without blocking the simulation engine.

**Architecture pattern: Snapshot-based decoupled rendering.**

The TUI runs on the same asyncio event loop as the simulation but never directly awaits simulation coroutines. Instead:

1. **StateStore** is a shared dataclass updated by simulation components
2. **TUI** reads StateStore every 200ms via `set_interval`
3. No direct coupling between agent inference and UI updates

```python
@dataclass
class StateSnapshot:
    """Immutable snapshot of simulation state for TUI consumption."""
    phase: SimulationPhase
    agent_states: dict[str, AgentStatus]  # id -> (THINKING|RESOLVED|ERROR|IDLE)
    agent_decisions: dict[str, str]       # id -> BUY|SELL|HOLD (latest round)
    latest_rationales: list[RationaleEntry]  # Most recent impactful rationales
    round_num: int
    tokens_per_second: float
    memory_percent: float
    active_inferences: int
    queue_depth: int

class StateStore:
    """Thread-safe mutable state, produces immutable snapshots."""
    def __init__(self):
        self._lock = asyncio.Lock()
        self._data = MutableState()

    async def update_agent(self, agent_id: str, status: AgentStatus, decision: str | None = None):
        async with self._lock:
            self._data.agent_states[agent_id] = status
            if decision:
                self._data.agent_decisions[agent_id] = decision

    def snapshot(self) -> StateSnapshot:
        """Non-blocking read for TUI. Returns frozen copy."""
        return StateSnapshot(
            phase=self._data.phase,
            agent_states=dict(self._data.agent_states),
            agent_decisions=dict(self._data.agent_decisions),
            latest_rationales=list(self._data.latest_rationales[-20:]),
            round_num=self._data.round_num,
            tokens_per_second=self._data.tps,
            memory_percent=self._data.memory_percent,
            active_inferences=self._data.active_inferences,
            queue_depth=self._data.queue_depth,
        )
```

**TUI layout:**

```python
class AlphaSwarmApp(App):
    CSS = """
    #grid { layout: grid; grid-size: 10 10; }
    #sidebar { width: 40; }
    #footer { height: 3; dock: bottom; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield AgentGrid(id="grid")       # 10x10 colored cells
            yield RationaleSidebar(id="sidebar")  # Streaming rationale log
        yield TelemetryFooter(id="footer")   # RAM, TPS, queue depth

    def on_mount(self):
        self.set_interval(0.2, self._refresh_snapshot)

    def _refresh_snapshot(self):
        snap = self.state_store.snapshot()
        self.query_one("#grid").update_from(snap)
        self.query_one("#sidebar").update_from(snap)
        self.query_one("#footer").update_from(snap)
```

**Key design:** The TUI uses Textual's reactive attributes on each grid cell widget. The 200ms interval calls `update_from()` which sets reactive attributes, triggering efficient re-renders only for cells that changed. This avoids the trap of calling `refresh()` on the entire app.

### 7. Ruflo v3.5 Integration Layer

**Important architectural note:** Ruflo is a TypeScript/Node.js platform, not a native Python library. It provides multi-agent orchestration via CLI commands and MCP server protocol. For AlphaSwarm (a pure Python asyncio application), Ruflo cannot be imported directly.

**Integration options (in order of recommendation):**

1. **Adopt Ruflo's hierarchical coordination patterns, implement in Python.** Use Ruflo's queen/worker topology and delegation strategy concepts but implement them natively in asyncio. This is the recommended approach -- the patterns are sound, the implementation must be Python-native.

2. **Subprocess bridge.** Call `npx ruflo` commands from Python via `asyncio.create_subprocess_exec`. High latency, fragile, not recommended for hot-path simulation logic.

3. **MCP server protocol.** If Ruflo exposes an MCP endpoint, connect via the protocol. Still adds network hop latency inappropriate for tight simulation loops.

**Recommendation:** Implement Ruflo's hierarchical swarm concepts (queen coordinator, worker delegation, shared context) as native Python asyncio classes. The SimulationEngine already acts as the "queen" coordinator, and AgentPool manages "worker" agents. This gives the architectural benefits without the cross-runtime overhead.

## Patterns to Follow

### Pattern 1: Producer-Consumer with Bounded Queue Backpressure

**What:** Use `asyncio.Queue(maxsize=N)` as the primary flow control mechanism between simulation engine and Ollama inference.

**When:** Dispatching 100 agent inference requests against a 16-slot parallel limit.

**Why:** Prevents unbounded memory growth from 100 pending prompt payloads. The queue's `put()` blocks the producer when full, naturally throttling the simulation engine.

### Pattern 2: Cycle-Scoped Graph Queries

**What:** Every Neo4j relationship carries a `cycle_id` and `round` property. All reads filter on current cycle. Composite index on `(cycle_id, round)` keeps queries under 5ms.

**When:** Every peer-state read in Rounds 2 and 3.

**Why:** Without cycle scoping, queries would scan the entire graph history. With composite indexes, Neo4j can do index-only lookups for current-cycle data.

### Pattern 3: Immutable Snapshot for UI Decoupling

**What:** Simulation writes to a mutable StateStore. TUI reads frozen snapshots on a 200ms timer. No shared mutable state crosses the boundary.

**When:** Every TUI refresh cycle.

**Why:** 100 agents updating state at ~16 concurrent would flood Textual's message queue if each pushed UI updates directly. The snapshot pattern decouples agent throughput from render throughput entirely.

### Pattern 4: Two-Model Loading Strategy

**What:** The orchestrator (llama4:70b) and workers (qwen3.5:7b) respect Ollama's MAX_LOADED_MODELS=2 constraint. Both models loaded simultaneously -- the 70B for seed injection and aggregation, the 7B for all 300 agent inferences (100 agents x 3 rounds).

**When:** Simulation startup and throughout execution.

**Why:** Cold-loading the 70B model takes ~30 seconds. By keeping both models loaded and routing requests to the appropriate model, we avoid repeated cold loads. The 70B model is idle during agent rounds (it only handles seed parsing and final aggregation).

### Pattern 5: UNWIND Batch Writes

**What:** All per-round Neo4j writes use Cypher UNWIND to insert 100 decisions in a single transaction.

**When:** After each round completes.

**Why:** 100 individual CREATE statements = 100 transaction round-trips. One UNWIND = 1 transaction. At 3 rounds, this saves 297 transaction round-trips per simulation cycle.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Per-Agent UI Updates

**What:** Having each agent coroutine directly call `widget.update()` on the TUI.

**Why bad:** 100 agents x 3 rounds = 300 update calls, many concurrent. Textual's message queue floods, UI thread starves, rendering freezes or crashes.

**Instead:** Write to StateStore, let TUI poll on 200ms interval.

### Anti-Pattern 2: Shared AsyncSession for Neo4j

**What:** Creating one `AsyncSession` and sharing it across concurrent agent coroutines.

**Why bad:** AsyncSession is explicitly NOT concurrency-safe. Concurrent use causes corrupted state, dropped results, or crashes.

**Instead:** Each concurrent Neo4j operation gets its own session from the driver's connection pool. The driver manages pooling internally -- sessions are cheap to create.

### Anti-Pattern 3: Hardcoded Semaphore Without Monitoring

**What:** Setting `asyncio.Semaphore(16)` and never adjusting it.

**Why bad:** The 70B model's context windows vary in size. A rumor about multiple entities may produce larger prompts that consume more memory per inference. Static limits either waste capacity (too conservative) or risk OOM (too aggressive).

**Instead:** ResourceGovernor with psutil feedback loop, adjusting the token pool every 2 seconds based on actual memory pressure.

### Anti-Pattern 4: Sequential Agent Processing

**What:** Processing agents one-by-one with `for agent in agents: await process(agent)`.

**Why bad:** 100 agents x ~2-5 seconds per inference = 200-500 seconds per round. Three rounds = 10-25 minutes. Unacceptable.

**Instead:** `asyncio.gather(*tasks)` with ResourceGovernor gating concurrency. 100 agents with 16 parallel = ~13-32 seconds per round. Three rounds = ~40-95 seconds total.

### Anti-Pattern 5: Storing Full Rationale Text in Prompt Context

**What:** Passing all 100 agent rationales from Round 1 into every Round 2 prompt.

**Why bad:** 100 rationales x ~200 tokens each = 20,000 extra tokens per prompt. With 100 agents, that is 2 million prompt tokens per round. The 7B model's context window cannot handle this, and even if it could, latency explodes.

**Instead:** Select top-K influential peers (5-8) based on bracket proximity and influence weight. Summarize their positions in ~50 tokens each. Total context addition: ~400 tokens per agent.

## Scalability Considerations

| Concern | Current (100 agents) | At 500 agents | At 1000 agents |
|---------|---------------------|---------------|----------------|
| Inference time per round | ~20-30s (16 parallel) | ~100-150s (need batch API) | Not feasible on M1 Max |
| Neo4j write volume | 100 decisions/round | 500/round (still single UNWIND) | 1000/round (split into 100-item batches) |
| Memory pressure | ~45-55GB peak (70B + 7B + Neo4j + Python) | Exceeds 64GB -- must drop 70B model between rounds | Not feasible |
| TUI rendering | 10x10 grid, trivial | 25x20 grid, still fast | 50x20 grid, may need virtualization |
| Neo4j query latency | <5ms with composite index | <10ms (more edges to traverse) | 10-20ms (need query optimization) |

**At 100 agents (current target):** M1 Max 64GB is viable with careful memory management. The 70B + 7B dual-model strategy works within the 2-model limit. The bottleneck is Ollama inference throughput, not graph queries or TUI rendering.

## Suggested Build Order (Dependencies)

Build order is dictated by dependency chains. Each layer depends on the layers above it being functional.

```
Phase 1: Foundation (no simulation yet)
  1. Project scaffolding, config, type definitions
  2. AgentPersona definitions (100 agents across 10 brackets)
  3. Neo4j connection + schema setup (indexes, constraints)
  4. Ollama AsyncClient wrapper with retry/backoff
  5. ResourceGovernor (standalone, testable with mock load)

Phase 2: Core Engine (simulation without UI)
  6. GraphStateManager (CRUD operations, tested against Neo4j)
  7. SeedInjector (Llama 4 entity extraction)
  8. AgentPool (dispatch + inference + write cycle for 1 round)
  9. SimulationEngine (3-round cascade, round transitions)
  --> Milestone: CLI-driven simulation that writes to Neo4j

Phase 3: TUI Dashboard
  10. StateStore (shared state + snapshot mechanism)
  11. TUI shell (Textual app, layout, empty widgets)
  12. AgentGrid widget (10x10 with color states)
  13. RationaleSidebar widget
  14. TelemetryFooter widget
  15. Wire StateStore to simulation engine
  --> Milestone: Full simulation with live TUI

Phase 4: Polish + Influence Topology
  16. Dynamic INFLUENCED_BY edge creation from citation patterns
  17. Influence weight evolution across rounds
  18. Consensus aggregation and summary (Llama 4)
  19. MiroBatcher stub (API stubbed, batcher logic real)
  20. Exponential backoff for Ollama + Miro retry strategies
  --> Milestone: Production-quality simulation
```

**Dependency rationale:**
- ResourceGovernor must exist before AgentPool (gates concurrency)
- GraphStateManager must exist before AgentPool (agents write to Neo4j)
- SeedInjector must exist before SimulationEngine (provides seed events)
- StateStore must exist before TUI (TUI reads from it)
- Core simulation must work headless before TUI is added (easier to debug)
- Influence topology is a Round 2/3 enhancement, not needed for basic cascade

## Sources

- [Ollama parallel request handling internals](https://www.glukhov.org/post/2025/05/how-ollama-handles-parallel-requests/)
- [Ollama Python library (v0.6.1)](https://github.com/ollama/ollama-python)
- [Ollama official batching support discussion](https://github.com/ollama/ollama/issues/10699)
- [Neo4j Python async driver docs](https://neo4j.com/docs/api/python-driver/current/async_api.html)
- [Neo4j concurrent transactions](https://neo4j.com/docs/python-manual/current/concurrency/)
- [Textual Workers guide](https://textual.textualize.io/guide/workers/)
- [Textual Reactivity guide](https://textual.textualize.io/guide/reactivity/)
- [OASIS: Open Agent Social Interaction Simulations architecture](https://arxiv.org/abs/2411.11581)
- [Ruflo v3.5 (TypeScript/Node.js platform)](https://github.com/ruvnet/ruflo)
- [Asyncio backpressure with bounded queues](https://softwarepatternslexicon.com/patterns-python/9/4/)
- [Multi-agent LLM architecture guide 2025](https://collabnix.com/multi-agent-and-multi-llm-architecture-complete-guide-for-2025/)
- [psutil system monitoring](https://psutil.readthedocs.io/)
- [Neo4j composite indexes and performance](https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/using-indexes/)
