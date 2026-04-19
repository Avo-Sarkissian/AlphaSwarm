# Phase 7: Rounds 2-3 Peer Influence and Consensus - Research

**Researched:** 2026-03-26
**Domain:** Multi-round consensus pipeline, async orchestration, peer context injection, opinion shift analysis
**Confidence:** HIGH

## Summary

Phase 7 completes the core 3-round consensus cascade by adding Rounds 2-3 to the existing Round 1 pipeline. The implementation is a composition of existing primitives: `run_round1()` handles the first round, then `run_simulation()` reloads the worker model and dispatches two additional waves with formatted peer context strings. All building blocks are already implemented and tested: `dispatch_wave()` accepts `peer_context: str | None`, `read_peer_decisions()` returns ranked `PeerDecision` objects, `AgentWorker.infer()` injects peer context as a second system message, and `write_decisions()` supports `round_num` parameterization.

The primary engineering challenge is **orchestration correctness**: managing the model lifecycle (one cold reload after Round 1), governor monitoring spans, per-agent peer context assembly (100 agents x 5 peers = 500 Neo4j reads per round), and clean state machine transitions. The secondary challenge is **observability**: computing opinion shift metrics between rounds and reporting them progressively to the user during the ~10 minute simulation runtime.

**Primary recommendation:** Build `run_simulation()` as a thin orchestrator that calls `run_round1()` for the first round, then manages a single governor monitoring session and model load for Rounds 2-3. Peer context formatting and shift analysis are pure functions that can be unit-tested independently of the async pipeline.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Structured summary format for peer_context string. Each of the top-5 peers rendered as: `[Bracket] SIGNAL (conf: X.XX)` followed by an 80-char truncated rationale snippet. ~250 tokens total for 5 peers. Balances information density with the worker's 4K context window.
- **D-02:** Rationale snippets truncated at 80 characters, consistent with Phase 6's `_sanitize_rationale()` pattern. Same sanitization applied (strip control chars, normalize whitespace).
- **D-03:** Peer context includes a header indicating which round's decisions are being shown (e.g., "Peer Decisions (Round 1)").
- **D-04:** Single `run_simulation()` top-level async function orchestrating all 3 rounds. Calls existing `run_round1()` for the first round (preserving it as a standalone function), then handles Rounds 2-3 inline with the worker model staying loaded.
- **D-05:** Worker model reloaded once after `run_round1()` returns (since `run_round1()` unloads in its finally block). Worker stays loaded for both Rounds 2-3 -- no reload between them. One cold load cost for preserving modularity.
- **D-06:** Governor monitoring spans Rounds 2-3 dispatch. `run_round1()` manages its own governor lifecycle; `run_simulation()` starts a fresh monitoring session for the Rounds 2-3 phase.
- **D-07:** SimulationPhase state machine transitions: IDLE -> SEEDING -> ROUND_1 -> ROUND_2 -> ROUND_3 -> COMPLETE. Phase transitions logged via structlog but not persisted to a SharedStateStore (deferred until TUI needs it).
- **D-08:** `SimulationResult` frozen dataclass containing Round1Result + per-round agent_decisions + shift metrics. Single canonical result container for the full simulation.
- **D-09:** For Round 2: read top-5 peer decisions from Round 1 for each agent via `read_peer_decisions(agent_id, cycle_id, round_num=1)`. For Round 3: same but `round_num=2`. Each agent gets personalized peer context (excluding self).
- **D-10:** Peer reads happen per-agent BEFORE dispatch, serialized into the peer_context string. The formatting function builds the context string, then `dispatch_wave()` receives it as the `peer_context` kwarg.
- **D-11:** Signal flips tracked between rounds: count agents who changed signal (BUY->SELL, SELL->HOLD, etc.) with a transition breakdown.
- **D-12:** Confidence delta computed per bracket: average confidence change between rounds. Reported alongside the bracket table after each round.
- **D-13:** Shift metrics computed by comparing Round N-1 and Round N agent_decisions. No Neo4j query needed -- done in-memory from the result containers.
- **D-14:** Per-round bracket tables printed as each round completes, reusing the `_print_round1_report()` pattern. Users see progressive output during the ~10 minute simulation.
- **D-15:** Shift analysis section added after Round 2 and Round 3 reports showing signal change counts and per-bracket confidence drift.
- **D-16:** Final "Simulation Complete" summary with total signal flips across rounds, convergence indicator, and final bracket consensus distribution.
- **D-17:** The existing `run` CLI subcommand evolves to run the full 3-round simulation (not just Round 1). `_handle_run()` calls `run_simulation()` instead of `run_round1()`.

### Claude's Discretion
- Internal helper function structure within `run_simulation()` (e.g., `_dispatch_round()`, `_format_peer_context()`, `_compute_shifts()`)
- Whether to parallelize peer reads across agents or serialize them (token budget vs Neo4j load)
- SimulationResult field naming and structure beyond the core round results
- Exact formatting of shift analysis output (column widths, alignment)
- How to handle the case where ALL 100 agents get the same top-5 peers (static ranking makes this likely -- acceptable until Phase 8 dynamic topology)
- Whether run_round1() standalone mode needs a separate CLI flag or just works as before

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIM-05 | Round 2 (Peer Influence) -- agents receive top-5 influential peer decisions from Round 1 and re-evaluate their position | `read_peer_decisions()` already implemented with static `influence_weight_base` ranking. `dispatch_wave()` accepts `peer_context` kwarg. `AgentWorker.infer()` injects peer context as second system message. |
| SIM-06 | Round 3 (Final Consensus Lock) -- agents receive updated peer decisions from Round 2 and produce final locked positions | Same infrastructure as SIM-05 with `round_num=2`. `SimulationResult` frozen dataclass prevents mutation after Round 3 completes. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

| Directive | Enforcement |
|-----------|-------------|
| 100% async (`asyncio`), no blocking I/O on main event loop | All pipeline functions must be async. `_handle_run()` is sync wrapper that calls `asyncio.run()`. |
| Local first, all inference via Ollama, max 2 models loaded simultaneously | Worker model is the only model loaded during Rounds 2-3. Orchestrator unloaded after seed injection. |
| Memory safety: monitor RAM via `psutil`, throttle at 80%, pause at 90% | Governor monitoring spans Rounds 2-3 dispatch per D-06. |
| Python 3.11+, strict typing, `uv`, `pytest-asyncio` | All new code uses type annotations. Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. |
| `structlog` for logging | Component-scoped loggers with `structlog.get_logger(component="simulation")`. |
| Frozen Pydantic models for domain types | `SimulationResult` as frozen dataclass per established pattern. |

## Standard Stack

### Core (already installed, no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` | stdlib | Async pipeline orchestration | Project hard constraint: 100% async |
| `structlog` | >=25.5.0 | Component-scoped logging with phase transitions | Established pattern from Phase 1 |
| `neo4j` (async driver) | >=5.28 | Peer decision reads via `read_peer_decisions()` | Established from Phase 4 |

### Supporting (already installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses` | stdlib | `SimulationResult` frozen container | Result type for full simulation |
| `pydantic` | >=2.12.5 | Existing `AgentDecision`, `AgentPersona` models | No new Pydantic models needed |

No new package installations required for this phase.

## Architecture Patterns

### Recommended Changes to Project Structure
```
src/alphaswarm/
    simulation.py      # ADD: run_simulation(), SimulationResult, _format_peer_context(), _dispatch_round(), _compute_shifts()
    cli.py             # MODIFY: _run_pipeline() calls run_simulation(), add _print_round_report(), _print_shift_analysis(), _print_simulation_summary()
    graph.py           # NO CHANGE (read_peer_decisions already implemented)
    batch_dispatcher.py # NO CHANGE (dispatch_wave already accepts peer_context)
    worker.py          # NO CHANGE (infer already handles peer_context)
    types.py           # NO CHANGE (SimulationPhase enum already defined)
```

### Pattern 1: Pipeline Orchestrator (run_simulation)
**What:** Top-level async function that composes existing pipeline functions into a 3-round cascade.
**When to use:** Single entry point for the full simulation lifecycle.
**Example:**
```python
# Source: Derived from existing run_round1() pattern in simulation.py
@dataclasses.dataclass(frozen=True)
class SimulationResult:
    """Immutable result container for the full 3-round simulation."""
    cycle_id: str
    parsed_result: ParsedSeedResult
    round1_decisions: list[tuple[str, AgentDecision]]
    round2_decisions: list[tuple[str, AgentDecision]]
    round3_decisions: list[tuple[str, AgentDecision]]
    round2_shifts: ShiftMetrics
    round3_shifts: ShiftMetrics

async def run_simulation(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    personas: list[AgentPersona],
) -> SimulationResult:
    """Execute the full 3-round simulation pipeline."""
    phase = SimulationPhase.IDLE
    logger.info("simulation_start", phase=phase.value)

    # Phase: SEEDING + ROUND_1 (delegated to run_round1)
    phase = SimulationPhase.SEEDING
    round1_result = await run_round1(
        rumor, settings, ollama_client, model_manager,
        graph_manager, governor, personas,
    )
    # run_round1 unloads worker in its finally block

    # Reload worker for Rounds 2-3 (D-05)
    await model_manager.ensure_clean_state()
    worker_alias = settings.ollama.worker_model_alias

    await governor.start_monitoring()
    try:
        await model_manager.load_model(worker_alias)
        try:
            # Round 2
            phase = SimulationPhase.ROUND_2
            round2_decisions = await _dispatch_round(...)
            await graph_manager.write_decisions(round2_decisions, cycle_id, round_num=2)

            # Round 3
            phase = SimulationPhase.ROUND_3
            round3_decisions = await _dispatch_round(...)
            await graph_manager.write_decisions(round3_decisions, cycle_id, round_num=3)
        finally:
            await model_manager.unload_model(worker_alias)
    finally:
        await governor.stop_monitoring()

    phase = SimulationPhase.COMPLETE
    return SimulationResult(...)
```

### Pattern 2: Per-Agent Peer Context Assembly
**What:** For each agent, read top-5 peer decisions from Neo4j and format into a context string before dispatch.
**When to use:** Before each dispatch_wave call in Rounds 2-3.
**Example:**
```python
# Source: Derived from CONTEXT.md D-01, D-02, D-03, D-09, D-10
def _format_peer_context(
    peers: list[PeerDecision],
    source_round: int,
) -> str:
    """Format top-5 peer decisions into a context string for injection.

    Format per D-01: [Bracket] SIGNAL (conf: X.XX) "rationale snippet..."
    Header per D-03: "Peer Decisions (Round N)"
    Truncation per D-02: 80-char rationale via _sanitize_rationale()
    """
    lines = [f"Peer Decisions (Round {source_round}):"]
    for i, peer in enumerate(peers, 1):
        snippet = _sanitize_rationale(peer.rationale, max_len=80)
        lines.append(
            f"{i}. [{peer.bracket}] {peer.signal.upper()} "
            f"(conf: {peer.confidence:.2f}) \"{snippet}\""
        )
    return "\n".join(lines)
```

### Pattern 3: dispatch_wave with Per-Agent Peer Context
**What:** Current `dispatch_wave()` accepts a single `peer_context` string applied to ALL agents. For Rounds 2-3, each agent needs a DIFFERENT peer context string (personalized top-5 excluding self).
**When to use:** This is the critical design decision for this phase.
**Recommendation:** Do NOT modify `dispatch_wave()` signature. Instead, create a `_dispatch_round()` helper that:
1. For each persona, calls `read_peer_decisions()` to get their personalized top-5
2. Formats the peer context string
3. Calls `dispatch_wave()` once per agent with their individual context -- OR -- creates individual tasks inside a TaskGroup.

**Critical insight:** The current `dispatch_wave()` applies the SAME `peer_context` to all agents. For Rounds 2-3, each agent gets DIFFERENT peer context. Two approaches:

**Option A: Modify dispatch_wave to accept per-agent context**
```python
async def dispatch_wave(
    personas: list[WorkerPersonaConfig],
    ...,
    peer_contexts: list[str | None] | None = None,  # NEW: per-agent
    peer_context: str | None = None,  # Backward compat: same for all
) -> list[AgentDecision]:
```

**Option B: Build per-agent dispatch in _dispatch_round()**
```python
async def _dispatch_round(
    personas: list[AgentPersona],
    cycle_id: str,
    source_round: int,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    rumor: str,
    settings: GovernorSettings,
) -> list[tuple[str, AgentDecision]]:
    """Dispatch a round with per-agent peer context."""
    worker_configs = [persona_to_worker_config(p) for p in personas]

    # Read peer context for all agents (parallelizable)
    peer_contexts: list[str] = []
    for persona in personas:
        peers = await graph_manager.read_peer_decisions(
            persona.id, cycle_id, source_round, limit=5,
        )
        peer_contexts.append(_format_peer_context(peers, source_round))

    # Dispatch with per-agent context
    # ... use TaskGroup with individual _safe_agent_inference calls
```

**Recommended: Option A** -- it minimizes code duplication and keeps the TaskGroup/jitter/failure-tracking logic in one place. Add `peer_contexts: list[str | None] | None = None` parameter to `dispatch_wave()`. When provided, it overrides the scalar `peer_context` on a per-agent basis. This is a backward-compatible additive change.

### Pattern 4: Opinion Shift Metrics (Pure Function)
**What:** Compare two rounds of agent decisions and compute signal flip counts and per-bracket confidence deltas.
**When to use:** After each subsequent round completes.
**Example:**
```python
@dataclasses.dataclass(frozen=True)
class ShiftMetrics:
    """Metrics comparing decisions between two consecutive rounds."""
    signal_flips: dict[str, int]   # e.g., {"BUY->SELL": 3, "SELL->HOLD": 2}
    total_flips: int
    bracket_confidence_delta: dict[str, float]  # bracket -> avg confidence change
    agents_shifted: int  # count of agents who changed signal

def _compute_shifts(
    prev_decisions: list[tuple[str, AgentDecision]],
    curr_decisions: list[tuple[str, AgentDecision]],
    personas: list[AgentPersona],
) -> ShiftMetrics:
    """Compute opinion shift metrics between two rounds (D-11, D-12, D-13)."""
    prev_map = {aid: dec for aid, dec in prev_decisions}
    curr_map = {aid: dec for aid, dec in curr_decisions}
    # ... pure comparison logic
```

### Anti-Patterns to Avoid
- **Reading peer decisions inside dispatch_wave:** Peer reads MUST happen BEFORE dispatch, not during. Mixing Neo4j reads with Ollama inference inside the TaskGroup adds contention and makes error handling complex. Per D-10: "Peer reads happen per-agent BEFORE dispatch."
- **Reloading worker model between Round 2 and Round 3:** Per D-05, the worker stays loaded for both rounds. Only one cold reload after `run_round1()` returns.
- **Persisting SimulationPhase to StateStore:** Per D-07, transitions are logged via structlog only. StateStore persistence is deferred to TUI phase.
- **Computing shifts via Neo4j queries:** Per D-13, shift metrics are computed in-memory from the result containers. No extra Neo4j reads needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Peer decision ranking | Custom sorting/filtering | `read_peer_decisions()` in graph.py | Already implemented with proper Cypher, self-exclusion, and influence_weight_base ordering |
| Batch agent dispatch | Custom TaskGroup logic | `dispatch_wave()` in batch_dispatcher.py | Already handles jitter, governor slots, failure tracking, and exception safety |
| Rationale truncation | Custom string trimming | `_sanitize_rationale()` in cli.py | Already handles control chars, whitespace normalization, and truncation with "..." |
| Model lifecycle | Manual load/unload | `OllamaModelManager.load_model()` / `unload_model()` | Already handles Lock serialization, ps() verification, and error wrapping |
| Bracket aggregation | Custom counting | `_aggregate_brackets()` in cli.py | Already handles PARSE_ERROR exclusion, bracket ordering, and confidence averaging |

**Key insight:** This phase is primarily a composition phase. Every primitive needed already exists and is tested. The work is orchestrating them correctly and adding the thin formatting/reporting layers.

## Common Pitfalls

### Pitfall 1: Per-Agent vs Global Peer Context in dispatch_wave
**What goes wrong:** Using the existing `peer_context: str | None` parameter in `dispatch_wave()` sends the SAME peer context to all 100 agents. Each agent needs their OWN top-5 peers (excluding themselves).
**Why it happens:** The Round 1 dispatch used `peer_context=None` for all agents. The interface worked fine for the uniform case.
**How to avoid:** Either extend `dispatch_wave()` with a `peer_contexts: list[str | None] | None` parameter, or build a new helper that creates individual tasks. The former is cleaner.
**Warning signs:** All agents cite the same rationales in their responses; self-citations appear.

### Pitfall 2: Static Influence Ranking Produces Identical Top-5 for All Agents
**What goes wrong:** With static `influence_weight_base`, the top-5 peers for almost every agent are the same 5 Sovereigns (weight 0.90). This creates a homogeneous influence signal.
**Why it happens:** `read_peer_decisions()` orders by `a.influence_weight_base DESC`. Sovereigns have 0.90, Whales have 0.85, Suits 0.80. The top-5 for any non-Sovereign is always 5 of the 10 Sovereigns (order within same weight depends on Neo4j internal ordering).
**How to avoid:** This is EXPLICITLY ACCEPTABLE per CONTEXT.md discretion note: "acceptable until Phase 8 dynamic topology." Do NOT try to fix this in Phase 7. However, the shift analysis will likely show muted diversity -- this is expected.
**Warning signs:** All 90 non-Sovereign agents shift toward whatever the Sovereigns decided. This is by design for now.

### Pitfall 3: Neo4j Session Exhaustion from 100 Peer Reads
**What goes wrong:** Reading peer decisions for 100 agents sequentially opens 100 Neo4j sessions (session-per-method pattern). If done carelessly with asyncio.gather, this could exhaust the connection pool (max 50).
**Why it happens:** `read_peer_decisions()` opens a new session per call. 100 concurrent calls would need 100 connections.
**How to avoid:** Serialize peer reads or batch them with a semaphore. Sequential reads for 100 agents should complete in <2 seconds total (sub-5ms per read per INFRA-05 index specification). Parallelizing provides minimal benefit given Neo4j is local Docker.
**Warning signs:** `Neo4jConnectionError` during peer context assembly; connection pool timeout errors.

### Pitfall 4: Governor Lifecycle Mismatch
**What goes wrong:** `run_round1()` starts AND stops its own governor monitoring. If `run_simulation()` also starts monitoring before calling `run_round1()`, there would be nested monitoring sessions.
**Why it happens:** The decision (D-06) specifies `run_round1()` manages its own governor lifecycle, and `run_simulation()` starts a FRESH session for Rounds 2-3.
**How to avoid:** `run_simulation()` does NOT start monitoring before `run_round1()`. It calls `run_round1()` first (which manages its own session), then starts a new monitoring session for the Rounds 2-3 block.
**Warning signs:** Double `start_monitoring` calls; `_monitor_task` already running when `start_monitoring` is called.

### Pitfall 5: Forgetting ensure_clean_state Before Worker Reload
**What goes wrong:** After `run_round1()` returns, the worker model should be unloaded (its finally block does this). But defensive `ensure_clean_state()` is needed before reloading, per the Phase 6 pattern.
**Why it happens:** `run_round1()` unloads in its finally block, but if that unload failed silently, the worker could still be loaded.
**How to avoid:** Call `model_manager.ensure_clean_state()` before `load_model()` in `run_simulation()`, mirroring the existing pattern in `run_round1()`.
**Warning signs:** `ModelLoadError` when reloading worker; unexpected memory pressure from stale model.

### Pitfall 6: Misaligned Agent IDs Between Rounds
**What goes wrong:** Round 2/3 decisions must be paired with the same agent_ids as Round 1. If the persona list order changes or agent_ids don't match, shift metrics and Neo4j writes will be incorrect.
**Why it happens:** `dispatch_wave()` returns results positionally aligned with the input persona list. If a different persona list is passed, alignment breaks.
**How to avoid:** Use the SAME `personas` list for all 3 rounds. Use the SAME `worker_configs` list derived from it. Assert length alignment after each dispatch.
**Warning signs:** Shift metrics show 100% flips (every agent appears to have changed); Neo4j agent_id mismatches.

## Code Examples

### Peer Context String Format (D-01, D-02, D-03)
```python
# Source: CONTEXT.md D-01, D-02, D-03 specification
# Expected output for a single agent's peer context:

"""
Peer Decisions (Round 1):
1. [sovereigns] HOLD (conf: 0.90) "Capital preservation mandate suggests wait-and-see approach given..."
2. [sovereigns] HOLD (conf: 0.87) "Strategic patience; quantum computing commercialization timeline ex..."
3. [whales] BUY (conf: 0.85) "Generational technology shift warrants early accumulation at curr..."
4. [suits] HOLD (conf: 0.82) "Consensus view is premature to position; awaiting sell-side cover..."
5. [insiders] BUY (conf: 0.78) "Supply chain intelligence confirms production ramp ahead of sche..."
"""
```

### SimulationResult Frozen Dataclass
```python
# Source: Pattern from Round1Result in simulation.py
@dataclasses.dataclass(frozen=True)
class ShiftMetrics:
    """Opinion shift metrics between two consecutive rounds."""
    signal_transitions: dict[str, int]  # "BUY->SELL": count
    total_flips: int
    bracket_confidence_delta: dict[str, float]
    agents_shifted: int

@dataclasses.dataclass(frozen=True)
class SimulationResult:
    """Immutable result for the full 3-round simulation."""
    cycle_id: str
    parsed_result: ParsedSeedResult
    round1_decisions: list[tuple[str, AgentDecision]]
    round2_decisions: list[tuple[str, AgentDecision]]
    round3_decisions: list[tuple[str, AgentDecision]]
    round2_shifts: ShiftMetrics
    round3_shifts: ShiftMetrics
```

### Shift Analysis CLI Output Format
```python
# Source: CONTEXT.md D-11, D-12, D-15
# Expected output after Round 2:

"""
  Signal Transitions (Round 1 -> Round 2)
  ----------------------------------------
  BUY -> SELL:  3      SELL -> BUY:  2
  BUY -> HOLD:  5      SELL -> HOLD: 1
  HOLD -> BUY:  4      HOLD -> SELL: 2
  Total agents shifted: 17/100

  Confidence Drift by Bracket
  ----------------------------------------
  Quants          +0.05
  Degens          -0.12
  Sovereigns      +0.02
  ...
"""
```

### dispatch_wave Extension for Per-Agent Context
```python
# Source: Extension of existing batch_dispatcher.py pattern
async def dispatch_wave(
    personas: list[WorkerPersonaConfig],
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    user_message: str,
    settings: GovernorSettings,
    *,
    peer_context: str | None = None,
    peer_contexts: list[str | None] | None = None,  # NEW: per-agent
) -> list[AgentDecision]:
    """Dispatch with optional per-agent peer context.

    If peer_contexts is provided, it MUST have the same length as personas.
    Each agent gets their individual context. peer_context is ignored when
    peer_contexts is provided.
    """
    if peer_contexts is not None:
        assert len(peer_contexts) == len(personas)

    tasks: list[asyncio.Task[AgentDecision]] = []
    async with asyncio.TaskGroup() as tg:
        for i, p in enumerate(personas):
            ctx = peer_contexts[i] if peer_contexts is not None else peer_context
            tasks.append(
                tg.create_task(
                    _safe_agent_inference(
                        p, governor, client, model, user_message, ctx,
                        settings.jitter_min_seconds, settings.jitter_max_seconds,
                    )
                )
            )
    # ... rest unchanged
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `dispatch_wave(peer_context=None)` | `dispatch_wave(peer_contexts=[...])` per-agent | Phase 7 | Enables personalized peer influence |
| `run_round1()` standalone | `run_simulation()` orchestrating 3 rounds | Phase 7 | Full consensus cascade |
| `_print_round1_report()` only | Generalized `_print_round_report()` + shift analysis | Phase 7 | Progressive multi-round reporting |
| CLI `run` = Round 1 only | CLI `run` = full 3-round simulation | Phase 7 | Complete end-to-end workflow |

## Open Questions

1. **Peer read parallelism vs serialization**
   - What we know: 100 agents need peer reads. Each read is sub-5ms per Neo4j index. Connection pool is 50.
   - What's unclear: Whether sequential (safe, simple, ~500ms total) or batched parallel (faster but connection pool risk) is better.
   - Recommendation: Serialize by default. 500ms overhead is negligible in a 10-minute simulation. If it becomes a bottleneck, add a semaphore-limited gather.

2. **Neo4j ordering within same influence_weight_base**
   - What we know: Multiple agents share the same weight (e.g., 10 Sovereigns at 0.90). Neo4j does not guarantee stable ordering for ties.
   - What's unclear: Whether the same agent gets different top-5 Sovereigns across runs.
   - Recommendation: Accept non-deterministic tie-breaking. Phase 8 introduces dynamic weights that eliminate this issue. No action needed in Phase 7.

3. **Echo chamber convergence**
   - What we know: STATE.md flags this as a known concern. Static influence weights bias toward Sovereigns who are inherently conservative (HOLD-biased).
   - What's unclear: Whether the shift analysis will show meaningful diversity or just universal convergence toward HOLD.
   - Recommendation: This is by design for Phase 7. The shift analysis will quantify the convergence. Phase 8's dynamic topology is the solution.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_simulation.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-05-a | `_format_peer_context()` produces correct format with header, 5 entries, truncated rationale | unit | `uv run pytest tests/test_simulation.py::test_format_peer_context_structure -x` | Wave 0 |
| SIM-05-b | `_dispatch_round()` reads peer decisions per-agent and passes to dispatch_wave | unit | `uv run pytest tests/test_simulation.py::test_dispatch_round_reads_peers_per_agent -x` | Wave 0 |
| SIM-05-c | `dispatch_wave()` with `peer_contexts` list sends per-agent context | unit | `uv run pytest tests/test_batch_dispatcher.py::test_dispatch_wave_per_agent_peer_contexts -x` | Wave 0 |
| SIM-05-d | `run_simulation()` executes Round 2 with peer context from Round 1 decisions | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_round2_uses_round1_peers -x` | Wave 0 |
| SIM-06-a | `run_simulation()` executes Round 3 with peer context from Round 2 decisions | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_round3_uses_round2_peers -x` | Wave 0 |
| SIM-06-b | `run_simulation()` returns SimulationResult with all 3 rounds of decisions | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_returns_complete_result -x` | Wave 0 |
| SIM-06-c | `SimulationResult` is frozen dataclass with correct fields | unit | `uv run pytest tests/test_simulation.py::test_simulation_result_is_frozen -x` | Wave 0 |
| SIM-06-d | `write_decisions()` called with round_num=2 and round_num=3 | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_persists_all_rounds -x` | Wave 0 |
| SHIFT-a | `_compute_shifts()` detects signal flips between rounds | unit | `uv run pytest tests/test_simulation.py::test_compute_shifts_signal_flips -x` | Wave 0 |
| SHIFT-b | `_compute_shifts()` computes per-bracket confidence delta | unit | `uv run pytest tests/test_simulation.py::test_compute_shifts_bracket_confidence -x` | Wave 0 |
| STATE-a | SimulationPhase transitions through all states in order | unit | `uv run pytest tests/test_simulation.py::test_simulation_phase_transitions -x` | Wave 0 |
| MODEL-a | Worker model reloaded once after run_round1, stays loaded for Rounds 2-3 | unit | `uv run pytest tests/test_simulation.py::test_worker_reload_once_for_rounds_2_3 -x` | Wave 0 |
| GOV-a | Governor monitoring started for Rounds 2-3 block (separate from Round 1 session) | unit | `uv run pytest tests/test_simulation.py::test_governor_fresh_session_rounds_2_3 -x` | Wave 0 |
| CLI-a | `_run_pipeline()` calls `run_simulation()` instead of `run_round1()` | unit | `uv run pytest tests/test_cli.py::test_run_pipeline_calls_run_simulation -x` | Wave 0 |
| CLI-b | Shift analysis printed after Round 2 and Round 3 | unit | `uv run pytest tests/test_cli.py::test_shift_analysis_output -x` | Wave 0 |
| CLI-c | Final simulation summary printed with convergence indicator | unit | `uv run pytest tests/test_cli.py::test_simulation_summary_output -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_simulation.py tests/test_batch_dispatcher.py tests/test_cli.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_simulation.py` -- extend with `run_simulation()`, `SimulationResult`, `_format_peer_context()`, `_dispatch_round()`, `_compute_shifts()`, `ShiftMetrics` tests
- [ ] `tests/test_batch_dispatcher.py` -- extend with `peer_contexts` list parameter test
- [ ] `tests/test_cli.py` -- extend with shift analysis and simulation summary output tests
- [ ] No new test files needed -- all tests extend existing files
- [ ] No framework install needed -- pytest-asyncio already configured

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/simulation.py` -- existing `run_round1()` pattern, `Round1Result` dataclass
- `src/alphaswarm/graph.py` -- `read_peer_decisions()` implementation, `PeerDecision` dataclass, Cypher query with influence_weight_base ordering
- `src/alphaswarm/batch_dispatcher.py` -- `dispatch_wave()` with `peer_context` parameter
- `src/alphaswarm/worker.py` -- `AgentWorker.infer()` peer context injection as second system message
- `src/alphaswarm/cli.py` -- `_print_round1_report()`, `_aggregate_brackets()`, `_sanitize_rationale()` patterns
- `src/alphaswarm/types.py` -- `SimulationPhase` enum, `AgentDecision`, `SignalType`
- `src/alphaswarm/config.py` -- `DEFAULT_BRACKETS` with influence_weight_base values per bracket
- `tests/test_simulation.py` -- existing test patterns for mocking pipeline dependencies

### Secondary (MEDIUM confidence)
- `.planning/phases/07-rounds-2-3-peer-influence-and-consensus/07-CONTEXT.md` -- all locked decisions and specifications
- `.planning/REQUIREMENTS.md` -- SIM-05, SIM-06 requirement definitions
- `.planning/STATE.md` -- echo chamber concern, accumulated project decisions

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies, all primitives exist and are tested
- Architecture: HIGH - clear composition of existing patterns, all decisions locked in CONTEXT.md
- Pitfalls: HIGH - identified from direct code reading and established project patterns

**Research date:** 2026-03-26
**Valid until:** 2026-04-25 (30 days - stable internal codebase, no external dependency changes)
