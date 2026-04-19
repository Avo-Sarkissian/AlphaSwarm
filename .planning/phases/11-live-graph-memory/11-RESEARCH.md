# Phase 11: Live Graph Memory - Research

**Researched:** 2026-03-31
**Domain:** Neo4j graph enrichment, async write-behind buffering, narrative entity matching
**Confidence:** HIGH

## Summary

Phase 11 extends the existing Neo4j graph schema and GraphStateManager to capture per-agent reasoning arcs during simulation. The implementation builds on three proven patterns already in the codebase: (1) UNWIND batch writes from `write_decisions()`, (2) post-round computation from `compute_influence_edges()`, and (3) async queue buffering from StateStore's `_rationale_queue`. No new dependencies are required. All new code extends `graph.py`, `simulation.py`, and `types.py` with a single new module `write_buffer.py`.

The core technical challenge is integrating a write-behind buffer into the simulation loop without disrupting the existing write path. The decision to keep existing `write_decisions()` untouched (D-03) and add new writes alongside it is the correct approach -- it preserves the proven v1 code path while adding enrichment. The entity matching for REFERENCES edges uses case-insensitive substring matching against clean entity names from seed injection, requiring no NLP dependencies.

Post-simulation narrative generation (D-10, D-11) adds ~100 inference calls through the governor using the already-loaded worker model. This is the only computationally expensive operation in this phase and should be gated by a flag for test skipping.

**Primary recommendation:** Follow the existing `write_decisions()` UNWIND pattern exactly. New writes (RationaleEpisode, REFERENCES edges, decision narratives) are separate Cypher statements within the same flush transaction, keeping total transaction count under 10 per round as required by success criteria.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Async queue + flush-per-round pattern. Agents push decisions into an asyncio.Queue as they complete. A single flush task drains the queue and writes via UNWIND batch after each round completes. TUI sees per-agent updates immediately via StateStore; Neo4j receives efficient batch writes at round boundaries.
- **D-02:** Standalone WriteBuffer class, separate from GraphStateManager. Buffer handles queueing logic; GraphStateManager handles Cypher operations. Clean separation, independently testable.
- **D-03:** Buffer handles new writes only (RationaleEpisode + narrative REFERENCES). Existing `write_decisions()` stays as-is -- proven batch UNWIND code path is not refactored.
- **D-04:** RationaleEpisode linked via `(:Decision)-[:HAS_EPISODE]->(:RationaleEpisode)`. One-to-one with Decision. Preserves the Agent->MADE->Decision->FOR->Cycle chain from Phase 4 D-01.
- **D-05:** Full peer context string stored on RationaleEpisode. The complete formatted peer context string injected into the agent's prompt is persisted as `peer_context_received` property. ~500-800 bytes per episode.
- **D-06:** Signal flip detection via flip_type enum. A `flip_type` field on RationaleEpisode stores the transition type (e.g., NONE, BUY_TO_SELL, SELL_TO_BUY, etc.). Round 1 episodes have flip_type=NONE. Computed at write time by comparing to the same agent's previous round Decision.
- **D-07:** RationaleEpisode node properties: rationale (text), timestamp (datetime), peer_context_received (str), flip_type (str, enum value), round (int), cycle_id (str).
- **D-08:** Case-insensitive substring matching for Decision-to-Entity REFERENCES edges. Entity names from seed injection are already clean. No NLP dependencies.
- **D-09:** REFERENCES edges created during flush, piggybacking on the same post-round UNWIND transaction. Entity names loaded once at cycle start and reused across all rounds.
- **D-10:** LLM-generated decision narrative summary stored as `decision_narrative` property on Agent nodes post-simulation. Worker model generates per-agent narrative.
- **D-11:** Narrative generation runs post-simulation as a batch of 100 inference calls through the governor. Estimated ~3-4 min with governor throttling on M1 Max.

### Claude's Discretion
- WriteBuffer internal implementation details (queue size limits, flush error handling, retry logic)
- FlipType enum design (Python StrEnum, naming convention, where it lives in types.py)
- RationaleEpisode Neo4j index strategy (composite index on cycle_id + round, or single field)
- Entity name caching strategy (in-memory dict vs re-query per round)
- Narrative generation prompt design and output format
- GraphStateManager new method signatures for episode writes, narrative edge writes, and narrative generation
- How narrative generation integrates with the post-simulation flow (after write_decisions Round 3, before COMPLETE phase transition)
- Error handling for partial narrative generation failures (skip agent vs retry)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRAPH-01 | Agent decisions are written to Neo4j individually in real time during simulation (per-agent immediate writes via write-behind buffer, not batch-per-round) | WriteBuffer class with asyncio.Queue collects per-agent decisions as they complete; flush drains queue into UNWIND batch at round boundary. TUI sees immediate updates via StateStore (existing pattern). Neo4j receives efficient batch writes. |
| GRAPH-02 | RationaleEpisode nodes link Agent -> Round -> Rationale with timestamps, peer context received, and signal flip detection | RationaleEpisode nodes linked via `(:Decision)-[:HAS_EPISODE]->(:RationaleEpisode)` with properties: rationale, timestamp (Neo4j `datetime()`), peer_context_received, flip_type (FlipType enum), round, cycle_id. FlipType computed by comparing previous round's signal. |
| GRAPH-03 | Narrative REFERENCES edges connect Decision nodes to Entity nodes via keyword matching against extracted entities | `(:Decision)-[:REFERENCES {match_type: "substring"}]->(:Entity)` edges created during flush. Case-insensitive `toLower(d.rationale) CONTAINS toLower(entity.name)` matching. Entity names loaded once per cycle. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop. WriteBuffer MUST use async queue and async flush.
- **Local First:** All inference local via Ollama. Narrative generation uses worker model already loaded post-simulation.
- **Memory Safety:** Monitor RAM via `psutil`. Narrative generation (100 inference calls) must go through ResourceGovernor for throttling.
- **Runtime:** Python 3.11+ (strict typing), `uv`, `pytest-asyncio`.
- **Neo4j:** Community Edition (Docker) via `neo4j` async driver. Session-per-method pattern. UNWIND batch writes.
- **Validation/Config:** `pydantic` for data models.
- **Logging:** `structlog` with component-scoped loggers.
- **Test runner:** `pytest-asyncio` with `asyncio_mode = "auto"`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| neo4j | >=5.28,<6.0 | Async graph database driver | Already in use, session-per-method pattern established |
| asyncio | stdlib | Write-behind queue, async flush | Project convention, matches StateStore pattern |
| structlog | >=25.5.0 | Component-scoped logging | Already in use across all modules |
| pydantic | >=2.12.5 | FlipType validation if needed | Already in use for all data models |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | >=0.24.0 | Async test infrastructure | Testing WriteBuffer flush, GraphStateManager new methods |
| pytest | >=8.0 | Unit test runner | All new tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncio.Queue for WriteBuffer | collections.deque with manual locking | Queue is the established pattern in StateStore; deque would require explicit Lock management |
| Case-insensitive substring in Python | Neo4j `toLower()` + `CONTAINS` in Cypher | Both work; Python-side matching avoids N*M cross-product in Cypher UNWIND. Recommend Python-side for REFERENCES edge construction, then UNWIND the matched pairs |
| `(str, Enum)` for FlipType | `StrEnum` (Python 3.11+) | StrEnum is available (Python 3.11.5 confirmed) but existing codebase uses `(str, Enum)`. Follow existing convention for consistency |

**Installation:**
```bash
# No new dependencies required -- all libraries already in pyproject.toml
```

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
    types.py          # + FlipType enum (7 values)
    write_buffer.py   # NEW: standalone WriteBuffer class (D-02)
    graph.py          # + write_rationale_episodes(), write_narrative_edges(),
                      #   write_decision_narratives(), read_cycle_entities()
    simulation.py     # + WriteBuffer integration in run_simulation(),
                      #   + post-simulation narrative generation
tests/
    test_write_buffer.py   # NEW: WriteBuffer unit tests
    test_graph.py          # + tests for new GraphStateManager methods
    test_simulation.py     # + tests for WriteBuffer integration, narrative generation
```

### Pattern 1: Write-Behind Buffer (D-01, D-02)
**What:** Standalone `WriteBuffer` class wrapping `asyncio.Queue`. Simulation pushes per-agent episode data as agents complete. A `flush()` method drains the queue and delegates to GraphStateManager for UNWIND batch writes.
**When to use:** After each round completes, between `write_decisions()` and `compute_influence_edges()`.
**Example:**
```python
# Source: Adapted from existing StateStore._rationale_queue pattern (state.py:109)
import asyncio
from dataclasses import dataclass

@dataclass(frozen=True)
class EpisodeRecord:
    """Immutable record for write-behind buffer queue."""
    decision_id: str      # Links to parent Decision node
    agent_id: str
    rationale: str
    peer_context_received: str  # Full formatted context string
    flip_type: str        # FlipType enum value
    round_num: int
    cycle_id: str

class WriteBuffer:
    """Write-behind buffer for RationaleEpisode graph writes (D-01, D-02).

    Agents push EpisodeRecords as they complete inference.
    flush() drains queue and delegates batch write to GraphStateManager.
    """
    def __init__(self, maxsize: int = 200) -> None:
        self._queue: asyncio.Queue[EpisodeRecord] = asyncio.Queue(maxsize=maxsize)
        self._log = structlog.get_logger(component="write_buffer")

    async def push(self, record: EpisodeRecord) -> None:
        """Non-blocking push. Drop oldest if full (same pattern as StateStore)."""
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(record)

    def drain(self) -> list[EpisodeRecord]:
        """Drain all records from queue. Returns empty list if empty."""
        records: list[EpisodeRecord] = []
        while not self._queue.empty():
            try:
                records.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return records

    async def flush(
        self,
        graph_manager: GraphStateManager,
        entity_names: list[str],
    ) -> int:
        """Drain queue and write to Neo4j via GraphStateManager.

        Returns number of records flushed.
        """
        records = self.drain()
        if not records:
            return 0
        await graph_manager.write_rationale_episodes(records)
        await graph_manager.write_narrative_edges(records, entity_names)
        return len(records)
```

### Pattern 2: UNWIND Batch Write for RationaleEpisode (D-04, D-07)
**What:** New `write_rationale_episodes()` method on GraphStateManager following the exact same pattern as `write_decisions()` (line 249-336 of graph.py).
**When to use:** Called by WriteBuffer.flush() after each round.
**Example:**
```python
# Source: Follows existing write_decisions() pattern in graph.py:285-336
@staticmethod
async def _batch_write_episodes_tx(
    tx: AsyncManagedTransaction,
    episodes: list[dict],
    cycle_id: str,
    round_num: int,
) -> None:
    """UNWIND batch create RationaleEpisode nodes linked to Decision nodes."""
    await tx.run(
        """
        UNWIND $episodes AS ep
        MATCH (d:Decision {decision_id: ep.decision_id})
        CREATE (re:RationaleEpisode {
            rationale: ep.rationale,
            timestamp: datetime(),
            peer_context_received: ep.peer_context_received,
            flip_type: ep.flip_type,
            round: $round_num,
            cycle_id: $cycle_id
        })
        CREATE (d)-[:HAS_EPISODE]->(re)
        """,
        episodes=episodes,
        cycle_id=cycle_id,
        round_num=round_num,
    )
```

### Pattern 3: Python-Side Entity Matching + Cypher UNWIND for REFERENCES (D-08, D-09)
**What:** Entity substring matching done in Python (fast, simple, no Cypher cross-product). Matched pairs are then written via UNWIND.
**When to use:** During flush, after writing RationaleEpisode nodes.
**Example:**
```python
# Source: Follows D-08 (case-insensitive substring) and D-09 (flush piggyback)
def _match_entities(
    records: list[EpisodeRecord],
    entity_names: list[str],
) -> list[dict]:
    """Match Decision rationales against entity names (Python-side).

    Returns list of {decision_id, entity_name} pairs for UNWIND.
    """
    matches = []
    for record in records:
        rationale_lower = record.rationale.lower()
        for name in entity_names:
            if name.lower() in rationale_lower:
                matches.append({
                    "decision_id": record.decision_id,
                    "entity_name": name,
                })
    return matches

# Cypher for REFERENCES edges (single UNWIND statement)
"""
UNWIND $matches AS m
MATCH (d:Decision {decision_id: m.decision_id})
MATCH (e:Entity {name: m.entity_name})
CREATE (d)-[:REFERENCES {match_type: "substring"}]->(e)
"""
```

### Pattern 4: FlipType Computation (D-06)
**What:** Compute signal transition type by comparing current and previous round decisions for the same agent. Follows the same comparison logic as `_compute_shifts()` in simulation.py.
**When to use:** At buffer push time, when pairing the current agent decision with its previous-round decision.
**Example:**
```python
# Source: Adapted from _compute_shifts() in simulation.py:333-385
def compute_flip_type(
    prev_signal: SignalType | None,
    curr_signal: SignalType,
) -> FlipType:
    """Compute signal transition type between rounds."""
    if prev_signal is None or prev_signal == SignalType.PARSE_ERROR:
        return FlipType.NONE
    if curr_signal == SignalType.PARSE_ERROR:
        return FlipType.NONE
    if prev_signal == curr_signal:
        return FlipType.NONE
    # Build key from signal values: "BUY_TO_SELL", "SELL_TO_HOLD", etc.
    key = f"{prev_signal.value.upper()}_TO_{curr_signal.value.upper()}"
    return FlipType(key)
```

### Pattern 5: Post-Simulation Narrative Generation (D-10, D-11)
**What:** After Round 3 write, generate a natural-language decision narrative per agent using the worker model (already loaded). Batch through governor. Store as `decision_narrative` property on Agent nodes.
**When to use:** Post-simulation, after Round 3 write_decisions + flush but before COMPLETE phase transition.
**Example integration point:**
```python
# In simulation.py:run_simulation(), after Round 3 writes (line ~825):
# 1. write_decisions (existing)
# 2. WriteBuffer.flush() (new)
# 3. compute_influence_edges (existing, Round 3 not currently done but optional)
# 4. generate_narratives (new, gated by flag)
# 5. SimulationPhase.COMPLETE transition

if generate_narratives:
    await _generate_decision_narratives(
        personas=personas,
        all_decisions={1: round1_decisions, 2: round2_decisions, 3: round3_decisions},
        graph_manager=graph_manager,
        governor=governor,
        client=ollama_client,
        model=worker_alias,
    )
```

### Anti-Patterns to Avoid
- **Per-agent Neo4j writes:** Never issue individual `CREATE` per agent. Always batch via UNWIND. 100 individual transactions = connection pool exhaustion. This is why WriteBuffer exists.
- **Refactoring write_decisions():** D-03 explicitly locks this. Do NOT modify the proven v1 write path. New writes are additive.
- **Entity matching in Cypher UNWIND:** A Cypher `UNWIND $episodes UNWIND $entities WHERE toLower(ep.rationale) CONTAINS toLower(e.name)` creates an N*M cross-product in the query plan. Do matching in Python, UNWIND only the matched pairs.
- **Blocking narrative generation:** 100 LLM calls must go through governor, not raw asyncio.gather(). Governor handles memory pressure throttling.
- **Storing decision_id on RationaleEpisode:** The `decision_id` is used to link via `HAS_EPISODE` relationship in the Cypher MATCH. It does NOT need to be stored as a property on RationaleEpisode (it is already traversable via the relationship).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async queue buffering | Custom lock + list accumulator | `asyncio.Queue` | Thread-safe, maxsize overflow handling, matches StateStore pattern |
| Signal flip detection | Manual if/elif chain for all 6 transitions | Computed `FlipType` from `f"{prev}_TO_{curr}"` string construction | StrEnum lookup handles all combinations; adding new signal types auto-extends |
| Neo4j batch writes | Individual `session.run()` per agent | `execute_write()` with UNWIND pattern | Proven pattern from write_decisions(). 1 transaction vs 100 |
| Entity name loading | Re-query Entity nodes from Neo4j per round | Load once at cycle start, cache as `list[str]` | Entity names are static within a cycle (created during seed injection) |
| Post-simulation inference batching | Raw `asyncio.gather()` for 100 inference calls | ResourceGovernor semaphore-controlled dispatch | Governor handles memory pressure throttling, backoff, and slot management |

**Key insight:** Every pattern needed for this phase already exists in the codebase. WriteBuffer mirrors StateStore's queue. Episode writes mirror `write_decisions()`. Entity matching mirrors `_create_cycle_with_entities_tx()`. Flip detection mirrors `_compute_shifts()`. Narrative generation mirrors `dispatch_wave()` through the governor. The planner should structure tasks as "adapt existing pattern X for use case Y."

## Common Pitfalls

### Pitfall 1: Decision ID Availability at Buffer Push Time
**What goes wrong:** The WriteBuffer needs `decision_id` to link RationaleEpisode to Decision via `HAS_EPISODE`. But `decision_id` is generated inside `_batch_write_decisions_tx()` (line 258 of graph.py) and is NOT returned to the caller.
**Why it happens:** `write_decisions()` generates UUIDs internally and does not expose them. The buffer push happens before or alongside `write_decisions()`, so the buffer doesn't know which Decision nodes were created.
**How to avoid:** Generate `decision_id` UUIDs at the call site (in `run_simulation()` or `_dispatch_round()`), pass them into both `write_decisions()` and `WriteBuffer.push()`. This requires a minor refactor of `write_decisions()` to accept pre-generated IDs instead of generating them internally. This is NOT a refactor of the write pattern itself (D-03 still respected) -- it's a parameter change to `write_decisions()`.
**Warning signs:** RationaleEpisode nodes with no `HAS_EPISODE` edges (orphaned nodes).

### Pitfall 2: Transaction Count Budget (Success Criteria 4)
**What goes wrong:** Adding RationaleEpisode writes, REFERENCES edges, and narrative writes could push transaction count over 10 per round.
**Why it happens:** Each `session.execute_write()` call is a separate transaction. If episode writes, edge writes, and influence edge computation each use separate sessions, that's 4+ transactions per round (write_decisions + write_episodes + write_references + compute_influence).
**How to avoid:** Combine RationaleEpisode creation and REFERENCES edge creation into a single `execute_write()` call with two Cypher statements (same pattern as `_batch_write_decisions_tx()` which has Statement 1 + Statement 2). Budget: `write_decisions` (1 tx) + `flush` (1 tx with 2-3 statements) + `compute_influence_edges` (2 tx: read + write) = 4 transactions per round. Well under 10.
**Warning signs:** Neo4j transaction log showing >10 begin/commit pairs per round.

### Pitfall 3: Peer Context String for Round 1
**What goes wrong:** Round 1 agents have no peer context (`peer_context=None` in `dispatch_wave()`). Storing `None` or empty string on RationaleEpisode.peer_context_received.
**Why it happens:** `_format_peer_context()` returns empty string for empty peers list. Round 1 has no peers by design.
**How to avoid:** Store empty string `""` for Round 1 episodes. Document this as expected behavior. Downstream queries should treat empty string as "no peer context (Round 1)."
**Warning signs:** Null property errors in Cypher queries filtering on `peer_context_received`.

### Pitfall 4: Entity Name Case Sensitivity in MATCH
**What goes wrong:** REFERENCES edges fail to create because `MATCH (e:Entity {name: m.entity_name})` is case-sensitive, and the Python-side match used `name.lower()`.
**Why it happens:** The entity names stored in Neo4j during seed injection preserve original casing (e.g., "NVIDIA", "Apple"). Python-side matching lowercases both sides. If the UNWIND passes `entity_name: "nvidia"` instead of `"NVIDIA"`, the MATCH fails.
**How to avoid:** Always pass the ORIGINAL entity name (not lowercased) in the matched pairs dict. The Python-side `name.lower() in rationale_lower` check determines IF there's a match. The Cypher MATCH uses the original name to find the Entity node.
**Warning signs:** Zero REFERENCES edges despite entities clearly mentioned in rationales.

### Pitfall 5: Narrative Generation Timeout / Partial Failure
**What goes wrong:** With 100 inference calls, some agents may fail (Ollama timeout, malformed response). If the narrative generation loop aborts on first failure, no agents get narratives.
**Why it happens:** Default asyncio.TaskGroup propagates first exception and cancels remaining tasks.
**How to avoid:** Use the same per-agent error handling as `dispatch_wave()` -- catch individual failures, log them, skip that agent's narrative. A `skip + log` strategy is better than retry (retrying 100 calls could take 6-8 minutes on top of the initial 3-4 minutes).
**Warning signs:** `decision_narrative` property missing on some Agent nodes. Downstream (Phase 14 interviews) should handle `None` gracefully.

### Pitfall 6: WriteBuffer Flush Ordering with write_decisions()
**What goes wrong:** If `flush()` runs before `write_decisions()` completes, the MATCH on `Decision {decision_id: ...}` in the episode write fails because the Decision node doesn't exist yet.
**Why it happens:** Both operations are async. If someone accidentally calls flush() before write_decisions() in the simulation loop.
**How to avoid:** Explicit sequential ordering in `run_simulation()`: (1) `write_decisions()`, (2) `write_buffer.flush()`, (3) `compute_influence_edges()`. Document this ordering constraint in WriteBuffer docstring. Tests should verify flush-after-write ordering.
**Warning signs:** Neo4j errors: "No node found matching Decision {decision_id: X}".

## Code Examples

Verified patterns from the existing codebase:

### FlipType Enum (for types.py)
```python
# Follows existing (str, Enum) convention from SignalType, BracketType, etc.
class FlipType(str, Enum):
    """Signal transition types between consecutive rounds."""
    NONE = "none"
    BUY_TO_SELL = "buy_to_sell"
    SELL_TO_BUY = "sell_to_buy"
    BUY_TO_HOLD = "buy_to_hold"
    HOLD_TO_BUY = "hold_to_buy"
    SELL_TO_HOLD = "sell_to_hold"
    HOLD_TO_SELL = "hold_to_sell"
```

### Schema Extension (for graph.py SCHEMA_STATEMENTS)
```python
# Add to SCHEMA_STATEMENTS list:
"CREATE INDEX episode_cycle_round IF NOT EXISTS FOR (re:RationaleEpisode) ON (re.cycle_id, re.round)",
```

### Entity Name Cache Loading (for GraphStateManager)
```python
# New method following session-per-method pattern (D-07 from Phase 4)
async def read_cycle_entities(self, cycle_id: str) -> list[str]:
    """Read entity names for a cycle. Loaded once, cached by caller."""
    async with self._driver.session(database=self._database) as session:
        result = await session.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})-[:MENTIONS]->(e:Entity)
            RETURN e.name AS name
            """,
            cycle_id=cycle_id,
        )
        return [record["name"] async for record in result]
```

### Decision Narrative Write (for GraphStateManager)
```python
# Batch-write decision_narrative property on Agent nodes
async def write_decision_narratives(
    self,
    narratives: list[dict],  # [{agent_id, narrative}]
) -> None:
    """Write decision_narrative property to Agent nodes via UNWIND."""
    async with self._driver.session(database=self._database) as session:
        await session.execute_write(
            self._batch_write_narratives_tx, narratives,
        )

@staticmethod
async def _batch_write_narratives_tx(
    tx: AsyncManagedTransaction,
    narratives: list[dict],
) -> None:
    await tx.run(
        """
        UNWIND $narratives AS n
        MATCH (a:Agent {id: n.agent_id})
        SET a.decision_narrative = n.narrative
        """,
        narratives=narratives,
    )
```

### Cypher Verification Query (Success Criteria 3)
```cypher
-- Query: complete 3-round reasoning arc for any agent
MATCH (a:Agent {id: $agent_id})-[:MADE]->(d:Decision)-[:HAS_EPISODE]->(re:RationaleEpisode)
WHERE d.cycle_id = $cycle_id
OPTIONAL MATCH (d)-[:REFERENCES]->(e:Entity)
OPTIONAL MATCH (d)<-[:CITED]-(citing:Agent)
RETURN d.round AS round,
       d.signal AS signal,
       d.confidence AS confidence,
       re.rationale AS rationale,
       re.peer_context_received AS peer_context,
       re.flip_type AS flip_type,
       re.timestamp AS timestamp,
       collect(DISTINCT e.name) AS referenced_entities,
       collect(DISTINCT citing.id) AS cited_by
ORDER BY d.round
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Neo4j as post-round data dump | Write-behind buffer with per-agent queueing + batch flush | Phase 11 | Enables per-agent reasoning arc queries; prerequisite for interviews and reports |
| No rationale persistence beyond Decision.rationale | RationaleEpisode nodes with full peer context and flip detection | Phase 11 | Interviews can replay exactly what the agent saw |
| No entity-decision linkage | REFERENCES edges via substring matching | Phase 11 | Reports can query "which agents mentioned NVIDIA" |
| No agent-level narrative summary | LLM-generated decision_narrative on Agent nodes | Phase 11 | Interviews have pre-computed context; reduces cold-start latency |

**Deprecated/outdated:**
- None applicable. This is additive functionality extending the v1 schema.

## Open Questions

1. **decision_id Generation Refactor Scope**
   - What we know: `write_decisions()` generates UUIDs internally (line 258). WriteBuffer needs these IDs.
   - What's unclear: Whether to refactor `write_decisions()` to accept pre-generated IDs, or to generate IDs earlier (at the call site) and pass them through.
   - Recommendation: Generate IDs at the call site in `run_simulation()` / `_dispatch_round()`. Modify `write_decisions()` to accept an optional `decision_ids` parameter. If not provided, generate internally (backward compatible). This is the least invasive change.

2. **Narrative Generation Prompt Design**
   - What we know: Worker model summarizes 3-round arc per agent. Input: persona, 3 decisions, flip types, cited peers.
   - What's unclear: Exact prompt template and expected output length.
   - Recommendation: Keep narrative under 200 tokens. Prompt should instruct: "Summarize this agent's 3-round decision arc in 2-3 sentences, noting any signal changes and key influences." Store as plain text, not structured JSON.

3. **Flush Transaction Scope**
   - What we know: D-09 says REFERENCES edges piggyback on the same transaction as RationaleEpisode writes.
   - What's unclear: Whether "same transaction" means same `execute_write()` call (single `_tx` function with 2 statements) or same session (sequential `execute_write()` calls).
   - Recommendation: Same `execute_write()` with a single transaction function containing two Cypher statements (episodes + references). Matches the two-statement pattern in `_batch_write_decisions_tx()`. This guarantees atomicity and counts as 1 transaction toward the budget.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | Yes | 3.11.5 (via uv) | -- |
| Neo4j | Graph writes | Yes | 5.26-community (Docker) | -- |
| Docker | Neo4j host | Yes | Running | -- |
| Ollama | Narrative generation | Yes (assumed) | -- | Skip narrative generation with flag |
| pytest-asyncio | Testing | Yes | >=0.24.0 | -- |

**Missing dependencies with no fallback:**
- None

**Missing dependencies with fallback:**
- Ollama availability is assumed but not verified in this research session. Narrative generation (D-10, D-11) should be gated by `generate_narratives` flag so tests and CI can skip inference.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24+ |
| Config file | `pyproject.toml` ([tool.pytest.ini_options]) |
| Quick run command | `uv run pytest tests/test_write_buffer.py tests/test_graph.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GRAPH-01 | WriteBuffer queues per-agent records and flush drains into batch | unit | `uv run pytest tests/test_write_buffer.py -x` | No -- Wave 0 |
| GRAPH-01 | GraphStateManager.write_rationale_episodes() batch writes via UNWIND | unit | `uv run pytest tests/test_graph.py -k "episode" -x` | No -- Wave 0 |
| GRAPH-02 | RationaleEpisode nodes created with all required properties | unit | `uv run pytest tests/test_graph.py -k "episode" -x` | No -- Wave 0 |
| GRAPH-02 | FlipType computed correctly for all signal transitions | unit | `uv run pytest tests/test_write_buffer.py -k "flip" -x` | No -- Wave 0 |
| GRAPH-02 | Round 1 episodes have flip_type=NONE, peer_context_received="" | unit | `uv run pytest tests/test_write_buffer.py -k "round1" -x` | No -- Wave 0 |
| GRAPH-03 | REFERENCES edges match entities case-insensitively | unit | `uv run pytest tests/test_graph.py -k "references" -x` | No -- Wave 0 |
| GRAPH-03 | Entity names loaded once per cycle and reused | unit | `uv run pytest tests/test_graph.py -k "entities" -x` | No -- Wave 0 |
| SC-3 | Cypher query returns complete 3-round reasoning arc | integration | `uv run pytest tests/test_graph_integration.py -k "reasoning_arc" -x` | No -- Wave 0 |
| SC-4 | Transaction count under 10 per round | integration | `uv run pytest tests/test_graph_integration.py -k "transaction_count" -x` | No -- Wave 0 |
| D-10 | Narrative generation writes decision_narrative to Agent nodes | unit | `uv run pytest tests/test_graph.py -k "narrative" -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_write_buffer.py tests/test_graph.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_write_buffer.py` -- covers GRAPH-01 (buffer push/drain/flush), GRAPH-02 (FlipType computation)
- [ ] `tests/test_graph.py` (additions) -- covers GRAPH-01 (write_rationale_episodes), GRAPH-02 (episode properties), GRAPH-03 (REFERENCES edges, entity loading), D-10 (narrative writes)
- [ ] `tests/test_graph_integration.py` (additions) -- covers SC-3 (full reasoning arc query), SC-4 (transaction count verification)
- [ ] `tests/test_simulation.py` (additions) -- covers WriteBuffer integration in run_simulation(), narrative generation flow

## Sources

### Primary (HIGH confidence)
- **Existing codebase** -- `graph.py` (write_decisions UNWIND pattern, compute_influence_edges post-round pattern), `simulation.py` (run_simulation orchestration, _format_peer_context, _compute_shifts), `state.py` (asyncio.Queue pattern in StateStore), `types.py` (enum conventions)
- **11-CONTEXT.md** -- All 11 locked decisions, discretion areas, canonical references
- **REQUIREMENTS.md** -- GRAPH-01, GRAPH-02, GRAPH-03 requirement definitions
- [Neo4j Performance Recommendations](https://neo4j.com/docs/python-manual/current/performance/) -- UNWIND batch write best practices, connection pool sizing
- [Neo4j UNWIND Cypher Manual](https://neo4j.com/docs/cypher-manual/current/clauses/unwind/) -- UNWIND syntax and batch patterns
- [Neo4j String Operators](https://neo4j.com/docs/cypher-manual/current/expressions/predicates/string-operators/) -- Case-insensitive CONTAINS with toLower()

### Secondary (MEDIUM confidence)
- [Neo4j Batch Updates Tips](https://medium.com/neo4j/5-tips-tricks-for-fast-batched-updates-of-graph-structures-with-neo4j-and-cypher-73c7f693c8cc) -- Transaction size recommendations for batch operations
- [Neo4j Python Driver Concurrency](https://neo4j.com/docs/python-manual/current/concurrency/) -- Async driver session management

### Tertiary (LOW confidence)
- None. All research findings are verified against existing codebase patterns and official Neo4j documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- No new dependencies. All patterns mirror existing codebase.
- Architecture: HIGH -- WriteBuffer design follows StateStore queue pattern. Graph writes follow write_decisions() pattern. Integration points are explicitly identified in CONTEXT.md with line numbers.
- Pitfalls: HIGH -- All 6 pitfalls identified from codebase analysis (decision_id availability, transaction count budget, Round 1 peer context, entity name casing, narrative failure handling, flush ordering). Each has concrete prevention strategy.

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (stable domain, no fast-moving dependencies)
