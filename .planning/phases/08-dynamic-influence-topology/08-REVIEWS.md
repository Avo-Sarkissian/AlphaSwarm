---
phase: 8
reviewers: [gemini, codex]
reviewed_at: 2026-03-26T00:00:00Z
plans_reviewed: [08-01-PLAN.md, 08-02-PLAN.md, 08-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 8: Dynamic Influence Topology

## Gemini Review

I have reviewed the implementation plans for **Phase 8: Dynamic Influence Topology**. Overall, the plans are well-structured, logically sequenced, and align closely with the architectural goals of the AlphaSwarm project.

### Summary

The three plans effectively transition the simulation from a static hierarchy to an organic, citation-based influence model. **Plan 01** builds the necessary mathematical and graph primitives, **Plan 02** integrates these into the core simulation loop with a clever hybrid of Neo4j persistence and in-memory selection for performance, and **Plan 03** provides a clean, decoupled interface for future Miro visualization. The strategy of using cumulative weights across rounds ensures that influence "builds" over the course of the simulation.

### Strengths

- **Hybrid Performance Model:** Moving to in-memory peer selection for Rounds 2 and 3 (Plan 02) significantly reduces Neo4j round-trip latency during the high-concurrency inference phase while still persisting the results for post-simulation analysis.
- **Bracket Diversity Logic:** The `select_diverse_peers` algorithm (Plan 01) is robust; it prevents echo chambers by mandating a 3-bracket minimum before falling back to pure weight, which is critical for a "consensus" simulation.
- **Cumulative Influence:** Implementing the weights as cumulative (Round 1 + Round 2) prevents "flash-in-the-pan" citations from completely overwriting established influence, providing more stable simulation dynamics.
- **Clean Decoupling:** Plan 03 keeps the `miro.py` module independent, avoiding circular dependencies and keeping the "visualizer" logic separate from the "engine" logic.

### Concerns

- **[MEDIUM] Cypher Read Pattern Discrepancy:** In Plan 01, the provided Cypher read pattern returns `agent_id` and `count`, but **D-03** requires creating `INFLUENCED_BY` edges for *all citation pairs*. To satisfy D-03, the query must return the source (who cited) and the target (who was cited), not just a flat count per agent.
- **[LOW] Normalization Denominator:** The formula `weight = citations_received / total_agents` assumes `total_agents` is the global swarm size (100). If some agents fail to produce a decision in a round (e.g., due to LLM errors), this denominator might need to be "total successful decisions in round" to keep weights normalized correctly.
- **[LOW] Memory Growth in SimulationResult:** Adding `BracketSummary` tuples for every round to `SimulationResult` is fine for 100 agents, but ensure these are `frozen=True` as planned to keep the `SimulationResult` hashable and immutable.
- **[LOW] Miro Batcher Buffer Logic:** The requirements mention a "2s buffer," but the Plan 03 interface `push_batch(payload)` implies the *caller* has already batched the data. If the `MiroBatcher` is intended to be a "collect and fire" utility, it may need an `add_node()` method and an internal timer. However, for a round-based simulation, sending a bulk payload at the end of the round satisfies the "no single-node updates" constraint.

### Suggestions

- **Refine Cypher Read:** Update the Plan 01 read query to capture source-target pairs:
  ```sql
  MATCH (src:Agent)-[:DECIDED]->(d:Decision)-[:CITED]->(tgt:Agent)
  WHERE d.cycle_id = $cycle_id AND d.round <= $up_to_round
  RETURN src.id AS source_id, tgt.id AS target_id
  ```
  Then, calculate the global influence weight for each `target_id` in Python and apply it to the source-target pairs.
- **Weight Persistence:** Ensure the `INFLUENCED_BY` edges in Neo4j include a `cumulative: true/false` property or similar, so users can distinguish between "influence earned in this specific round" vs "total influence at this point in the simulation."
- **Logging the "Diverse Selection":** In `select_diverse_peers`, add a `structlog` debug event that captures when the "3-bracket diversity" fallback is triggered (i.e., when fewer than 3 brackets have citations), as this is a key signal for simulation health.
- **Miro Positioning:** For the `MiroNode` coordinates (`x`, `y`), consider a simple layout utility in `miro.py` to prevent all nodes from stacking at `(0,0)`.

### Risk Assessment: LOW

The risk is low because the system maintains a fallback to the Round 1 "static" path. If the dynamic weight computation fails or returns no citations, the system can gracefully continue using the base weights. The most complex part is the cumulative Cypher query, but since it's scoped to a single `cycle_id`, performance will remain high even with hundreds of edges.

**Recommendation:** Proceed with Wave 1 (Plan 01 and Plan 03) in parallel, then follow with Wave 2 (Plan 02).

---

## Codex Review

### Overall

The wave split is mostly right: Plan 01 defines the core primitives, Plan 02 wires them into the live cascade, and Plan 03 stays isolated. The main delivery risk is the Plan 01/02 contract. The influence-edge computation is under-specified in a way that can produce the wrong topology, and the zero-citation fallback is not defined strongly enough for a reliable Round 2/3 path.

### Plan 01: Influence Computation Primitives

**Summary**

Directionally strong. Splitting topology computation, peer selection, and bracket summaries into reusable primitives is the correct shape for the phase. The biggest issue is that the proposed Cypher read pattern does not actually capture source-target influence pairs, so as written it cannot fully satisfy the topology or queryability goals.

**Strengths**
- Clean separation of computation from orchestration.
- Moves bracket aggregation toward the simulation layer, which aligns with D-08.
- Explicitly calls out cumulative weights, self-citation filtering, and zero-citation handling.
- Diverse peer selection as a pure function is a good replacement for per-agent Neo4j reads later.

**Concerns**
- **[HIGH]** The proposed citation read query only returns cited-agent totals, not who cited whom. That is not enough to create queryable `INFLUENCED_BY` edges or answer "who influenced this agent?"
- **[HIGH]** `compute_influence_edges()` does not have a defined return contract, but Plan 02 depends on it returning usable weights for peer selection.
- **[HIGH]** `select_diverse_peers()` does not explicitly exclude the requesting agent or `PARSE_ERROR` decisions, both of which can contaminate peer context.
- **[MEDIUM]** Zero-citation rounds say "no edges," but the plan does not define what the next-round selector should do with empty dynamic weights.
- **[MEDIUM]** Duplicate agent IDs inside `cited_agents` are not addressed. The current model allows repeats, which can inflate influence unless deduped.
- **[MEDIUM]** The roadmap wording mentions citation and agreement patterns, but the plan implements citation frequency only. That may be correct if D-01 overrides it, but the spec mismatch should be resolved explicitly.
- **[MEDIUM]** Using `CREATE` per round without clarifying snapshot semantics can leave multiple parallel edges for the same pair and ambiguous reads.
- **[LOW]** `BracketSummary` does not explicitly preserve configured bracket order or zero-count brackets, both of which matter for matching current CLI behavior.

**Suggestions**
- Replace the read path with a pair-aware query, or compute weights in Python from round decisions and only persist edge snapshots to Neo4j.
- Define `compute_influence_edges()` explicitly as returning `dict[str, float]` for cumulative per-agent weights plus an edge count/result summary.
- Make `select_diverse_peers()` accept `current_agent_id` and exclude self plus invalid peers.
- Add deterministic tie-breaking for equal weights.
- Add integration tests for edge direction, cumulative round behavior, self-citation filtering, duplicate citations, and zero-citation rounds.

**Risk Assessment: HIGH** — this is the phase-critical logic and the current query shape would not correctly produce the intended topology.

---

### Plan 02: Simulation Pipeline Wiring

**Summary**

This is the right architectural direction. Moving Round 2/3 peer selection in-memory removes the current per-agent Neo4j read path and should improve latency and reduce pool pressure. The main gaps are fallback behavior, API definition with Plan 01, and underestimated test churn.

**Strengths**
- Inserts influence recomputation at the correct lifecycle boundaries.
- Uses previous-round decisions for context while allowing cumulative weights across rounds.
- Promotes bracket summaries into `RoundCompleteEvent` and `SimulationResult`, which fits D-08.
- Keeps Round 1 cold-start behavior separate from dynamic rounds.

**Concerns**
- **[HIGH]** The plan does not define behavior when dynamic weights are empty after a zero-citation round.
- **[HIGH]** Test impact is understated. Adding required fields to `RoundCompleteEvent` and `SimulationResult` will also break existing CLI tests, not just simulation tests.
- **[MEDIUM]** `_dispatch_round()` will need an explicit adapter from `prev_decisions` + persona metadata into the peer objects/context formatter expects.
- **[MEDIUM]** Keeping `_aggregate_brackets()` as a fallback risks two aggregation implementations drifting apart.
- **[MEDIUM]** Adding `brackets` to `run_simulation()` increases signature churn across tests and callers; that scope should be called out.
- **[LOW]** The plan does not say whether Round 1 standalone reporting will reuse the new summary type or remain split.

**Suggestions**
- Define the empty-weight fallback now. Safest option: fall back to base `influence_weight_base` ordering for that round.
- Have `select_diverse_peers()` return a format-compatible peer structure so `_format_peer_context()` can stay stable.
- Expand the file/test list to include `tests/test_cli.py`.
- If `_aggregate_brackets()` stays, make it a thin adapter over `BracketSummary` instead of a separate implementation.
- Keep the Plan 01/02 interface very small and explicit before implementation starts.

**Risk Assessment: MEDIUM** — direction is good, but correctness depends on clarifying the Plan 01 contract and fallback behavior.

---

### Plan 03: Miro Batcher Stub

**Summary**

This is the cleanest plan. The scope is controlled, the isolation is appropriate, and it avoids premature integration. Most remaining issues are minor contract details rather than architectural problems.

**Strengths**
- Correctly isolated from simulation and graph concerns.
- Uses explicit typed payload models for a future integration boundary.
- Log-only async methods fit the "no live API calls" requirement.
- Surfaces the 2-second buffer setting without forcing immediate runtime wiring.

**Concerns**
- **[MEDIUM]** `metadata: dict[...] = {}` is a mutable default and should use `Field(default_factory=dict)`.
- **[MEDIUM]** Frozen Pydantic models with `list` fields are only shallowly immutable.
- **[MEDIUM]** `board_id` exists on both the batcher and payload, but mismatch handling is undefined.
- **[MEDIUM]** The interface mentions a 2-second buffer, but actual buffering semantics are not described.
- **[LOW]** `timestamp: str` weakens validation compared with `datetime`.
- **[LOW]** Logging full payloads could get noisy or expensive.

**Suggestions**
- Use `Field(default_factory=dict)` for `metadata`.
- Prefer tuples for `nodes` and `connectors` if immutability matters.
- Either remove one `board_id` source or validate equality.
- Clarify whether this version is config-only buffering or whether enqueue/flush behavior is expected.
- Define a fixed structlog event shape with counts instead of dumping full payloads.

**Risk Assessment: LOW** — isolated, small in scope, not on the critical simulation path.

**Bottom Line:** Plan 03 is ready with minor contract fixes. Plan 02 is sound once its fallback and test scope are tightened. Plan 01 needs the most revision before implementation, specifically around pair-aware influence modeling and the exact API it exposes to Plan 02.

---

## Consensus Summary

Phase 8 reviewed by 2 AI systems (Gemini, Codex).

### Agreed Strengths

- **Hybrid in-memory + Neo4j architecture** — Both reviewers praised the decision to compute influence weights in Neo4j but do peer selection in Python, reducing per-round query load.
- **Bracket diversity logic** — Both highlighted `select_diverse_peers` as well-designed for preventing echo chambers.
- **Cumulative influence weights** — Both affirmed D-04 (cumulative across rounds) as architecturally sound.
- **Miro module isolation** — Both agreed Plan 03 is the cleanest plan and its decoupling from the simulation layer is the right call.

### Agreed Concerns

1. **[HIGH] Cypher read pattern is pair-unaware** — The proposed `MATCH (d:Decision)-[:CITED]->(a:Agent)` query aggregates citation counts per target but does not return `(source, target)` pairs. This means `INFLUENCED_BY` edges cannot encode directionality correctly, and the "who influenced this agent?" query (Success Criterion 5) cannot be satisfied. Both reviewers independently flagged this. **Resolution: use a pair-aware query or derive pairs from in-memory round decisions.**

2. **[HIGH] Zero-citation fallback is undefined** — Both reviewers noted that when Round 1 produces zero citations (which is the expected cold-start case per Pitfall 1 in RESEARCH.md), the plan says "no edges" but does not define what `_dispatch_round` should do with empty weights for Round 2. **Resolution: explicit fallback to `influence_weight_base` ordering when weights dict is empty.**

3. **[MEDIUM] `select_diverse_peers` needs self-exclusion guard** — Both reviewers noted the agent must not appear in its own peer list. The current plan spec doesn't explicitly guard this. **Resolution: add `agent_id` exclusion to the candidate filtering step.**

4. **[MEDIUM] `metadata: dict = {}` mutable default in MiroNode** — Both reviewers caught the mutable default in the frozen Pydantic model. **Resolution: `Field(default_factory=dict)`.**

### Divergent Views

- **Plan 01 risk level:** Codex rates Plan 01 as **HIGH** risk due to the query contract gap. Gemini rates overall risk as **LOW** because the static fallback provides a safety net. This divergence is worth investigating — the query gap is real but whether it blocks a working simulation depends on whether the fallback path can carry the simulation through Phase 8 testing.
- **Miro buffer semantics:** Gemini is satisfied that caller-side batching (one payload per round) satisfies the "no single-node" constraint. Codex wants explicit enqueue/flush semantics defined. Given D-09 is stub-only, caller-side batching per round is the intended model — this is probably not a blocker.
- **Normalization denominator:** Only Gemini raised the question of `total_agents` vs "successful decisions." This edge case matters if LLM failures during a round leave decision gaps. Low probability but worth a note in the implementation.

---

*To incorporate feedback:*
```
/gsd:plan-phase 8 --reviews
```
