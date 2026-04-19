# Phase 8: Dynamic Influence Topology - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 08-dynamic-influence-topology
**Areas discussed:** Influence algorithm, Peer ranking switchover, Bracket aggregation, Miro batcher stub

---

## Influence Algorithm

### Q1: How should INFLUENCED_BY edge weights be computed?

| Option | Description | Selected |
|--------|-------------|----------|
| Citation frequency | Weight = normalized citation count. Simple, interpretable, uses existing CITED edges. | ✓ |
| Citation + agreement blend | Base from citations, boosted when citer agrees with cited agent's signal. | |
| PageRank-style recursive | Agents cited by high-influence agents get more weight. Recursive convergence. | |

**User's choice:** Citation frequency (Recommended)
**Notes:** None

### Q2: When should influence edges be computed?

| Option | Description | Selected |
|--------|-------------|----------|
| After each round | Compute after Round 1 (for R2 peers) and after Round 2 (for R3 peers). Dynamic topology shapes cascade. | ✓ |
| After full simulation | Run all 3 rounds with static ranking, compute retrospectively for queryability. | |

**User's choice:** After each round (Recommended)
**Notes:** None

### Q3: Edge creation threshold?

| Option | Description | Selected |
|--------|-------------|----------|
| All citation pairs | Every CITED relationship produces an INFLUENCED_BY edge. Let weight distinguish strong vs weak. | ✓ |
| Threshold filter | Only create edges for agents cited by 2+ peers. Reduces noise. | |
| You decide | Claude picks. | |

**User's choice:** All citation pairs (Recommended)
**Notes:** None

### Q4: Weight accumulation across rounds?

| Option | Description | Selected |
|--------|-------------|----------|
| Cumulative | Round 3 weights = Round 1 + Round 2 citations. Consistently cited agents build momentum. | ✓ |
| Per-round reset | Each round's weights computed only from immediately prior round's citations. | |
| You decide | Claude picks. | |

**User's choice:** Cumulative (Recommended)
**Notes:** None

---

## Peer Ranking Switchover

### Q1: Round 1 cold-start strategy?

| Option | Description | Selected |
|--------|-------------|----------|
| Static base | Round 1 keeps influence_weight_base. Dynamic kicks in for Round 2+. | ✓ |
| Random for Round 1 | Randomize peer selection to avoid static hierarchy. | |
| Blended always | Gradual alpha transition from static to dynamic across rounds. | |

**User's choice:** Static base (Recommended)
**Notes:** None

### Q2: Bracket diversity in peer selection?

| Option | Description | Selected |
|--------|-------------|----------|
| Pure weight ranking | Top-5 by weight regardless of bracket. | |
| Bracket-diverse top-5 | At least 3 different brackets in top-5. Fill by weight within bracket. | ✓ |
| You decide | Claude picks. | |

**User's choice:** Bracket-diverse top-5
**Notes:** User chose diversity over pure ranking to prevent echo chambers.

### Q3: Minimum bracket count in top-5?

| Option | Description | Selected |
|--------|-------------|----------|
| At least 3 brackets | Top-1 from each of top-3 brackets by weight, remaining 2 by pure weight. | ✓ |
| At least 4 brackets | Stricter diversity, may include lower-influence agents. | |
| You decide | Claude picks. | |

**User's choice:** At least 3 brackets (Recommended)
**Notes:** None

---

## Bracket Aggregation

### Q1: Where should aggregation be computed?

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory from results | Compute in Python from AgentDecision list. Reuses _aggregate_brackets() pattern. | ✓ |
| Neo4j aggregation query | Cypher query against Decision nodes by bracket. Graph-first approach. | |
| Both (compute + persist) | In-memory for immediate use, persist as BracketSummary nodes in Neo4j. | |

**User's choice:** In-memory from results (Recommended)
**Notes:** None

### Q2: Promote to simulation layer?

| Option | Description | Selected |
|--------|-------------|----------|
| Promote to simulation | BracketSummary dataclass in simulation module. SimulationResult includes per-round summaries. | ✓ |
| Keep in CLI | Stays as display concern in cli.py. | |

**User's choice:** Promote to simulation (Recommended)
**Notes:** None

---

## Miro Batcher Stub

### Q1: Stub scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Data shapes only | Pydantic models + stub batcher class that logs instead of HTTP calls. | ✓ |
| Full async batcher | Complete 2s buffer/batching logic, routed to logs. Ready to flip in v2. | |
| Minimal type stubs | Just TypedDict shapes and no-op interface. Lightest touch. | |

**User's choice:** Data shapes only (Recommended)
**Notes:** None

### Q2: Wiring into pipeline?

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone module | miro.py independent, not imported by simulation or wired into AppState. | ✓ |
| Wired into pipeline | MiroBatcher in AppState, called from run_simulation() after each round. | |

**User's choice:** Standalone module (Recommended)
**Notes:** None

---

## Claude's Discretion

- Internal structure of influence computation module
- INFLUENCED_BY edge Cypher write pattern
- BracketSummary dataclass field design details
- MiroNode/MiroConnector field details beyond core shape
- Bracket-diverse selection implementation (Cypher vs Python post-processing)
- Error handling for edge cases (zero citations, self-citations)

## Deferred Ideas

None — discussion stayed within phase scope
