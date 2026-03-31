# Phase 11: Live Graph Memory - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-03-31
**Phase:** 11-live-graph-memory
**Areas discussed:** Write-behind buffer design, RationaleEpisode content, Narrative edge matching, Interview context prep

---

## Write-Behind Buffer Design

### How should the write-behind buffer work?

| Option | Description | Selected |
|--------|-------------|----------|
| Async queue + flush-per-round | Agents push to asyncio.Queue, single flush drains via UNWIND batch after round completes. Real-time to TUI, efficient to Neo4j. | ✓ |
| Micro-batch on timer | Flush every N seconds regardless of round boundaries. More granular but adds timer complexity. | |
| True per-agent writes | Each agent writes immediately. Maximum granularity but 100+ transactions per round, connection pool risk. | |

**User's choice:** Async queue + flush-per-round
**Notes:** Best of both worlds -- per-agent TUI updates via StateStore, batch Neo4j writes at round boundaries.

### Should the buffer be standalone or internal to GraphStateManager?

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone WriteBuffer class | New class wrapping asyncio.Queue with flush(). Clean separation, independently testable. | ✓ |
| Internal to GraphStateManager | Queue + flush inside GraphStateManager. Fewer parts but mixes concerns. | |

**User's choice:** Standalone WriteBuffer class
**Notes:** None

### Should the buffer handle existing writes or only new ones?

| Option | Description | Selected |
|--------|-------------|----------|
| New writes only | Buffer for RationaleEpisode + narrative REFERENCES. Existing write_decisions() unchanged. | ✓ |
| Unify all writes | Route all Neo4j writes through buffer. Single path but refactors working code. | |

**User's choice:** New writes only
**Notes:** No risk to proven write_decisions() code path.

---

## RationaleEpisode Content

### How much peer context to store?

| Option | Description | Selected |
|--------|-------------|----------|
| Compressed summary | Peer IDs, signals, bracket mix. ~200 bytes. | |
| Full peer context string | Complete formatted string injected into prompt. ~500-800 bytes. Interviews replay exactly what agent saw. | ✓ |
| IDs only | Just peer agent IDs. Minimal but requires re-query at interview time. | |

**User's choice:** Full peer context string
**Notes:** Prioritizes interview richness over storage efficiency.

### How should signal flip detection work?

| Option | Description | Selected |
|--------|-------------|----------|
| Boolean + prev signal | signal_flipped (bool) + prev_signal (str|null). Simple, queryable. | |
| Flip type enum | flip_type field (BUY_TO_SELL, SELL_TO_HOLD, etc.). Richer for reports. | ✓ |
| Compute at query time | Derive from consecutive Decision nodes via Cypher. No duplication but complex queries. | |

**User's choice:** Flip type enum
**Notes:** More expressive categorization for reports and interview queries.

### How should RationaleEpisode link to the graph?

| Option | Description | Selected |
|--------|-------------|----------|
| Decision->RationaleEpisode | (:Decision)-[:HAS_EPISODE]->(:RationaleEpisode). One-to-one. Preserves Phase 4 chain. | ✓ |
| Agent->RationaleEpisode | (:Agent)-[:EXPERIENCED]->(:RationaleEpisode). Simpler interview traversal but breaks Decision-centric model. | |

**User's choice:** Decision->RationaleEpisode
**Notes:** Keeps Agent->MADE->Decision->FOR->Cycle chain clean from Phase 4.

---

## Narrative Edge Matching

### What matching strategy for REFERENCES edges?

| Option | Description | Selected |
|--------|-------------|----------|
| Case-insensitive substring | Check if entity name appears in rationale text. Simple, fast, deterministic. | ✓ |
| Token-level matching | Tokenize and match on exact token overlap. Better word boundaries but added complexity. | |
| LLM-assisted matching | Worker LLM identifies entity references. Most accurate but 300 extra inference calls. | |

**User's choice:** Case-insensitive substring
**Notes:** Entity names from seed injection are already clean. No NLP dependencies needed.

### When should REFERENCES edges be created?

| Option | Description | Selected |
|--------|-------------|----------|
| During flush | Same UNWIND batch as RationaleEpisode writes. Entity names cached at cycle start. | ✓ |
| Post-simulation batch | Separate pass after simulation. Clean separation but delays data availability. | |

**User's choice:** During flush
**Notes:** Piggybacks on existing transaction, one extra Cypher statement per flush.

---

## Interview Context Prep

### Pre-compute decision narrative on Agent nodes?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, post-simulation | Compute summary after simulation. Stored as decision_narrative on Agent node. | ✓ |
| No, derive at interview time | Traverse Decision + Episode nodes dynamically. More flexible but adds query latency. | |
| Yes, per-round incremental | Update running narrative after each round flush. Always current but more complex writes. | |

**User's choice:** Yes, post-simulation
**Notes:** Interviews load narrative instantly without traversal.

### How should the narrative be generated?

| Option | Description | Selected |
|--------|-------------|----------|
| Template-based | Python string template from data. Zero inference cost, deterministic, instant. | |
| LLM-generated | Worker LLM generates natural-language narrative per agent. ~3-4 min for 100 agents. | ✓ |

**User's choice:** LLM-generated
**Notes:** User asked for pros/cons analysis before deciding. Chose LLM-generated for richer, more natural interview context despite inference cost. Worker model already loaded post-simulation.

---

## Claude's Discretion

- WriteBuffer internals (queue size, error handling, retry)
- FlipType enum design (StrEnum, naming, location)
- RationaleEpisode index strategy
- Entity name caching details
- Narrative generation prompt design
- New GraphStateManager method signatures
- Post-simulation narrative integration flow
- Partial narrative failure handling

## Deferred Ideas

None -- discussion stayed within phase scope
