# Phase 8: Dynamic Influence Topology - Research

**Researched:** 2026-03-26
**Domain:** Neo4j graph topology computation, in-memory aggregation, Pydantic data contracts
**Confidence:** HIGH

## Summary

Phase 8 replaces the static `influence_weight_base` peer ranking with a dynamic citation-frequency-based INFLUENCED_BY edge system that actively shapes which agents appear in each other's peer context across rounds. The implementation spans four workstreams: (1) influence edge computation from existing CITED relationships in Neo4j, (2) bracket-diverse top-5 peer selection using dynamic weights, (3) bracket-level sentiment aggregation promoted from CLI to the simulation layer as a proper frozen dataclass, and (4) a standalone Miro batcher stub with Pydantic data shape contracts.

The codebase is well-prepared. `write_decisions()` in `graph.py` already persists CITED relationships via UNWIND batch writes (Decision-[:CITED]->Agent). The Phase 4 schema design (D-02, D-03) explicitly anticipated this phase: CITED is raw LLM output, INFLUENCED_BY is the computed topology. `read_peer_decisions()` currently uses `ORDER BY a.influence_weight_base DESC` -- this is the single Cypher query that must be replaced with a dynamic-weight alternative. The `_aggregate_brackets()` function in `cli.py` provides a working pattern to extract, refine, and promote to the simulation layer.

**Primary recommendation:** Implement influence computation as a pure Python function that reads CITED edges from Neo4j via a new `read_citation_counts()` method, computes normalized weights in-memory, then writes INFLUENCED_BY edges back via UNWIND batch. Keep bracket aggregation entirely in-memory (no new Neo4j queries). Miro module is a standalone `miro.py` with zero imports from the simulation layer.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Citation frequency algorithm. INFLUENCED_BY edge weight = normalized count of how many times an agent is cited across the round. Weight = citations_received / total_agents. Simple, interpretable, directly uses existing CITED edges in Neo4j.
- **D-02:** Compute INFLUENCED_BY edges after each round (not retrospectively). After Round 1: compute edges for Round 2 peer selection. After Round 2: compute edges for Round 3 peer selection. The topology actively shapes subsequent rounds.
- **D-03:** All citation pairs produce INFLUENCED_BY edges. Every CITED relationship generates an INFLUENCED_BY edge with its computed weight. No minimum threshold filter. Neo4j handles the edge count (max ~300 edges per round).
- **D-04:** Cumulative weights across rounds. Round 2 weights = Round 1 citations. Round 3 weights = Round 1 + Round 2 citations combined. Agents who are consistently cited build momentum across the cascade.
- **D-05:** Static base for Round 1 cold start. Round 1 keeps using `influence_weight_base` from config (existing behavior). Dynamic citation-based weights kick in for Round 2+ once citation data exists. Clean separation -- Round 1 seeds the topology.
- **D-06:** Bracket-diverse top-5 peer selection. Top-5 peers must include agents from at least 3 different brackets. Fill slots by weight within each bracket -- top-1 from highest-weight bracket, top-1 from second-highest, top-1 from third, then fill remaining 2 by pure weight. Prevents echo chambers where a single archetype dominates influence.
- **D-07:** In-memory computation from round results. Compute bracket aggregation in Python from the round's AgentDecision list. No new Neo4j queries needed. Reuses the pattern from existing `_aggregate_brackets()` in cli.py.
- **D-08:** Promote aggregation to simulation layer. Move aggregation logic into the simulation module as a proper BracketSummary frozen dataclass. SimulationResult includes per-round bracket summaries. CLI and future TUI both consume the same data. Clean separation of compute vs display.
- **D-09:** Data shapes only. Define Pydantic models for Miro payloads (MiroNode, MiroConnector, MiroBatchPayload) and a MiroBatcher class with async methods that accept these types but log instead of making HTTP calls. Defines the v2 contract without premature implementation.
- **D-10:** Standalone module. `miro.py` exists independently with types and stub batcher. Not imported by simulation.py or wired into AppState. v2 wires it in. Avoids unnecessary coupling for a stub.

### Claude's Discretion
- Internal structure of the influence computation module (helper functions, where it lives)
- INFLUENCED_BY edge Cypher write pattern (UNWIND batch vs individual creates)
- BracketSummary dataclass field design beyond signal distribution and avg confidence
- MiroNode/MiroConnector field details beyond the core shape
- Whether bracket-diverse selection uses a dedicated Cypher query or post-processes in Python
- Error handling for edge cases (zero citations in a round, self-citations)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIM-07 | Dynamic influence topology -- INFLUENCED_BY edges in Neo4j form and shift weight based on citation/agreement patterns within the current cycle, not predefined hierarchies | Influence computation algorithm (D-01 through D-04), Cypher patterns for reading CITED edges and writing INFLUENCED_BY edges, bracket-diverse peer selection (D-06) |
| SIM-08 | Bracket-level sentiment aggregation computed after each round (e.g., "Quants are 80% bearish") | BracketSummary frozen dataclass promoted from CLI pattern (D-07, D-08), signal distribution computation, SimulationResult extension |
| INFRA-10 | Miro API batcher stubbed with 2s buffer and bulk payload interface (no live API calls in v1) | MiroNode/MiroConnector/MiroBatchPayload Pydantic models, MiroBatcher stub class with log-only methods (D-09, D-10) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (asyncio). All new Neo4j methods must be async.
- **Local First:** No cloud APIs (except Miro stub which logs only).
- **Memory Safety:** Monitor RAM via psutil. 100 agents x 3 rounds = 300 decisions max per cycle.
- **Miro API:** Strict 2-second buffer/batching. Bulk operations only. Never send single-node updates.
- **Runtime:** Python 3.11+ strict typing, uv package manager, pytest-asyncio.
- **State/Memory:** Neo4j Community (Docker) via neo4j async driver.
- **Validation/Config:** Pydantic for config/data shapes, frozen dataclasses for immutable results.
- **Logging:** structlog with component-scoped loggers.
- **GSD Workflow:** All changes through GSD commands.

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| neo4j | 5.28.3 | Graph database async driver | Already in use; UNWIND batch pattern established |
| pydantic | 2.12.5 | Miro data shape contracts, BracketSummary validation | Project standard for config and validation |
| structlog | 25.5.0 | Component-scoped logging | Project standard |
| httpx | 0.28.1 | Already installed (for future Miro HTTP) | Listed in CLAUDE.md stack |
| pytest | 9.0.2 | Test framework | Project standard |

### No New Dependencies Required
This phase requires zero new package installations. All functionality is built on existing Neo4j async driver Cypher queries, in-memory Python computation, and Pydantic model definitions.

## Architecture Patterns

### Recommended Module Structure
```
src/alphaswarm/
  graph.py          # + compute_influence_edges(), read_dynamic_peers()
  simulation.py     # + BracketSummary, influence injection between rounds
  cli.py            # - _aggregate_brackets() (promoted to simulation layer)
  miro.py           # NEW: MiroNode, MiroConnector, MiroBatchPayload, MiroBatcher
  types.py          # unchanged (BracketSummary lives in simulation.py with other result types)
tests/
  test_graph.py     # + influence edge computation tests
  test_simulation.py # + BracketSummary, influence injection tests
  test_miro.py      # NEW: Miro data shape and stub tests
```

### Pattern 1: Influence Edge Computation (graph.py)

**What:** New `compute_influence_edges()` method on GraphStateManager that reads CITED relationships for given round(s), computes normalized citation frequency, and batch-writes INFLUENCED_BY edges.

**When to use:** Called between rounds in `run_simulation()` -- after `write_decisions()` completes for Round N, before `_dispatch_round()` for Round N+1.

**Cypher read pattern (citation counts):**
```python
# Read citation counts for a cycle up to a given round
# Returns: list of {cited_agent_id: str, citation_count: int}
CITATION_COUNT_QUERY = """
MATCH (d:Decision)-[:CITED]->(a:Agent)
WHERE d.cycle_id = $cycle_id AND d.round <= $up_to_round
RETURN a.id AS agent_id, count(d) AS citation_count
"""
```

**Cypher write pattern (INFLUENCED_BY edges via UNWIND):**
```python
# Batch-write INFLUENCED_BY edges between agents
# Each edge: (citing_agent)-[:INFLUENCED_BY {weight, cycle_id, round}]->(cited_agent)
INFLUENCE_WRITE_QUERY = """
UNWIND $edges AS e
MATCH (src:Agent {id: e.source_id})
MATCH (tgt:Agent {id: e.target_id})
CREATE (src)-[:INFLUENCED_BY {
    weight: e.weight,
    cycle_id: $cycle_id,
    round: $round_num
}]->(tgt)
"""
```

**Normalization (in Python):**
```python
def _compute_influence_weights(
    citation_counts: list[dict],
    total_agents: int,
) -> dict[str, float]:
    """Normalize citation counts: weight = citations_received / total_agents."""
    return {
        row["agent_id"]: row["citation_count"] / total_agents
        for row in citation_counts
    }
```

### Pattern 2: Bracket-Diverse Peer Selection (graph.py or Python post-processing)

**What:** Replace `ORDER BY a.influence_weight_base DESC LIMIT 5` with dynamic-weight ranking that ensures at least 3 distinct brackets in the top-5.

**Recommendation: Post-process in Python.** The bracket-diversity constraint (at least 3 brackets, fill by weight within bracket, remaining by pure weight) is complex to express in a single Cypher query. Better to fetch top candidates from Neo4j ordered by dynamic weight, then apply the diversity filter in Python.

**Cypher read pattern (dynamic peer candidates):**
```python
# Read peer agents with their cumulative influence weights
# Returns more than 5 to allow Python-side bracket diversity filtering
DYNAMIC_PEERS_QUERY = """
MATCH (a:Agent)
WHERE a.id <> $agent_id
OPTIONAL MATCH (a)<-[inf:INFLUENCED_BY]-(src:Agent)
WHERE inf.cycle_id = $cycle_id AND inf.round <= $up_to_round
WITH a, COALESCE(sum(inf.weight), 0) AS dynamic_weight
RETURN a.id AS agent_id,
       a.bracket AS bracket,
       dynamic_weight
ORDER BY dynamic_weight DESC
LIMIT $candidate_pool
"""
# Then in Python: apply bracket-diverse top-5 selection
```

**Alternative approach (recommended):** Since influence weights are already computed in Python during `compute_influence_edges()`, pass the weight dict directly to `_dispatch_round()` and do peer selection entirely in Python using the round's AgentDecision data already in memory. This avoids an additional Neo4j round-trip per agent.

**Python bracket-diverse selection:**
```python
def select_diverse_peers(
    agent_id: str,
    influence_weights: dict[str, float],
    personas: list[AgentPersona],
    limit: int = 5,
    min_brackets: int = 3,
) -> list[str]:
    """Select top-5 peers ensuring bracket diversity.

    Algorithm (D-06):
    1. Group candidates by bracket, sorted by weight within each bracket
    2. Pick top-1 from highest-weight bracket, top-1 from second, top-1 from third
    3. Fill remaining 2 slots by pure weight (any bracket)
    """
```

### Pattern 3: BracketSummary Promotion (simulation.py)

**What:** Extract aggregation logic from `cli.py:_aggregate_brackets()`, refine into a frozen dataclass in `simulation.py`, and embed per-round summaries in `SimulationResult` and `RoundCompleteEvent`.

**Dataclass design:**
```python
@dataclasses.dataclass(frozen=True)
class BracketSummary:
    """Per-bracket signal distribution and confidence for a single round."""
    bracket: str          # BracketType.value
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float  # Additional: useful for "Quants are 80% bearish" display

def compute_bracket_summaries(
    agent_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
) -> tuple[BracketSummary, ...]:
    """Compute per-bracket summaries from a round's decisions."""
```

### Pattern 4: Miro Batcher Stub (miro.py)

**What:** Standalone module with Pydantic models for Miro API payload shapes and a stub batcher that logs instead of making HTTP calls.

**Data shapes based on Miro REST API v2:**
```python
class MiroNode(BaseModel, frozen=True):
    """A board item (sticky note) representing an agent or bracket."""
    item_id: str                    # Agent ID or bracket name
    content: str                    # Display text
    color: str                      # Hex color based on sentiment
    x: float                        # Board position
    y: float                        # Board position
    width: float = 200.0
    height: float = 200.0
    metadata: dict[str, str | float] = {}  # signal, confidence, etc.

class MiroConnector(BaseModel, frozen=True):
    """A connector line between two board items."""
    start_item_id: str              # Source agent/bracket
    end_item_id: str                # Target agent/bracket
    label: str = ""                 # Edge label (e.g., weight)
    stroke_color: str = "#000000"
    stroke_width: float = 1.0

class MiroBatchPayload(BaseModel, frozen=True):
    """Batch of nodes and connectors for a single Miro API call."""
    board_id: str
    nodes: list[MiroNode]
    connectors: list[MiroConnector]
    timestamp: str                  # ISO 8601
```

### Anti-Patterns to Avoid

- **Writing INFLUENCED_BY edges one at a time:** Use UNWIND batch writes, matching the established pattern in `_batch_write_decisions_tx`. Max ~300 edges per round is well within a single UNWIND batch.
- **Reading peer decisions per agent from Neo4j when dynamic weights are already in memory:** After computing influence weights in Python, pass them through to peer selection rather than re-querying Neo4j for each of 100 agents.
- **Importing miro.py from simulation.py:** The Miro module must remain standalone (D-10). No coupling to the simulation pipeline in v1.
- **Using mutable containers in frozen dataclasses:** Use `tuple` not `list` for fields in BracketSummary and result containers (established pattern from Phase 7 Codex review).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph edge batch writes | Custom loop with individual CREATE | UNWIND batch via neo4j async driver | Established pattern, 100x faster |
| Citation frequency counting | Manual traversal in Python | Neo4j Cypher COUNT aggregation | Graph engine optimizes this natively |
| JSON serialization for Miro shapes | Manual dict construction | Pydantic `.model_dump()` | Type-safe, validated, serialization built-in |
| Bracket aggregation | Keep in CLI layer | Promote to simulation module | CLI and TUI must share the same computation |

**Key insight:** The existing codebase already has all the primitives (UNWIND writes, session-per-method, frozen dataclasses, Pydantic models). This phase composes them into new methods rather than inventing new patterns.

## Common Pitfalls

### Pitfall 1: Empty CITED Edges After Round 1
**What goes wrong:** If agents in Round 1 produce no citations (cited_agents is always empty), then `compute_influence_edges()` finds zero CITED relationships and all agents have weight 0.
**Why it happens:** Round 1 agents process the seed rumor independently with no peer context, so they have no one to cite. The prompt includes `"cited_agents": []` as the default.
**How to avoid:** This is the expected case. D-05 says Round 1 uses static `influence_weight_base`. Only compute INFLUENCED_BY edges when there are actual CITED relationships. If citation count is 0 for all agents after a round, the system gracefully falls back to static weights (or to the previous round's dynamic weights for Round 3).
**Warning signs:** All influence weights are 0.0 after Round 1. This is correct behavior, not a bug.

### Pitfall 2: Self-Citations
**What goes wrong:** An agent cites itself, inflating its own influence weight.
**Why it happens:** The LLM may output the agent's own ID in `cited_agents`.
**How to avoid:** Filter self-citations in the Cypher query or in Python normalization. Add a `WHERE d_citing_agent <> a.id` clause or filter in the Python layer. This is explicitly listed as Claude's discretion.
**Warning signs:** An agent's influence weight is disproportionately high relative to actual peer citations.

### Pitfall 3: Bracket-Diverse Selection With Few Cited Brackets
**What goes wrong:** If only 2 brackets have any citations (all other agents have weight 0), the "at least 3 brackets" constraint cannot be met purely from cited agents.
**Why it happens:** Uneven citation patterns where some brackets are ignored.
**How to avoid:** The selection algorithm should fall back gracefully. If fewer than 3 brackets have non-zero dynamic weight, fill remaining bracket slots with the highest static `influence_weight_base` agents from uncited brackets. The diversity constraint is "best effort" -- always return 5 peers.
**Warning signs:** Fewer than 3 unique brackets in the selected top-5 peers.

### Pitfall 4: Neo4j Connection Pool Exhaustion During Influence Computation
**What goes wrong:** Parallel reads from 100 agents exhaust the Neo4j connection pool.
**Why it happens:** Phase 7 already identified this (Pitfall 3) and solved it with sequential reads.
**How to avoid:** Influence computation is a single batch read (citation counts) + single batch write (INFLUENCED_BY edges). No per-agent queries needed for the computation step itself. Peer selection for the dispatch phase should continue the sequential pattern from Phase 7.
**Warning signs:** Neo4j `ServiceUnavailable` errors during influence edge writes.

### Pitfall 5: INFLUENCED_BY Edge Accumulation Across Cycles
**What goes wrong:** INFLUENCED_BY edges from previous simulation cycles leak into current cycle queries.
**Why it happens:** Missing cycle_id filter in Cypher queries.
**How to avoid:** Always filter by `cycle_id` in both read and write queries. Include cycle_id as a property on every INFLUENCED_BY edge.
**Warning signs:** Influence weights that don't match the current round's citation patterns.

### Pitfall 6: Stale CLI _aggregate_brackets Reference
**What goes wrong:** After promoting aggregation to the simulation layer, CLI still calls its own `_aggregate_brackets()` for old code paths.
**Why it happens:** Incomplete refactor -- CLI function remains but is no longer authoritative.
**How to avoid:** CLI should consume BracketSummary from SimulationResult/RoundCompleteEvent rather than computing inline. Remove or deprecate `cli.py:_aggregate_brackets()`.
**Warning signs:** Two different bracket aggregation results for the same round.

## Code Examples

### Example 1: Citation Count Cypher Query
```python
# Source: Established UNWIND pattern from graph.py + Neo4j COUNT aggregation
@staticmethod
async def _read_citation_counts_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    up_to_round: int,
) -> list[dict]:
    """Read per-agent citation counts across rounds."""
    result = await tx.run(
        """
        MATCH (d:Decision)-[:CITED]->(a:Agent)
        WHERE d.cycle_id = $cycle_id AND d.round <= $up_to_round
        RETURN a.id AS agent_id, count(d) AS citation_count
        """,
        cycle_id=cycle_id,
        up_to_round=up_to_round,
    )
    return [dict(record) async for record in result]
```

### Example 2: INFLUENCED_BY Batch Write
```python
# Source: Mirrors _batch_write_decisions_tx pattern in graph.py
@staticmethod
async def _write_influence_edges_tx(
    tx: AsyncManagedTransaction,
    edges: list[dict],
    cycle_id: str,
    round_num: int,
) -> None:
    """Batch-write INFLUENCED_BY edges via UNWIND."""
    if not edges:
        return
    await tx.run(
        """
        UNWIND $edges AS e
        MATCH (src:Agent {id: e.source_id})
        MATCH (tgt:Agent {id: e.target_id})
        CREATE (src)-[:INFLUENCED_BY {
            weight: e.weight,
            cycle_id: $cycle_id,
            round: $round_num
        }]->(tgt)
        """,
        edges=edges,
        cycle_id=cycle_id,
        round_num=round_num,
    )
```

### Example 3: Bracket-Diverse Selection in Python
```python
# Source: D-06 algorithm description from CONTEXT.md
def _select_diverse_peers(
    agent_id: str,
    influence_weights: dict[str, float],
    personas: list[AgentPersona],
    limit: int = 5,
    min_brackets: int = 3,
) -> list[str]:
    """Select top-5 peers with bracket diversity guarantee."""
    # Exclude self
    candidates = [p for p in personas if p.id != agent_id]

    # Group by bracket, sort each group by weight
    from collections import defaultdict
    bracket_groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for p in candidates:
        w = influence_weights.get(p.id, 0.0)
        bracket_groups[p.bracket.value].append((p.id, w))

    for bracket in bracket_groups:
        bracket_groups[bracket].sort(key=lambda x: x[1], reverse=True)

    # Sort brackets by their top agent's weight
    sorted_brackets = sorted(
        bracket_groups.keys(),
        key=lambda b: bracket_groups[b][0][1] if bracket_groups[b] else 0.0,
        reverse=True,
    )

    selected: list[str] = []
    used_brackets: set[str] = set()

    # Phase 1: Top-1 from top-3 brackets
    for bracket in sorted_brackets:
        if len(selected) >= min_brackets:
            break
        if bracket_groups[bracket]:
            agent, _ = bracket_groups[bracket].pop(0)
            selected.append(agent)
            used_brackets.add(bracket)

    # Phase 2: Fill remaining slots by pure weight
    remaining = []
    for bracket in bracket_groups:
        remaining.extend(bracket_groups[bracket])
    remaining.sort(key=lambda x: x[1], reverse=True)

    for agent, _ in remaining:
        if len(selected) >= limit:
            break
        if agent not in selected:
            selected.append(agent)

    return selected
```

### Example 4: BracketSummary Frozen Dataclass
```python
# Source: Promoted from cli.py:_aggregate_brackets() pattern
@dataclasses.dataclass(frozen=True)
class BracketSummary:
    """Immutable per-bracket aggregation for a single round."""
    bracket: str          # BracketType.value
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float
```

### Example 5: MiroBatcher Stub
```python
# Source: D-09, D-10 from CONTEXT.md + Miro REST API v2 shape
class MiroBatcher:
    """Stub batcher that defines the v2 Miro API contract.

    All methods log payloads via structlog instead of making HTTP calls.
    v2 replaces log calls with httpx POST requests to Miro REST API v2.
    """

    def __init__(self, board_id: str, buffer_seconds: float = 2.0) -> None:
        self._board_id = board_id
        self._buffer_seconds = buffer_seconds
        self._log = structlog.get_logger(component="miro")

    async def push_batch(self, payload: MiroBatchPayload) -> None:
        """Buffer and send a batch of nodes + connectors.

        v1: logs payload summary. v2: POST to Miro API with 2s buffer.
        """
        self._log.info(
            "miro_batch_stub",
            board_id=payload.board_id,
            node_count=len(payload.nodes),
            connector_count=len(payload.connectors),
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `influence_weight_base` ordering | Dynamic citation-frequency INFLUENCED_BY edges | Phase 8 (this phase) | Peers are now contextually relevant, not just bracket-default ranked |
| CLI-computed bracket aggregation | BracketSummary in simulation layer | Phase 8 (this phase) | Clean separation: compute in engine, display in CLI/TUI |
| No Miro integration | Stub with data shapes | Phase 8 (this phase) | v2 contract defined without premature HTTP coupling |

**Important:** `read_peer_decisions()` in `graph.py` (static weight version) must be preserved as a fallback for Round 1 cold-start and for the `inject` CLI command which doesn't use dynamic topology. The new dynamic peer selection is a separate code path called only for Rounds 2-3.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_graph.py tests/test_simulation.py tests/test_miro.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-07a | compute_influence_edges reads CITED, computes weights, writes INFLUENCED_BY | unit | `uv run pytest tests/test_graph.py::test_compute_influence_edges_reads_citations -x` | Wave 0 |
| SIM-07b | Cumulative weights across rounds (D-04) | unit | `uv run pytest tests/test_graph.py::test_influence_weights_cumulative_across_rounds -x` | Wave 0 |
| SIM-07c | Bracket-diverse peer selection (D-06) | unit | `uv run pytest tests/test_simulation.py::test_bracket_diverse_peer_selection -x` | Wave 0 |
| SIM-07d | Dynamic peer selection replaces static for Rounds 2-3 | unit | `uv run pytest tests/test_simulation.py::test_dynamic_peers_used_for_round2 -x` | Wave 0 |
| SIM-07e | Zero citations gracefully handled | unit | `uv run pytest tests/test_graph.py::test_compute_influence_edges_zero_citations -x` | Wave 0 |
| SIM-07f | Self-citations filtered | unit | `uv run pytest tests/test_graph.py::test_self_citations_filtered -x` | Wave 0 |
| SIM-08a | BracketSummary frozen dataclass fields | unit | `uv run pytest tests/test_simulation.py::test_bracket_summary_is_frozen -x` | Wave 0 |
| SIM-08b | compute_bracket_summaries matches CLI output | unit | `uv run pytest tests/test_simulation.py::test_bracket_summaries_match_cli -x` | Wave 0 |
| SIM-08c | SimulationResult includes per-round bracket summaries | unit | `uv run pytest tests/test_simulation.py::test_simulation_result_has_bracket_summaries -x` | Wave 0 |
| SIM-08d | RoundCompleteEvent includes bracket summaries | unit | `uv run pytest tests/test_simulation.py::test_round_complete_event_has_bracket_summaries -x` | Wave 0 |
| INFRA-10a | MiroNode, MiroConnector, MiroBatchPayload Pydantic models | unit | `uv run pytest tests/test_miro.py::test_miro_node_model -x` | Wave 0 |
| INFRA-10b | MiroBatcher.push_batch logs instead of HTTP | unit | `uv run pytest tests/test_miro.py::test_miro_batcher_logs_payload -x` | Wave 0 |
| INFRA-10c | MiroBatcher 2s buffer config | unit | `uv run pytest tests/test_miro.py::test_miro_batcher_buffer_config -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_graph.py tests/test_simulation.py tests/test_miro.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_miro.py` -- covers INFRA-10 (new file)
- [ ] New test functions in `tests/test_graph.py` for influence edge computation (SIM-07a/b/e/f)
- [ ] New test functions in `tests/test_simulation.py` for BracketSummary and dynamic peer injection (SIM-07c/d, SIM-08a-d)

*(Existing test infrastructure (conftest.py fixtures, mock patterns) covers all other needs)*

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | (note: system python is 3.10.14, uv venv may differ) | 3.10.14 system | uv run always uses project venv |
| Neo4j (Docker) | Graph state | Yes | Running (container up 36h) | -- |
| Docker | Neo4j container | Yes | 29.3.0 | -- |
| uv | Package management | Yes | 0.11.0 | -- |
| neo4j driver | Graph queries | Yes | 5.28.3 | -- |
| pydantic | Miro data shapes | Yes | 2.12.5 | -- |
| httpx | Future Miro HTTP (not used in v1 stub) | Yes | 0.28.1 | Logging stub only |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Open Questions

1. **INFLUENCED_BY Edge Direction: Agent-to-Agent or Decision-to-Decision?**
   - What we know: Phase 4 D-02 says "INFLUENCED_BY connects Decision-to-Decision." But Phase 8 CONTEXT.md D-01 describes weight as `citations_received / total_agents` -- agent-level, not decision-level.
   - What's unclear: Whether edges should be (Agent)-[:INFLUENCED_BY]->(Agent) (simpler, sufficient for peer ranking) or (Decision)-[:INFLUENCED_BY]->(Decision) (granular, matches Phase 4 schema intent).
   - Recommendation: Use Agent-to-Agent edges for Phase 8. The D-01 formula is agent-level (normalized by total_agents), and the peer selection query operates on Agent nodes. Decision-to-Decision granularity can be added in v2 if needed. The Phase 4 schema design anticipated Decision-to-Decision but Phase 8 CONTEXT.md decisions are agent-level. **Agent-to-Agent is simpler and matches the actual algorithm.** Store cycle_id and round on the edge for scoping.

2. **Peer Selection: Neo4j Query vs In-Memory Python?**
   - What we know: D-06 bracket-diverse selection is complex. Influence weights are already computed in Python. Phase 7 reads peers sequentially from Neo4j (100 sequential queries).
   - What's unclear: Whether to add a new dynamic Cypher query or do peer selection entirely in Python using the weight dict.
   - Recommendation: **In-memory Python selection.** After `compute_influence_edges()`, the weight dict is already available. Build the top-5 list per agent in Python using the bracket-diverse algorithm. This eliminates 100 Neo4j round-trips per dispatch round and keeps the diversity logic testable without Neo4j mocks. Still need to read Decision data (signal, confidence, rationale) from Neo4j for the peer context string -- but this can be a single batch read of all decisions for the round, not per-agent.

3. **Simulation Result Extension: Backward Compatibility**
   - What we know: `SimulationResult` is a frozen dataclass consumed by CLI. Adding `bracket_summaries` fields changes its constructor signature.
   - What's unclear: Whether to extend `SimulationResult` directly or create a new result type.
   - Recommendation: Extend `SimulationResult` directly with optional bracket summary fields (defaulting to empty tuple). The CLI is the only consumer, and the frozen dataclass has no external API contract to break.

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/graph.py` -- Current CITED edge write pattern, read_peer_decisions static query, UNWIND batch pattern
- `src/alphaswarm/simulation.py` -- run_simulation orchestration, ShiftMetrics pattern, RoundCompleteEvent
- `src/alphaswarm/cli.py` -- `_aggregate_brackets()` implementation to promote
- `src/alphaswarm/types.py` -- AgentDecision.cited_agents, BracketType enum, AgentPersona.influence_weight_base
- `.planning/phases/04-neo4j-graph-state/04-CONTEXT.md` -- D-02 (INFLUENCED_BY schema), D-03 (CITED vs INFLUENCED_BY), D-09 (static fallback)
- `.planning/phases/07-rounds-2-3-peer-influence-and-consensus/07-CONTEXT.md` -- D-09/D-10 (peer reads), sequential pattern
- `.planning/phases/08-dynamic-influence-topology/08-CONTEXT.md` -- All locked decisions D-01 through D-10

### Secondary (MEDIUM confidence)
- [Neo4j Cypher UNWIND docs](https://neo4j.com/docs/cypher-manual/current/clauses/unwind/) -- UNWIND batch pattern for relationship creation
- [Neo4j aggregation functions](https://neo4j.com/docs/cypher-manual/current/functions/aggregating/) -- COUNT aggregation for citation frequency
- [Neo4j Python async driver docs](https://neo4j.com/docs/api/python-driver/current/async_api.html) -- Async transaction patterns
- [Miro REST API connectors](https://developers.miro.com/docs/work-with-connectors) -- Connector JSON shape (startItem, endItem, shape, style)
- [Miro REST API sticky notes](https://developers.miro.com/reference/create-sticky-note-item) -- Sticky note creation endpoint and shape

### Tertiary (LOW confidence)
- None -- all findings verified against codebase or official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and in use, zero new dependencies
- Architecture: HIGH -- all patterns follow established codebase conventions (UNWIND, session-per-method, frozen dataclass), locked decisions are specific and actionable
- Pitfalls: HIGH -- identified from direct code inspection and prior phase patterns (pool exhaustion, empty citations, self-citations)
- Miro shapes: MEDIUM -- based on Miro REST API v2 docs but this is a stub (shapes can evolve in v2)

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- no external dependency changes expected)
