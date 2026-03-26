# Phase 8: Dynamic Influence Topology - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 8 replaces the static `influence_weight_base` peer ranking with dynamic citation-frequency-based INFLUENCED_BY edges that form and shift weight after each round. Delivers: influence edge computation from CITED relationships, bracket-diverse dynamic peer selection for Rounds 2-3, bracket-level sentiment aggregation promoted to the simulation layer, and a standalone Miro batcher stub with data shape contracts. No TUI (Phase 9-10). No live Miro API calls (v2). The dynamic influence topology is the product's primary differentiator.

</domain>

<decisions>
## Implementation Decisions

### Influence Algorithm
- **D-01:** Citation frequency algorithm. INFLUENCED_BY edge weight = normalized count of how many times an agent is cited across the round. Weight = citations_received / total_agents. Simple, interpretable, directly uses existing CITED edges in Neo4j.
- **D-02:** Compute INFLUENCED_BY edges after each round (not retrospectively). After Round 1: compute edges for Round 2 peer selection. After Round 2: compute edges for Round 3 peer selection. The topology actively shapes subsequent rounds.
- **D-03:** All citation pairs produce INFLUENCED_BY edges. Every CITED relationship generates an INFLUENCED_BY edge with its computed weight. No minimum threshold filter. Neo4j handles the edge count (max ~300 edges per round).
- **D-04:** Cumulative weights across rounds. Round 2 weights = Round 1 citations. Round 3 weights = Round 1 + Round 2 citations combined. Agents who are consistently cited build momentum across the cascade.

### Peer Ranking Switchover
- **D-05:** Static base for Round 1 cold start. Round 1 keeps using `influence_weight_base` from config (existing behavior). Dynamic citation-based weights kick in for Round 2+ once citation data exists. Clean separation — Round 1 seeds the topology.
- **D-06:** Bracket-diverse top-5 peer selection. Top-5 peers must include agents from at least 3 different brackets. Fill slots by weight within each bracket — top-1 from highest-weight bracket, top-1 from second-highest, top-1 from third, then fill remaining 2 by pure weight. Prevents echo chambers where a single archetype dominates influence.

### Bracket Aggregation
- **D-07:** In-memory computation from round results. Compute bracket aggregation in Python from the round's AgentDecision list. No new Neo4j queries needed. Reuses the pattern from existing `_aggregate_brackets()` in cli.py.
- **D-08:** Promote aggregation to simulation layer. Move aggregation logic into the simulation module as a proper BracketSummary frozen dataclass. SimulationResult includes per-round bracket summaries. CLI and future TUI both consume the same data. Clean separation of compute vs display.

### Miro Batcher Stub
- **D-09:** Data shapes only. Define Pydantic models for Miro payloads (MiroNode, MiroConnector, MiroBatchPayload) and a MiroBatcher class with async methods that accept these types but log instead of making HTTP calls. Defines the v2 contract without premature implementation.
- **D-10:** Standalone module. `miro.py` exists independently with types and stub batcher. Not imported by simulation.py or wired into AppState. v2 wires it in. Avoids unnecessary coupling for a stub.

### Claude's Discretion
- Internal structure of the influence computation module (helper functions, where it lives)
- INFLUENCED_BY edge Cypher write pattern (UNWIND batch vs individual creates)
- BracketSummary dataclass field design beyond signal distribution and avg confidence
- MiroNode/MiroConnector field details beyond the core shape
- Whether bracket-diverse selection uses a dedicated Cypher query or post-processes in Python
- Error handling for edge cases (zero citations in a round, self-citations)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Implementation (Primary)
- `src/alphaswarm/graph.py` — `GraphStateManager.read_peer_decisions()` (line 338-404) currently uses `ORDER BY a.influence_weight_base DESC`. Must be updated to use dynamic INFLUENCED_BY weights for Rounds 2-3. Also: `write_decisions()` already writes CITED relationships (line 296-335) — the input data for influence computation.
- `src/alphaswarm/simulation.py` — `run_simulation()` orchestrates 3 rounds. Influence edge computation must be injected between rounds. `Round1Result` and `SimulationResult` containers.
- `src/alphaswarm/cli.py` — `_aggregate_brackets()` contains the bracket aggregation pattern to be promoted to the simulation layer.
- `src/alphaswarm/types.py` — `AgentDecision.cited_agents` (line 109), `AgentPersona.influence_weight_base`, `SimulationPhase` enum, `BracketType` enum, `SignalType` enum.
- `src/alphaswarm/config.py` — Bracket `influence_weight_base` values (0.3-0.9) used for Round 1 static ranking.
- `src/alphaswarm/batch_dispatcher.py` — `dispatch_wave()` with `peer_context` kwarg.
- `src/alphaswarm/worker.py` — `WorkerPersonaConfig` with `influence_weight` field.

### Requirements
- `.planning/REQUIREMENTS.md` — SIM-07 (dynamic influence topology), SIM-08 (bracket-level sentiment aggregation), INFRA-10 (Miro API batcher stub)
- `.planning/ROADMAP.md` — Phase 8 success criteria (5 criteria)

### Prior Phase Context
- `.planning/phases/04-neo4j-graph-state/04-CONTEXT.md` — D-02 (INFLUENCED_BY connects Decision-to-Decision), D-03 (CITED is raw LLM output, INFLUENCED_BY is computed topology), D-09 (static influence_weight_base as pre-Phase 8 fallback)
- `.planning/phases/07-rounds-2-3-peer-influence-and-consensus/07-CONTEXT.md` — D-09/D-10 (peer read per-agent before dispatch), D-04 (run_simulation orchestration), discretion note about static ranking producing identical top-5 peers

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_aggregate_brackets()` in `cli.py` — bracket aggregation pattern to promote to simulation layer as BracketSummary
- `write_decisions()` in `graph.py` — already writes CITED relationships via UNWIND batch. Citation data is in the graph.
- `read_peer_decisions()` in `graph.py` — peer selection query to update with dynamic weight ranking
- `PeerDecision` dataclass in `graph.py` — agent_id, bracket, signal, confidence, sentiment, rationale fields
- `dispatch_wave()` in `batch_dispatcher.py` — accepts peer_context kwarg, wired for Rounds 2-3
- `SimulationResult` / `Round1Result` in `simulation.py` — result containers to extend with bracket summaries

### Established Patterns
- UNWIND batch writes for Neo4j operations (graph.py)
- Session-per-method pattern for GraphStateManager (D-07 from Phase 4)
- Frozen dataclasses for immutable result containers
- structlog with component-scoped loggers
- Pydantic BaseModel for configuration/settings types

### Integration Points
- `graph.py` — Add `compute_influence_edges()`, `read_dynamic_peer_decisions()` (bracket-diverse), `read_bracket_aggregation()` if needed
- `simulation.py` — Inject influence computation between rounds in `run_simulation()`. Extend `SimulationResult` with BracketSummary per round.
- `cli.py` — Update reporting to use BracketSummary from SimulationResult instead of computing inline
- New `miro.py` module — standalone Miro types and stub batcher

</code_context>

<specifics>
## Specific Ideas

- Influence weight formula: `weight = citations_received / total_agents` (normalized citation frequency)
- Cumulative: Round 3 dynamic weights include citations from both Round 1 and Round 2
- Bracket-diverse selection: at least 3 distinct brackets in top-5 peers, fill by weight within bracket, remaining slots by pure weight
- Round 1 stays static (`influence_weight_base`), Rounds 2-3 use dynamic weights
- BracketSummary promoted from cli.py to simulation layer as frozen dataclass in SimulationResult
- MiroBatcher as standalone `miro.py` — data shapes + log-only methods, not wired into pipeline

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-dynamic-influence-topology*
*Context gathered: 2026-03-26*
