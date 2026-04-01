# Phase 12: Richer Agent Interactions - Research

**Researched:** 2026-04-01
**Domain:** Neo4j graph writes/reads, peer context formatting, simulation integration
**Confidence:** HIGH

## Summary

Phase 12 transforms the existing peer influence mechanism from 80-character rationale snippets into full published rationale posts, creating observable social dynamics through Post nodes in Neo4j. The implementation is well-bounded: zero extra inference calls (rationale already exists on Decision nodes), three new graph methods (`write_posts()`, `read_ranked_posts()`, `write_read_post_edges()`), one updated function (`_format_peer_context()`), and integration wiring in `run_simulation()`. The codebase has mature UNWIND batch write patterns and frozen dataclass conventions that Phase 12 follows directly.

The primary complexity lies in the simulation integration sequencing -- Post writes and READ_POST edges must be inserted between existing `write_decisions()` and `dispatch_wave()` calls at precise points in `run_simulation()`, and the updated `_format_peer_context()` must enforce a 4000-character budget with greedy fill and word-boundary truncation. The existing `_dispatch_round()` function (which currently handles both dynamic and static peer selection paths) will need to be modified to use `read_ranked_posts()` instead of `read_peer_decisions()` / in-memory PeerDecision construction.

**Primary recommendation:** Follow the existing UNWIND batch write pattern from `write_decisions()` and `write_rationale_episodes()` exactly. Create a `RankedPost` frozen dataclass as the return type from `read_ranked_posts()`. Update `_format_peer_context()` to accept `RankedPost` objects and enforce the 4000-char budget. Insert post writes and READ_POST edge writes into `run_simulation()` at the decision points specified in CONTEXT.md D-12/D-13.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `public_rationale = rationale`. The existing `AgentDecision.rationale` field IS the post content. No schema changes to AgentDecision or the LLM output JSON. Post nodes are created by the write layer reading the rationale from the already-written Decision node -- zero additional inference calls.
- **D-02:** Post node properties: `content` (rationale text), `agent_id`, `signal` (SignalType value), `confidence` (float), `round_num` (int), `cycle_id` (str), `created_at` (datetime). Signal and confidence are copied from the Decision node so peer prompts can include them without a join.
- **D-03:** Post nodes are created in a single UNWIND batch write after `write_decisions()` completes each round -- same pattern as RationaleEpisode writes. New `write_posts()` method on GraphStateManager. One-to-one mapping: one Post per Decision.
- **D-04:** Character budget of 4000 chars total for the peer context block, K=10 max posts. Posts are ranked top-K, then filled greedily until budget exhausted; the last post that would overflow is truncated at a word boundary. No per-post character cap (replaces Phase 7's 80-char snippet).
- **D-05:** Unified peer context block format -- one section replacing `_format_peer_context`'s current snippet style. Format: numbered list with `[Bracket] SIGNAL (conf: X.XX) "full post text..."`. Prompt guard line preserved.
- **D-06:** `_format_peer_context()` in simulation.py is updated (or replaced) to accept Post objects and apply the 4000-char budget.
- **D-07:** Posts ranked by INFLUENCED_BY edge weight between the reading agent and the post author. For Round 2: uses Round 1 INFLUENCED_BY weights. For Round 3: uses Round 2 INFLUENCED_BY weights. Fallback: `influence_weight_base` when no INFLUENCED_BY edges exist.
- **D-08:** New `read_ranked_posts()` method on GraphStateManager. Cypher: MATCH Post nodes for cycle + prior round, OPTIONAL MATCH INFLUENCED_BY edges for reading agent, ORDER BY coalesce(edge weight, influence_weight_base) DESC, LIMIT K.
- **D-09:** READ_POST semantics: every agent has READ_POST edges to ALL posts from the prior round. Simpler batch write -- one UNWIND over all (agent, post) pairs per round.
- **D-10:** READ_POST edge properties: `round_num` (int, the round in which reading occurred), `cycle_id` (str).
- **D-11:** New `write_read_post_edges()` method on GraphStateManager. Cypher: UNWIND pairs MATCH (a:Agent) MATCH (p:Post) CREATE (a)-[:READ_POST {round_num, cycle_id}]->(p).
- **D-12:** Integration order per round: write_decisions -> write_posts -> read_ranked_posts -> _format_peer_context -> write_read_post_edges -> dispatch_wave.
- **D-13:** Round 1 has no peer context. `write_posts()` is called after Round 1's `write_decisions()` so Round 2 has posts to read.

### Claude's Discretion
- Post node Neo4j index strategy (composite on cycle_id + round_num recommended)
- Whether to extend PeerDecision dataclass or create a new PostPeer/RankedPost type
- Word-boundary truncation implementation
- Error handling for empty post content
- Whether `write_posts()` and `write_read_post_edges()` are separate methods or combined
- Test strategy (unit tests with mocked graph, integration tests requiring Neo4j)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SOCIAL-01 | Agents produce a "public rationale post" as part of their decision output, stored as Post nodes in Neo4j (zero extra inference calls) | D-01, D-02, D-03: Post nodes created from existing Decision.rationale via write_posts() UNWIND batch write. No inference changes needed. |
| SOCIAL-02 | Top-K ranked posts (by influence weight) injected into peer context for Rounds 2-3 with token budget management | D-04 through D-08: read_ranked_posts() queries Post nodes ranked by INFLUENCED_BY edge weight, _format_peer_context() enforces 4000-char budget with greedy fill. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). All new graph methods must be async.
- **Local First:** All inference local via Ollama. Phase 12 adds zero inference calls (confirmed by D-01).
- **Memory Safety:** No new memory concerns -- Post nodes are lightweight string storage in Neo4j.
- **Runtime:** Python 3.11+ strict typing. All new types must use frozen dataclasses or frozen Pydantic models.
- **State/Memory:** Neo4j Community via async driver. Session-per-method pattern.
- **Testing:** `pytest-asyncio` with `uv run pytest`.
- **Logging:** `structlog` with component-scoped loggers.
- **Validation:** `pydantic` for config models, frozen dataclasses for result containers.

## Architecture Patterns

### Existing Codebase Patterns (MUST follow)

#### Pattern 1: UNWIND Batch Write (session-per-method)
**What:** All Neo4j writes use UNWIND with session-per-method isolation.
**Where exemplified:** `write_decisions()` (graph.py:250-307), `write_rationale_episodes()` (graph.py:434-499)
**Apply to:** `write_posts()`, `write_read_post_edges()`

Structure for each new write method:
1. Public async method with error handling wrapping `session.execute_write()`
2. Private `@staticmethod` transaction function (`_batch_write_posts_tx`, `_batch_write_read_post_edges_tx`)
3. Cypher uses `UNWIND $params AS p` then `MATCH` existing nodes then `CREATE` new nodes/edges
4. Empty-list guard at method top (return immediately if no records)
5. Wrap `Neo4jError` in `Neo4jWriteError`
6. Log with `structlog` at INFO level with count

#### Pattern 2: Frozen Dataclass Result Containers
**What:** All cross-boundary data types are frozen dataclasses or frozen Pydantic models.
**Where exemplified:** `PeerDecision` (graph.py:28-37), `EpisodeRecord` (write_buffer.py:34-48), `RoundDispatchResult` (simulation.py:53-61)
**Apply to:** New `RankedPost` dataclass for `read_ranked_posts()` return type.

#### Pattern 3: Peer Context Flow (persona-aligned lists)
**What:** `peer_contexts` is a `list[str | None]` aligned by persona index. Length MUST equal `len(personas)`.
**Where exemplified:** `_dispatch_round()` (simulation.py:534-669), `dispatch_wave()` (batch_dispatcher.py:81-168)
**Apply to:** Updated `_dispatch_round()` must produce peer_contexts from ranked posts, still aligned by persona index.

#### Pattern 4: Integration Sequencing in run_simulation()
**What:** Each round follows a strict order: dispatch -> pair -> write_decisions -> write_buffer -> compute_influence -> compute_summaries -> StateStore updates -> callback.
**Where exemplified:** run_simulation() lines 796-870 (Round 2), 878-944 (Round 3).
**Apply to:** Post writes and READ_POST edges inserted per D-12 ordering.

### Recommended New Types

#### RankedPost (frozen dataclass)
```python
@dataclass(frozen=True)
class RankedPost:
    """A peer's published rationale post ranked by influence weight."""
    post_id: str       # Unique ID for the Post node (for READ_POST edge targeting)
    agent_id: str
    bracket: str
    signal: str        # SignalType value string
    confidence: float
    content: str       # Full rationale text
    influence_weight: float  # Resolved weight (dynamic or static fallback)
    round_num: int
```

**Why new type instead of extending PeerDecision:** `RankedPost` carries `post_id` (needed for READ_POST edges), `content` (semantic distinction from rationale -- this is the published post), and `influence_weight` (resolved from INFLUENCED_BY or fallback). PeerDecision carries `sentiment` which is unused in the new peer context format. Clean separation of concerns -- existing PeerDecision and its tests remain unchanged.

### Schema Extension

Add to `SCHEMA_STATEMENTS`:
```python
"CREATE INDEX post_cycle_round IF NOT EXISTS FOR (p:Post) ON (p.cycle_id, p.round_num)",
```

**Reasoning:** `read_ranked_posts()` queries `MATCH (p:Post) WHERE p.cycle_id = $cycle_id AND p.round_num = $round_num` -- composite index on (cycle_id, round_num) is the critical access pattern. This follows the existing `decision_cycle_round` and `episode_cycle_round` index patterns.

### Anti-Patterns to Avoid
- **Per-agent transactions for Post writes:** NEVER write 100 individual Post nodes. Use UNWIND batch (D-03).
- **Per-agent Neo4j reads for ranked posts:** The `read_ranked_posts()` query runs once per agent (100 sequential reads for Round 2). This matches the existing `read_peer_decisions()` pattern. Do NOT attempt to batch 100 agent reads into one query -- the per-agent INFLUENCED_BY edge lookup requires agent-specific context.
- **Modifying AgentDecision schema:** D-01 explicitly forbids this. Post content comes from the existing `rationale` field.
- **Truncating in Cypher:** Budget enforcement is Python-side logic in `_format_peer_context()`, not in the Neo4j query.

## Detailed Code Analysis

### Current _format_peer_context() (simulation.py:313-343)
```python
def _format_peer_context(
    peers: list[PeerDecision],
    source_round: int,
) -> str:
```
- Accepts `list[PeerDecision]`
- Uses `sanitize_rationale(peer.rationale, max_len=80)` for truncation
- Format: `{i}. [{peer.bracket}] {peer.signal.upper()} (conf: {peer.confidence:.2f}) "{snippet}"`
- Appends prompt guard line
- Returns empty string for empty peers list

**What changes:** Signature changes to accept `list[RankedPost]`. Removes 80-char `sanitize_rationale()` call. Adds 4000-char greedy budget enforcement. Keeps header and prompt guard format.

### Current _dispatch_round() (simulation.py:534-669)
- Two paths: `use_dynamic` (in-memory PeerDecision construction from prev_decisions) and static fallback (Neo4j `read_peer_decisions()`)
- Dynamic path: calls `select_diverse_peers()` then constructs `PeerDecision` objects in-memory
- Static path: calls `graph_manager.read_peer_decisions()` per agent sequentially
- Both paths call `_format_peer_context()` then build `peer_contexts` list

**What changes:** Both paths replaced by a single path that calls `graph_manager.read_ranked_posts()` per agent. The `select_diverse_peers()` function and in-memory PeerDecision construction are no longer needed for this function (they may be kept for backward compatibility but are not called). The `read_peer_decisions()` static fallback path is also replaced.

**Critical consideration:** `_dispatch_round()` currently returns `RoundDispatchResult` with `peer_contexts` list. This remains unchanged -- the peer_contexts are still built from `_format_peer_context()`, just with different input types and budget logic.

### Current run_simulation() Integration Points
Round 2 (lines 796-870):
```
1. _dispatch_round() -> round2_result (includes peer_contexts)
2. write_decisions(round2_decisions, cycle_id, round_num=2) -> round2_ids
3. WriteBuffer push + flush (RationaleEpisode writes)
4. compute_influence_edges(cycle_id, up_to_round=2) -> round2_weights
5. compute_bracket_summaries -> StateStore -> callback
```

**New insertion points per D-12:**
After step 2 (`write_decisions`): call `write_posts(round2_decisions, cycle_id, round_num=2)`
But wait -- the D-12 ordering says:
```
1. write_decisions() -> Decision nodes exist
2. write_posts() -> Post nodes created from Decision rationale
3. read_ranked_posts() -> load top-K posts per agent for NEXT round
4. _format_peer_context() -> build unified context block with budget
5. write_read_post_edges() -> batch-write READ_POST for all agents
6. dispatch_wave() -> next round with peer context injected
```

This means the current `_dispatch_round()` approach changes significantly. Currently `_dispatch_round()` reads peers, formats context, and dispatches the wave as one unit. With D-12, the steps split:
- Post writes happen AFTER `write_decisions()` in `run_simulation()` (not inside `_dispatch_round()`)
- Ranked post reads + context formatting happen BEFORE `dispatch_wave()` (still logically part of dispatching)
- READ_POST edge writes happen AFTER context formatting but BEFORE dispatch

**Recommended approach:** Move post creation and READ_POST writes into `run_simulation()` flow (alongside existing write_decisions and WriteBuffer calls). Either refactor `_dispatch_round()` to accept pre-built peer contexts, OR extract the dispatch-only portion. The cleanest approach: `_dispatch_round()` already accepts `peer_contexts` via its output from an internal build step -- we can build peer_contexts externally in `run_simulation()` and pass them to `dispatch_wave()` directly, bypassing `_dispatch_round()` for Rounds 2-3.

### INFLUENCED_BY Edge Structure (graph.py:724-738)
```
(src:Agent)-[:INFLUENCED_BY {
    weight: float,
    cycle_id: str,
    round: int
}]->(tgt:Agent)
```
- Direction: source (citing agent) -> target (cited agent)
- `weight` = citation_count / total_agents (normalized)
- Each round writes its own edges (CREATE, not MERGE)
- Multiple edges between same pair across rounds are expected
- Queries MUST filter by round to avoid double-counting

**For read_ranked_posts() Cypher:** The reading agent is the `source` in INFLUENCED_BY. We need edges where the reading agent INFLUENCED_BY the post author, meaning:
```cypher
OPTIONAL MATCH (reader:Agent {id: $agent_id})-[inf:INFLUENCED_BY {cycle_id: $cycle_id, round: $source_round}]->(author:Agent {id: p.agent_id})
```
Wait -- reviewing the edge direction more carefully. In `compute_influence_edges()`, the `source_id` is the citing agent and `target_id` is the cited agent. The Cypher is:
```cypher
CREATE (src)-[:INFLUENCED_BY {weight, cycle_id, round}]->(tgt)
```
So `(citer)-[:INFLUENCED_BY]->(cited)`. The weight on this edge represents how influential the target is (how many agents cite them / total).

For `read_ranked_posts()`: we want posts ranked by how influential their author is to the reading agent. The INFLUENCED_BY edge goes FROM the reader TO the author if the reader cited the author previously. The weight represents the author's influence.

```cypher
MATCH (p:Post)
WHERE p.cycle_id = $cycle_id AND p.round_num = $source_round AND p.agent_id <> $agent_id
OPTIONAL MATCH (reader:Agent {id: $agent_id})-[inf:INFLUENCED_BY]->(author:Agent {id: p.agent_id})
WHERE inf.cycle_id = $cycle_id AND inf.round = $source_round
WITH p, inf, author
OPTIONAL MATCH (author2:Agent {id: p.agent_id})
ORDER BY coalesce(inf.weight, author2.influence_weight_base, 0.0) DESC
LIMIT $limit
RETURN p.content AS content, p.agent_id AS agent_id, p.signal AS signal,
       p.confidence AS confidence, p.round_num AS round_num,
       coalesce(inf.weight, author2.influence_weight_base, 0.0) AS influence_weight,
       author2.bracket AS bracket,
       elementId(p) AS post_id
```

**Important nuance:** The INFLUENCED_BY edges represent pair-wise citation patterns, not global influence. An agent who was cited by agent A has an INFLUENCED_BY edge from A, but agent B (who didn't cite them) has no such edge. So the OPTIONAL MATCH correctly falls back to `influence_weight_base` for agents with no citation relationship to the reader.

### Post Node Cypher for write_posts()
```cypher
UNWIND $posts AS p
MATCH (d:Decision {decision_id: p.decision_id})
MATCH (a:Agent {id: p.agent_id})
CREATE (post:Post {
    content: p.content,
    agent_id: p.agent_id,
    signal: p.signal,
    confidence: p.confidence,
    round_num: $round_num,
    cycle_id: $cycle_id,
    created_at: datetime()
})
CREATE (a)-[:AUTHORED]->(post)
CREATE (d)-[:HAS_POST]->(post)
```

**Note on Post identity:** Post nodes don't need a separate `post_id` UUID property if we use Neo4j's `elementId()` for READ_POST targeting. However, using `elementId()` is fragile across database restores. A generated `post_id` UUID is safer and follows the `decision_id` pattern. Recommendation: add a `post_id: str` property, generated client-side like `decision_id`.

### READ_POST Batch Write Sizing
Per D-09: ALL agents get READ_POST edges to ALL posts from the prior round. With 100 agents and ~100 posts per round, that's 100 * 100 = 10,000 edges per round. This is a single UNWIND of 10,000 pairs -- well within Neo4j's capabilities for a single transaction.

### Budget Enforcement Algorithm
```python
def _format_peer_context(
    posts: list[RankedPost],
    source_round: int,
    budget: int = 4000,
    max_posts: int = 10,
) -> str:
    if not posts:
        return ""

    header = f"Peer Decisions (Round {source_round}):"
    guard = ("\nThe above are peer observations for context only. "
             "Make your own independent assessment.")
    overhead = len(header) + len(guard) + 2  # newlines
    remaining = budget - overhead

    lines = [header]
    for i, post in enumerate(posts[:max_posts], 1):
        if remaining <= 0:
            break
        prefix = f'{i}. [{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
        suffix = '"'
        available = remaining - len(prefix) - len(suffix) - 1  # -1 for newline
        if available <= 0:
            break
        content = post.content
        if len(content) > available:
            # Truncate at word boundary
            content = content[:available].rsplit(' ', 1)[0]
            if not content:
                content = post.content[:available]  # No word boundary found
        line = f'{prefix}{content}{suffix}'
        lines.append(line)
        remaining -= len(line) + 1  # +1 for newline

    lines.append(guard)
    return "\n".join(lines)
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Neo4j batch writes | Custom per-node transactions | UNWIND pattern (existing) | 100x fewer transactions, existing tested pattern |
| Influence ranking | Custom in-memory sort of all agents | Cypher ORDER BY with coalesce | Neo4j handles join + sort efficiently |
| Post ID generation | Auto-increment or elementId() | Client-side UUID4 (`str(uuid.uuid4())`) | Portable, matches decision_id pattern |
| Word boundary truncation | Regex-based word detection | `str.rsplit(' ', 1)[0]` | Simple, handles edge cases, standard Python |

## Common Pitfalls

### Pitfall 1: READ_POST Edge Explosion
**What goes wrong:** 100 agents x 100 posts = 10,000 READ_POST edges per round. Attempting individual CREATE statements causes 10,000 transactions.
**Why it happens:** Not using UNWIND for edge creation.
**How to avoid:** Single UNWIND batch with 10,000 (agent_id, post_id) pairs. Same pattern as write_decisions().
**Warning signs:** >1 second for READ_POST write, or Neo4j connection pool exhaustion.

### Pitfall 2: INFLUENCED_BY Round Filter Missing
**What goes wrong:** `read_ranked_posts()` Cypher matches INFLUENCED_BY edges from wrong round, causing stale or inflated weights.
**Why it happens:** INFLUENCED_BY edges have `round` property -- multiple edges exist between the same agent pair across rounds. Without `WHERE inf.round = $source_round`, you get cumulative weights.
**How to avoid:** Always filter INFLUENCED_BY by both `cycle_id` AND `round` in the OPTIONAL MATCH.
**Warning signs:** Unusually high influence weights, or agents with no citations showing non-zero dynamic weights.

### Pitfall 3: Budget Accounting Off-by-One
**What goes wrong:** Peer context block exceeds 4000 chars due to not accounting for newlines, header, and prompt guard overhead.
**Why it happens:** Budget calculation only counts post content, not structural text.
**How to avoid:** Pre-compute overhead (header + guard + newlines) and subtract from budget before iterating posts.
**Warning signs:** Context blocks >4100 chars in tests.

### Pitfall 4: Empty Post Content Injection
**What goes wrong:** PARSE_ERROR agents produce rationale like "Inference failed for quants_01: ConnectionError" which gets stored as Post content and injected into peer context.
**Why it happens:** `write_posts()` creates Post for every Decision, including PARSE_ERROR ones.
**How to avoid:** Filter PARSE_ERROR decisions before creating Post nodes. In `write_posts()`: skip entries where signal == "parse_error". In `read_ranked_posts()` Cypher: `WHERE p.signal <> 'parse_error'`.
**Warning signs:** Peer context containing error messages instead of analysis.

### Pitfall 5: _dispatch_round Refactor Breaking Existing Tests
**What goes wrong:** 20+ existing tests for `_dispatch_round()` and `run_simulation()` break because the function signature or internal logic changes.
**Why it happens:** Phase 12 replaces the dynamic/static peer selection paths in `_dispatch_round()`.
**How to avoid:** Keep `_dispatch_round()` working with minimal changes. The cleanest approach: add a `ranked_posts` parameter to `_dispatch_round()` that bypasses the internal peer reads when provided. Or build peer_contexts in `run_simulation()` directly and pass to `dispatch_wave()` without going through `_dispatch_round()` at all.
**Warning signs:** >10 test failures after refactoring.

### Pitfall 6: Post Node Without AUTHORED/HAS_POST Relationships
**What goes wrong:** Post nodes are created but not linked to Agent or Decision nodes, making them orphaned in the graph.
**Why it happens:** Forgetting to add relationship creation in the UNWIND Cypher.
**How to avoid:** write_posts() Cypher must CREATE both `(a)-[:AUTHORED]->(post)` and `(d)-[:HAS_POST]->(post)` in the same transaction.
**Warning signs:** `MATCH (a:Agent)-[:AUTHORED]->(p:Post)` returns 0 results.

## Integration Sequence (Detailed)

### Round 1 Flow (modified)
```
1. run_round1() -> Round1Result (unchanged)
2. write_posts(round1_decisions, cycle_id, round_num=1)   <-- NEW
3. WriteBuffer push + flush (RationaleEpisode writes)     <-- existing
4. compute_influence_edges(cycle_id, up_to_round=1)       <-- existing
```

### Round 2 Flow (modified)
```
1. read_ranked_posts(agent_id, cycle_id, source_round=1, limit=10) per agent  <-- NEW (replaces read_peer_decisions)
2. _format_peer_context(ranked_posts, source_round=1)     <-- UPDATED (new signature + budget)
3. write_read_post_edges(agents, posts, round_num=2, cycle_id)  <-- NEW
4. dispatch_wave(peer_contexts=...)                        <-- existing
5. write_decisions(round2_decisions, cycle_id, round_num=2)  <-- existing
6. write_posts(round2_decisions, cycle_id, round_num=2)   <-- NEW
7. WriteBuffer push + flush                               <-- existing
8. compute_influence_edges(cycle_id, up_to_round=2)       <-- existing
```

### Round 3 Flow (same pattern as Round 2 but with Round 2 data)
```
1. read_ranked_posts(agent_id, cycle_id, source_round=2, limit=10) per agent
2. _format_peer_context(ranked_posts, source_round=2)
3. write_read_post_edges(agents, posts, round_num=3, cycle_id)
4. dispatch_wave(peer_contexts=...)
5. write_decisions(round3_decisions, cycle_id, round_num=3)
6. write_posts(round3_decisions, cycle_id, round_num=3)
7. WriteBuffer push + flush
```

## Code Examples

### write_posts() Method Skeleton
```python
async def write_posts(
    self,
    agent_decisions: list[tuple[str, AgentDecision]],
    cycle_id: str,
    round_num: int,
) -> list[str]:
    """Batch-write Post nodes from Decision rationale (D-01, D-02, D-03).

    Filters out PARSE_ERROR decisions. One Post per valid Decision.
    Returns list of post_id strings for downstream READ_POST edges.
    """
    posts = []
    post_ids = []
    for agent_id, decision in agent_decisions:
        if decision.signal == SignalType.PARSE_ERROR:
            continue
        pid = str(uuid.uuid4())
        post_ids.append(pid)
        posts.append({
            "post_id": pid,
            "agent_id": agent_id,
            "content": decision.rationale,
            "signal": decision.signal.value,
            "confidence": decision.confidence,
            "round_num": round_num,
            "cycle_id": cycle_id,
        })
    if not posts:
        return []
    # ... session.execute_write with UNWIND
    return post_ids
```

### read_ranked_posts() Cypher
```cypher
MATCH (p:Post)
WHERE p.cycle_id = $cycle_id AND p.round_num = $source_round
  AND p.agent_id <> $agent_id
  AND p.signal <> 'parse_error'
WITH p
MATCH (author:Agent {id: p.agent_id})
OPTIONAL MATCH (reader:Agent {id: $agent_id})-[inf:INFLUENCED_BY {cycle_id: $cycle_id, round: $source_round}]->(author)
RETURN p.post_id AS post_id,
       p.agent_id AS agent_id,
       author.bracket AS bracket,
       p.signal AS signal,
       p.confidence AS confidence,
       p.content AS content,
       p.round_num AS round_num,
       coalesce(inf.weight, author.influence_weight_base) AS influence_weight
ORDER BY influence_weight DESC
LIMIT $limit
```

### write_read_post_edges() Batch Pattern
```python
async def write_read_post_edges(
    self,
    agent_ids: list[str],
    post_ids: list[str],
    round_num: int,
    cycle_id: str,
) -> None:
    """Batch-write READ_POST edges: every agent -> all posts (D-09, D-10, D-11)."""
    if not agent_ids or not post_ids:
        return
    pairs = [
        {"agent_id": aid, "post_id": pid}
        for aid in agent_ids
        for pid in post_ids
    ]
    # ... session.execute_write with UNWIND
```

**Cypher:**
```cypher
UNWIND $pairs AS pair
MATCH (a:Agent {id: pair.agent_id})
MATCH (p:Post {post_id: pair.post_id})
CREATE (a)-[:READ_POST {round_num: $round_num, cycle_id: $cycle_id}]->(p)
```

## State of the Art

| Old Approach (Phase 7) | New Approach (Phase 12) | Impact |
|------------------------|------------------------|--------|
| `sanitize_rationale(max_len=80)` per peer | Full rationale with 4000-char budget | Richer context for agent reasoning |
| `read_peer_decisions()` static ranking | `read_ranked_posts()` INFLUENCED_BY ranking | Dynamic influence topology drives content |
| 5 peers max (`limit=5`) | 10 posts max (`K=10`) with budget | More diverse peer exposure |
| In-memory PeerDecision construction (dynamic path) | Neo4j Post node query (unified path) | Single code path, no dynamic/static branching |
| No record of what agents read | READ_POST edges | Observable social graph |

**Deprecated by this phase:**
- `read_peer_decisions()` -- replaced by `read_ranked_posts()` for Rounds 2-3. May be kept for backward compatibility but no longer called in production simulation flow.
- `select_diverse_peers()` -- bracket diversity was applied in the in-memory dynamic path. The new `read_ranked_posts()` uses pure influence weight ranking. If bracket diversity is still desired, it must be applied post-query in Python (but CONTEXT.md does not mention bracket diversity for posts, only weight ranking).

## Open Questions

1. **Bracket diversity in post ranking**
   - What we know: Phase 8 D-06 introduced bracket-diverse peer selection via `select_diverse_peers()`. Phase 12 D-07/D-08 specifies pure influence weight ranking for posts.
   - What's unclear: Should `read_ranked_posts()` also ensure bracket diversity, or is pure weight ranking the intended design?
   - Recommendation: Follow D-07/D-08 as written (pure weight ranking). Bracket diversity was a peer selection concern; post ranking is influence-driven. The K=10 limit (vs old limit=5) naturally provides more diversity.

2. **Post node identity for READ_POST edges**
   - What we know: READ_POST edges connect Agent to Post. Posts need a stable identifier for the MATCH clause.
   - What's unclear: Whether to use a client-side `post_id` UUID or Neo4j's internal `elementId()`.
   - Recommendation: Use client-side `post_id` (UUID4 string), following the `decision_id` pattern. Add a `post_id` property to Post nodes and index it.

3. **Refactoring _dispatch_round() vs. building peer context externally**
   - What we know: D-12 ordering requires Post writes and READ_POST writes to happen between write_decisions and dispatch_wave in run_simulation(). Currently _dispatch_round() encapsulates peer reads + format + dispatch.
   - What's unclear: Whether to refactor _dispatch_round() to accept pre-built peer contexts, or build peer contexts directly in run_simulation().
   - Recommendation: Build peer contexts directly in `run_simulation()` for Rounds 2-3 (bypass `_dispatch_round()` for these rounds, call `dispatch_wave()` directly with pre-built peer_contexts). This avoids modifying `_dispatch_round()` signature and breaking its existing tests. `_dispatch_round()` can be retained but only used when Post-based ranking is not active (e.g., a future fallback mode).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] asyncio_mode = "auto" |
| Quick run command | `uv run pytest tests/test_graph.py tests/test_simulation.py -x -q` |
| Full suite command | `uv run pytest tests/ -x --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SOCIAL-01a | write_posts() creates Post nodes from Decision rationale via UNWIND | unit | `uv run pytest tests/test_graph.py -x -k "write_posts"` | No -- Wave 0 |
| SOCIAL-01b | write_posts() skips PARSE_ERROR decisions | unit | `uv run pytest tests/test_graph.py -x -k "write_posts_skip_parse_error"` | No -- Wave 0 |
| SOCIAL-01c | Post schema index added to SCHEMA_STATEMENTS | unit | `uv run pytest tests/test_graph.py -x -k "schema_statements_includes_post_index"` | No -- Wave 0 |
| SOCIAL-01d | write_posts() integration (real Neo4j) | integration | `uv run pytest tests/test_graph_integration.py -x -k "write_posts"` | No -- Wave 0 |
| SOCIAL-02a | read_ranked_posts() returns RankedPost list ordered by influence weight | unit | `uv run pytest tests/test_graph.py -x -k "read_ranked_posts"` | No -- Wave 0 |
| SOCIAL-02b | read_ranked_posts() falls back to influence_weight_base | unit | `uv run pytest tests/test_graph.py -x -k "ranked_posts_fallback"` | No -- Wave 0 |
| SOCIAL-02c | _format_peer_context() enforces 4000-char budget | unit | `uv run pytest tests/test_simulation.py -x -k "format_peer_context_budget"` | No -- Wave 0 |
| SOCIAL-02d | _format_peer_context() truncates at word boundary | unit | `uv run pytest tests/test_simulation.py -x -k "format_peer_context_word_boundary"` | No -- Wave 0 |
| SOCIAL-02e | _format_peer_context() preserves prompt guard | unit | `uv run pytest tests/test_simulation.py -x -k "format_peer_context_prompt_guard"` | Exists (update) |
| SOCIAL-02f | write_read_post_edges() creates READ_POST for all agent-post pairs | unit | `uv run pytest tests/test_graph.py -x -k "write_read_post_edges"` | No -- Wave 0 |
| SOCIAL-02g | run_simulation() integration: posts written after decisions, ranked posts read, READ_POST edges created | unit (mocked) | `uv run pytest tests/test_simulation.py -x -k "run_simulation_writes_posts"` | No -- Wave 0 |
| SOCIAL-02h | End-to-end 3-round with Post nodes (real Neo4j) | integration | `uv run pytest tests/test_graph_integration.py -x -k "posts_and_read_post"` | No -- Wave 0 |

### Existing Tests That Must Not Break
- `test_format_peer_context_structure` -- signature changes, test must be updated
- `test_format_peer_context_truncates_rationale` -- truncation logic changes (80-char -> budget), test must be updated
- `test_format_peer_context_empty_peers` -- behavior unchanged (empty -> ""), test should pass
- `test_format_peer_context_prompt_guard` -- behavior unchanged, but input type changes
- `test_dispatch_round_*` -- if `_dispatch_round()` is refactored, these tests need updates
- `test_run_simulation_*` -- mock graph_manager needs new method mocks (write_posts, read_ranked_posts, write_read_post_edges)
- All other existing tests should pass unchanged

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_graph.py tests/test_simulation.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_graph.py` -- add tests for write_posts, read_ranked_posts, write_read_post_edges
- [ ] `tests/test_simulation.py` -- add tests for updated _format_peer_context with budget, update existing _format_peer_context tests
- [ ] `tests/test_simulation.py` -- add tests for run_simulation post/READ_POST integration
- [ ] `tests/test_graph_integration.py` -- add Post + READ_POST integration tests
- [ ] `tests/conftest.py` -- add Post node cleanup to graph_manager fixture teardown
- [ ] No new framework install needed -- existing pytest + pytest-asyncio infrastructure is sufficient

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/graph.py` -- Full source read. UNWIND patterns, SCHEMA_STATEMENTS, PeerDecision, INFLUENCED_BY edge structure, compute_influence_edges().
- `src/alphaswarm/simulation.py` -- Full source read. _format_peer_context(), _dispatch_round(), run_simulation(), select_diverse_peers(), RoundDispatchResult.
- `src/alphaswarm/types.py` -- Full source read. AgentDecision (frozen Pydantic, rationale field), SignalType, PeerDecision location.
- `src/alphaswarm/worker.py` -- Full source read. infer() peer_context injection as system message.
- `src/alphaswarm/batch_dispatcher.py` -- Full source read. dispatch_wave() peer_contexts parameter handling.
- `src/alphaswarm/write_buffer.py` -- Full source read. EpisodeRecord pattern, flush() ordering constraint.
- `tests/test_graph.py`, `tests/test_simulation.py`, `tests/conftest.py` -- Test patterns and fixtures.

### Secondary (MEDIUM confidence)
- `.planning/phases/12-richer-agent-interactions/12-CONTEXT.md` -- All 13 locked decisions, discretion areas, canonical refs.
- `.planning/REQUIREMENTS.md` -- SOCIAL-01, SOCIAL-02 requirement text.
- `.planning/STATE.md` -- Project decisions and velocity metrics.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All libraries already in use (neo4j async driver, pydantic, structlog, pytest-asyncio). No new dependencies.
- Architecture: HIGH -- All patterns directly observable in existing codebase. UNWIND batch writes, frozen dataclasses, session-per-method, persona-aligned lists.
- Pitfalls: HIGH -- Identified from direct code analysis of existing integration points and Neo4j query patterns.
- Integration sequence: HIGH -- Line-by-line analysis of run_simulation() with clear insertion points.

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable -- no external dependency changes)
