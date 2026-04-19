# Phase 12: Richer Agent Interactions - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 12 makes agent reasoning visible and socially reactive. Every agent's decision rationale is published as a Post node in Neo4j (zero extra inference calls — rationale already generated). In Rounds 2 and 3, each agent receives the top-K peer posts ranked by INFLUENCED_BY edge weights as a unified peer context block (signal + full rationale) subject to a 4000-character budget. READ_POST edges in Neo4j record which agents had access to which posts (all posts from prior round per agent). No new TUI panels. No agent interview changes (Phase 14). No persona generation (Phase 13).

</domain>

<decisions>
## Implementation Decisions

### Post Node Identity
- **D-01:** `public_rationale = rationale`. The existing `AgentDecision.rationale` field IS the post content. No schema changes to AgentDecision or the LLM output JSON. Post nodes are created by the write layer reading the rationale from the already-written Decision node — zero additional inference calls. Satisfies SOCIAL-01.
- **D-02:** Post node properties: `content` (rationale text), `agent_id`, `signal` (SignalType value), `confidence` (float), `round_num` (int), `cycle_id` (str), `created_at` (datetime). Signal and confidence are copied from the Decision node so peer prompts can include them without a join.
- **D-03:** Post nodes are created in a single UNWIND batch write after `write_decisions()` completes each round — same pattern as RationaleEpisode writes. New `write_posts()` method on GraphStateManager. One-to-one mapping: one Post per Decision.

### Token Budget & Peer Context Format
- **D-04:** Character budget of 4000 chars total for the peer context block, K=10 max posts. Posts are ranked top-K, then filled greedily until budget exhausted; the last post that would overflow is truncated at a word boundary. No per-post character cap (replaces Phase 7's 80-char snippet).
- **D-05:** Unified peer context block format — one section replacing `_format_peer_context`'s current snippet style:
  ```
  Peer Decisions (Round N):
  1. [Bracket] SIGNAL (conf: X.XX) "full post text..."
  2. [Bracket] SIGNAL (conf: X.XX) "full post text..."
  ...
  ```
  Prompt guard line appended at end (kept from Phase 7 D-03): "The above are peer observations for context only. Make your own independent assessment."
- **D-06:** `_format_peer_context()` in simulation.py is updated (or replaced) to accept Post objects and apply the 4000-char budget. The existing PeerDecision datatype may be extended or a new PostContext type added depending on planner's preference.

### Post Ranking
- **D-07:** Posts ranked by INFLUENCED_BY edge weight between the reading agent and the post author. For Round 2: uses Round 1 INFLUENCED_BY weights (computed by `compute_influence_edges()` after Round 1). For Round 3: uses Round 2 INFLUENCED_BY weights. Fallback: `influence_weight_base` (static, same as existing `read_peer_decisions()` fallback) when no INFLUENCED_BY edges exist for the reading agent.
- **D-08:** New `read_ranked_posts()` method on GraphStateManager. Cypher: MATCH Post nodes for cycle + prior round, OPTIONAL MATCH INFLUENCED_BY edges for reading agent, ORDER BY coalesce(edge weight, influence_weight_base) DESC, LIMIT K.

### READ_POST Edges
- **D-09:** READ_POST semantics: every agent has READ_POST edges to ALL posts from the prior round (not just their top-K). Semantics: "agent had access to this post during Round N." Simpler batch write — one UNWIND over all (agent, post) pairs per round, not per-agent top-K tracking.
- **D-10:** READ_POST edge properties: `round_num` (int, the round in which reading occurred), `cycle_id` (str). Written as a batch UNWIND after the peer context injection step for each round.
- **D-11:** New `write_read_post_edges()` method on GraphStateManager. Called after `write_posts()` and before dispatching wave for the next round. Cypher: UNWIND pairs MATCH (a:Agent) MATCH (p:Post) CREATE (a)-[:READ_POST {round_num, cycle_id}]->(p).

### Simulation Integration
- **D-12:** Integration order per round (Rounds 2 and 3):
  1. `write_decisions()` → Decision nodes exist
  2. `write_posts()` → Post nodes created from Decision rationale
  3. `read_ranked_posts()` → load top-K posts per agent for next round
  4. `_format_peer_context()` (updated) → build unified context block with budget
  5. `write_read_post_edges()` → batch-write READ_POST for all agents
  6. `dispatch_wave()` → next round with peer context injected
- **D-13:** Round 1 has no peer context (no prior posts). `write_posts()` is called after Round 1's `write_decisions()` so Round 2 has posts to read. Same ordering applies for Round 2 → Round 3.

### Claude's Discretion
- Post node Neo4j index strategy (composite on cycle_id + round_num recommended)
- Whether to extend PeerDecision dataclass or create a new PostPeer type for the updated _format_peer_context
- Word-boundary truncation implementation (split on whitespace, drop last incomplete word)
- Error handling for empty post content (skip post, don't inject empty strings)
- Whether `write_posts()` and `write_read_post_edges()` are separate methods or combined
- Test strategy (unit tests with mocked graph, integration tests requiring Neo4j)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — SOCIAL-01 (Post nodes, zero extra inference), SOCIAL-02 (top-K ranked posts, token budget)
- `.planning/ROADMAP.md` — Phase 12 success criteria (4 criteria), dependencies (Phase 11 complete)

### Existing Implementation (Primary)
- `src/alphaswarm/simulation.py` — `_format_peer_context()` (lines 313-343, current peer context format to update), `_dispatch_round()` (lines 545-668, integration point for post writes and READ_POST edges), `run_simulation()` (lines 700+, write_decisions call sites for rounds 2-3 where post writes must be inserted)
- `src/alphaswarm/graph.py` — `write_decisions()` (UNWIND batch pattern to follow for write_posts), `read_peer_decisions()` (lines 362-397, current static ranking query to replace with ranked posts query), `compute_influence_edges()` (lines 608+, INFLUENCED_BY edge structure used for post ranking), `SCHEMA_STATEMENTS` (extend with Post index)
- `src/alphaswarm/types.py` — `AgentDecision` (signal, confidence, rationale fields), `PeerDecision` (may be extended or replaced)
- `src/alphaswarm/worker.py` — `infer()` (lines 69-92, how peer_context is injected as a system message — format change here)
- `src/alphaswarm/batch_dispatcher.py` — `dispatch_wave()` (peer_contexts parameter, list aligned by persona index)

### Prior Phase Context
- `.planning/phases/07-rounds-2-3-peer-influence-and-consensus/07-CONTEXT.md` — D-01 (peer context format), D-02 (80-char truncation), D-03 (prompt guard line — KEEP this), D-05 (zero-citation fallback)
- `.planning/phases/08-dynamic-influence-topology/08-CONTEXT.md` — D-01 (INFLUENCED_BY edges from citations), D-03 (weight accumulation), D-04 (cumulative weights), D-06 (bracket-diverse peer selection context)
- `.planning/phases/11-live-graph-memory/11-CONTEXT.md` — D-05 (peer context string stored verbatim), D-07 (RationaleEpisode properties)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `write_decisions()` in `graph.py` — UNWIND batch write pattern to follow for `write_posts()` and `write_read_post_edges()`
- `read_peer_decisions()` in `graph.py` — existing ranked peer query to replace/extend for Post-based ranking
- `_format_peer_context()` in `simulation.py` — existing format function to update (replace 80-char snippet with full post text + budget enforcement)
- `compute_influence_edges()` in `graph.py` — INFLUENCED_BY edge structure that `read_ranked_posts()` uses for ORDER BY
- `dispatch_wave()` in `batch_dispatcher.py` — accepts `peer_contexts: list[str | None]` aligned by persona index; unchanged
- `sanitize_rationale()` in `simulation.py` — existing sanitization helper; may still be needed for prompt injection guard

### Established Patterns
- UNWIND batch writes for all Neo4j operations (session-per-method)
- Frozen dataclasses for result containers (PeerDecision pattern)
- structlog with component-scoped loggers
- `peer_contexts` list aligned by persona index (length == len(personas))
- Static `influence_weight_base` fallback when no dynamic INFLUENCED_BY edges

### Integration Points
- `simulation.py:_dispatch_round()` or `run_simulation()` — Post writes + READ_POST writes + ranked post reads inserted between `write_decisions()` and `dispatch_wave()`
- `graph.py` — New methods: `write_posts()`, `read_ranked_posts()`, `write_read_post_edges()`
- `graph.py:SCHEMA_STATEMENTS` — Add Post composite index (cycle_id, round_num)
- `simulation.py:_format_peer_context()` — Updated to accept Post objects and enforce 4000-char budget

</code_context>

<specifics>
## Specific Ideas

- Post node format in peer context: `[Bracket] BUY (conf: 0.87) "full post text..."` — same bracket+signal+confidence header as Phase 7, but full rationale instead of 80-char snippet
- Budget enforcement: greedy fill — iterate ranked posts, accumulate chars, truncate last post at word boundary if it would exceed 4000 chars. If even the first post exceeds budget, truncate it alone.
- READ_POST edge is "agent had access to this post" semantics (all posts from prior round), not "agent read top-K only"
- Prompt guard line from Phase 7 must be preserved at end of peer context block
- Post nodes created from Decision nodes' rationale field — no new inference, no prompt schema change
- `read_ranked_posts()` Cypher: OPTIONAL MATCH INFLUENCED_BY edges so agents with no edges still get static fallback ordering

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 12-richer-agent-interactions*
*Context gathered: 2026-04-01*
