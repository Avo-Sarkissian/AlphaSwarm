# Phase 11: Live Graph Memory - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 11 transforms Neo4j from a post-round data dump into a living memory that captures per-agent reasoning arcs, narrative connections, and decision context as the simulation runs. Delivers: a write-behind buffer for async graph writes, RationaleEpisode nodes with full peer context and signal flip detection, narrative REFERENCES edges from Decisions to Entities via keyword matching, and LLM-generated decision narrative summaries on Agent nodes post-simulation. No new TUI panels (Phase 10 complete). No agent interviews (Phase 14). No social post nodes (Phase 12).

</domain>

<decisions>
## Implementation Decisions

### Write-Behind Buffer Design
- **D-01:** Async queue + flush-per-round pattern. Agents push decisions into an asyncio.Queue as they complete. A single flush task drains the queue and writes via UNWIND batch after each round completes. TUI sees per-agent updates immediately via StateStore; Neo4j receives efficient batch writes at round boundaries. Satisfies GRAPH-01 "per-agent immediate writes" intent while avoiding 700x write amplification.
- **D-02:** Standalone WriteBuffer class, separate from GraphStateManager. Buffer handles queueing logic; GraphStateManager handles Cypher operations. Clean separation, independently testable.
- **D-03:** Buffer handles new writes only (RationaleEpisode + narrative REFERENCES). Existing `write_decisions()` stays as-is — proven batch UNWIND code path is not refactored.

### RationaleEpisode Content
- **D-04:** RationaleEpisode linked via `(:Decision)-[:HAS_EPISODE]->(:RationaleEpisode)`. One-to-one with Decision. Preserves the Agent->MADE->Decision->FOR->Cycle chain from Phase 4 D-01.
- **D-05:** Full peer context string stored on RationaleEpisode. The complete formatted peer context string injected into the agent's prompt is persisted as `peer_context_received` property. Interviews can replay exactly what the agent saw. ~500-800 bytes per episode.
- **D-06:** Signal flip detection via flip_type enum. A `flip_type` field on RationaleEpisode stores the transition type (e.g., NONE, BUY_TO_SELL, SELL_TO_BUY, BUY_TO_HOLD, HOLD_TO_BUY, SELL_TO_HOLD, HOLD_TO_SELL). Round 1 episodes have flip_type=NONE. Computed at write time by comparing to the same agent's previous round Decision. Richer than a boolean for reports and interview queries.
- **D-07:** RationaleEpisode node properties: rationale (text), timestamp (datetime), peer_context_received (str, full formatted context), flip_type (str, enum value), round (int), cycle_id (str).

### Narrative Edge Matching
- **D-08:** Case-insensitive substring matching for Decision-to-Entity REFERENCES edges. For each Decision's rationale text, check if any extracted entity name appears as a case-insensitive substring. Entity names from seed injection are already clean (e.g., "Apple", "OPEC", "Fed"). No NLP dependencies.
- **D-09:** REFERENCES edges created during flush, piggybacking on the same post-round UNWIND transaction as RationaleEpisode writes. Entity names loaded once at cycle start and reused across all rounds. One extra Cypher statement per flush.

### Interview Context Prep
- **D-10:** LLM-generated decision narrative summary stored as `decision_narrative` property on Agent nodes post-simulation. Worker model (already loaded) generates a natural-language narrative per agent summarizing their 3-round arc, signal progression, key influences, and reasoning shifts.
- **D-11:** Narrative generation runs post-simulation as a batch of 100 inference calls through the governor. Worker model is already loaded at this point. Estimated ~3-4 min with governor throttling on M1 Max.

### Claude's Discretion
- WriteBuffer internal implementation details (queue size limits, flush error handling, retry logic)
- FlipType enum design (Python StrEnum, naming convention, where it lives in types.py)
- RationaleEpisode Neo4j index strategy (composite index on cycle_id + round, or single field)
- Entity name caching strategy (in-memory dict vs re-query per round)
- Narrative generation prompt design and output format
- GraphStateManager new method signatures for episode writes, narrative edge writes, and narrative generation
- How narrative generation integrates with the post-simulation flow (after write_decisions Round 3, before COMPLETE phase transition)
- Error handling for partial narrative generation failures (skip agent vs retry)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` -- GRAPH-01 (per-agent immediate writes via write-behind buffer), GRAPH-02 (RationaleEpisode nodes), GRAPH-03 (narrative REFERENCES edges)
- `.planning/ROADMAP.md` -- Phase 11 success criteria (4 criteria), dependencies (Phase 10 complete)

### Existing Implementation (Primary)
- `src/alphaswarm/graph.py` -- GraphStateManager: `write_decisions()` (line 249-336, UNWIND batch pattern to follow), `compute_influence_edges()` (line 410-483, post-round computation pattern), `_create_cycle_with_entities_tx()` (line 204-238, Entity node creation showing existing Entity schema)
- `src/alphaswarm/simulation.py` -- `run_simulation()` (line 656-882, full 3-round orchestration showing where write-behind flushes and narrative generation must integrate), `_dispatch_round()` (line 520-648, per-agent peer context formatting showing what peer_context_received string looks like), `_format_peer_context()` (line 300-330, the exact string that should be stored on RationaleEpisode)
- `src/alphaswarm/types.py` -- `AgentDecision` (signal, confidence, sentiment, rationale, cited_agents), `SignalType` enum (BUY, SELL, HOLD, PARSE_ERROR), `AgentPersona`, `SeedEvent` with entities
- `src/alphaswarm/state.py` -- StateStore for TUI per-agent updates (existing pattern for immediate per-agent writes)

### Prior Phase Context
- `.planning/phases/04-neo4j-graph-state/04-CONTEXT.md` -- D-01 (Decision as node), D-02 (INFLUENCED_BY Decision-to-Decision), D-03 (CITED relationships), D-07 (session-per-method), D-08 (minimal API surface)
- `.planning/phases/08-dynamic-influence-topology/08-CONTEXT.md` -- D-02 (influence edges computed after each round), D-04 (cumulative weights), D-06 (bracket-diverse peer selection)

### Research
- `.planning/research/SUMMARY.md` -- Pitfall 2 (write amplification), Pitfall 6 (hollow interview context), architecture approach for graph.py extensions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `write_decisions()` in `graph.py` -- UNWIND batch write pattern to follow for RationaleEpisode writes
- `_format_peer_context()` in `simulation.py` -- produces the exact peer context string to store on RationaleEpisode.peer_context_received
- `_compute_shifts()` in `simulation.py` -- signal flip computation pattern (prev vs curr comparison) to adapt for FlipType enum
- `compute_influence_edges()` in `graph.py` -- post-round computation + write pattern to follow for narrative edge creation
- `_create_cycle_with_entities_tx()` in `graph.py` -- Entity MERGE pattern and Entity node schema (name, type properties)
- `dispatch_wave()` peer_contexts parameter -- list of formatted peer context strings aligned by persona index
- `SCHEMA_STATEMENTS` in `graph.py` -- existing schema constraints/indexes to extend for RationaleEpisode

### Established Patterns
- UNWIND batch writes for all Neo4j operations
- Session-per-method pattern for GraphStateManager
- Frozen dataclasses for immutable result containers
- structlog with component-scoped loggers
- asyncio.Queue used in StateStore (rationale_queue) for async buffering

### Integration Points
- `simulation.py:run_simulation()` -- WriteBuffer.flush() calls after each `write_decisions()` call (lines 769, 825). Narrative generation after Round 3 write but before COMPLETE phase transition.
- `graph.py` -- New methods: `write_rationale_episodes()`, `write_narrative_edges()`, `write_decision_narrative()`, `read_cycle_entities()` (for entity name cache)
- `graph.py:SCHEMA_STATEMENTS` -- Add RationaleEpisode index, REFERENCES edge support
- `types.py` -- New FlipType enum
- New `write_buffer.py` module -- standalone WriteBuffer class with asyncio.Queue

</code_context>

<specifics>
## Specific Ideas

- FlipType enum values: NONE, BUY_TO_SELL, SELL_TO_BUY, BUY_TO_HOLD, HOLD_TO_BUY, SELL_TO_HOLD, HOLD_TO_SELL (7 values covering all SignalType transitions, excluding PARSE_ERROR)
- Entity name cache: load all Entity nodes for the cycle at start, reuse across 3 rounds for substring matching
- Peer context string is already formatted by `_format_peer_context()` -- store it verbatim, no re-serialization needed
- Narrative generation uses worker model (qwen3.5:9b) with a structured prompt containing the agent's persona, 3-round decisions, flip types, and cited peers
- Post-simulation narrative generation should be gated by a flag (e.g., `generate_narratives=True` on run_simulation) so tests can skip the 3-4 min inference cost
- REFERENCES edges: `(:Decision)-[:REFERENCES {match_type: "substring"}]->(:Entity)` -- match_type property allows future matching strategies

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 11-live-graph-memory*
*Context gathered: 2026-03-31*
