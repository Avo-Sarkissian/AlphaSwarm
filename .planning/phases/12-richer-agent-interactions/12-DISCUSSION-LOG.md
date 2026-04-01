# Phase 12: Richer Agent Interactions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-01
**Phase:** 12-richer-agent-interactions
**Areas discussed:** Post content identity, Token budget, Post ranking, READ_POST semantics, Prompt layout, Peer source

---

## Post Content Identity

| Option | Description | Selected |
|--------|-------------|----------|
| Same as rationale | public_rationale = existing rationale field, zero schema changes | ✓ |
| Separate LLM output field | New field in AgentDecision JSON, LLM outputs both internal rationale and public post | |
| Condensed rationale | First N chars of rationale, trimmed to sentence boundary | |

**User's choice:** Same as rationale
**Notes:** Keeps things simple — the rationale is already being generated, Post nodes just reuse it.

---

## Post Node Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Text + signal/confidence | Post stores content, agent_id, signal, confidence, round_num, cycle_id | ✓ |
| Text only | Post stores content, agent_id, round_num, cycle_id — join to Decision for signal | |

**User's choice:** Text + signal/confidence
**Notes:** Keeps prompts self-contained — peer context block reads from Post nodes without extra joins.

---

## Token Budget Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Character budget | Total char cap across all injected posts, no dependencies | ✓ |
| Approximate token count (chars/4) | Same simplicity but expressed in token units | |
| Per-post truncation only | Keep Phase 7's 80-char per-post snippet | |

**User's choice:** Character budget

---

## Budget Cap & K

| Option | Description | Selected |
|--------|-------------|----------|
| 2000 chars, K=5 | Consistent with current top-5 peers | |
| 1500 chars, K=3 | Tighter budget | |
| 4000 chars, K=10 | Richer peer context, 10 posts | ✓ |

**User's choice:** 4000 chars, K=10
**Notes:** User wants richer peer context — gives agents more to react to.

---

## Post Ranking Source

| Option | Description | Selected |
|--------|-------------|----------|
| INFLUENCED_BY edge weights | Dynamic weights from Phase 8, fallback to influence_weight_base | ✓ |
| Static influence_weight_base only | Always use static property | |
| Recency + influence combined | Score = influence_weight × recency_factor | |

**User's choice:** INFLUENCED_BY edge weights (with static fallback)

---

## READ_POST Edge Semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Top-K injected posts only | Precise — only posts actually in agent's context window | |
| All available posts from prior round | Every agent READ_POST to every prior-round post | ✓ |
| No READ_POST edges | Skip entirely | |

**User's choice:** All available posts from prior round
**Notes:** "Agent had access to this post" semantics — simpler batch write.

---

## Peer Context Source (Decision vs Post)

| Option | Description | Selected |
|--------|-------------|----------|
| Replace: Posts become the peer source | Clean cutover | |
| Augment: Posts added alongside existing decisions | Both signal format AND post rationale | ✓ |
| Keep decisions, add post summary | Posts in Neo4j but don't change prompts | |

**User's choice:** Augment — both decisions + posts in a unified block

---

## Prompt Layout

| Option | Description | Selected |
|--------|-------------|----------|
| One unified block | Single "Peer Decisions" section, signal + full post text per entry | ✓ |
| Two separate sections | Decision signals section, then separate "Peer Posts" section | |

**User's choice:** One unified block (format preview confirmed)
