# Phase 4: Neo4j Graph State - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-25
**Phase:** 04-neo4j-graph-state
**Areas discussed:** Graph schema design, Docker & bootstrap, GraphStateManager API, Data lifecycle

---

## Graph Schema Design

### How should agent decisions be modeled in Neo4j?

| Option | Description | Selected |
|--------|-------------|----------|
| Decision as relationship (Recommended) | Agent nodes persistent. Each round's decision is a DECIDED relationship from Agent to Cycle node. Compact graph, fast traversal. | |
| Decision as node | Each decision is its own node linked to both Agent and Cycle. More flexible for querying individual decisions, larger graph. | ✓ |
| Hybrid | Rounds 1-2 as relationship properties, Round 3 as full nodes. | |

**User's choice:** Decision as node
**Notes:** Chose flexibility for querying individual decisions across rounds.

### Should INFLUENCED_BY connect Decision-to-Decision or Agent-to-Agent?

| Option | Description | Selected |
|--------|-------------|----------|
| Agent-to-Agent (Recommended) | INFLUENCED_BY edge between Agent nodes with cycle_id + round properties. Simpler graph. | |
| Decision-to-Decision | INFLUENCED_BY connects specific Decision nodes. Most precise — shows exactly which decision influenced which. | ✓ |

**User's choice:** Decision-to-Decision
**Notes:** Chose granular traceability over simplicity.

### Should cited_agents be stored as a list property on Decision, or as separate CITED relationships?

| Option | Description | Selected |
|--------|-------------|----------|
| List property (Recommended) | cited_agents stays as string list on Decision node. INFLUENCED_BY edges are the graph-native version. | |
| CITED relationship | Replace list with explicit CITED edges from Decision to Agent. More graph-native, queryable via Cypher traversal. | ✓ |

**User's choice:** CITED relationship
**Notes:** Both CITED (raw LLM output) and INFLUENCED_BY (Phase 8 computed topology) coexist as distinct edge types.

---

## Docker & Bootstrap

### How should Neo4j be provisioned for local development?

| Option | Description | Selected |
|--------|-------------|----------|
| docker-compose.yml (Recommended) | docker-compose.yml at project root with Neo4j Community Edition, volumes, health checks. | ✓ |
| Script-based | Shell script running `docker run` with flags. | |
| Assume external | No Docker config; user runs Neo4j however they want. | |

**User's choice:** docker-compose.yml
**Notes:** None

### How should the graph schema be applied?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-apply on startup (Recommended) | GraphStateManager.ensure_schema() with idempotent CREATE ... IF NOT EXISTS. | ✓ |
| Init script | Separate .cypher file mounted into container or run manually. | |
| Both | Cypher file for docs/CI, auto-apply on startup for convenience. | |

**User's choice:** Auto-apply on startup
**Notes:** None

### Should Agent nodes be seeded during schema setup or lazily on first simulation?

| Option | Description | Selected |
|--------|-------------|----------|
| Eager seed on startup (Recommended) | ensure_schema() also creates all 100 Agent nodes via MERGE. | ✓ |
| Lazy on first write | Agent nodes created as part of first batch decision write. | |

**User's choice:** Eager seed on startup
**Notes:** None

---

## GraphStateManager API

### How should GraphStateManager manage Neo4j driver sessions?

| Option | Description | Selected |
|--------|-------------|----------|
| Session-per-method (Recommended) | Each public method opens its own short-lived session. Caller never sees a session. | ✓ |
| Session factory | Exposes session_scope() context manager for callers to manage. | |
| Both | High-level convenience methods + low-level session_scope() escape hatch. | |

**User's choice:** Session-per-method
**Notes:** Aligns with session-per-coroutine requirement.

### What public methods should GraphStateManager expose?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal core (Recommended) | Only methods Phase 4 can fully test: ensure_schema, seed_agents, create_cycle, write_decisions, read_peer_decisions, close. | ✓ |
| Full surface upfront | All methods including influence topology as stubs. | |

**User's choice:** Minimal core
**Notes:** Influence topology methods added in Phase 8 when needed.

### How should read_peer_decisions rank peers before Phase 8?

| Option | Description | Selected |
|--------|-------------|----------|
| Bracket influence_weight_base (Recommended) | Use static influence_weight_base from config. Whales/Quants rank higher by default. | ✓ |
| Random sampling | Randomly select 5 peers. No bias. | |
| Bracket-diverse sampling | Top-1 from each of 5 different brackets. | |

**User's choice:** Bracket influence_weight_base
**Notes:** Phase 8 replaces with dynamic citation-based weights.

---

## Data Lifecycle

### How should cycle_id be generated?

| Option | Description | Selected |
|--------|-------------|----------|
| UUID4 (Recommended) | Standard uuid4() string. Globally unique. | ✓ |
| Timestamp-based | ISO timestamp. Human-readable, sortable. Collision risk. | |
| Sequential integer | Auto-incrementing. Simplest but needs coordination. | |

**User's choice:** UUID4
**Notes:** None

### What happens to old simulation cycles?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep all, no pruning (Recommended) | All cycles persist indefinitely. Composite indexes keep queries fast. | ✓ |
| Auto-prune old cycles | Keep last N cycles. | |
| Soft delete | Mark old cycles as archived. | |

**User's choice:** Keep all, no pruning
**Notes:** Manual cleanup via Cypher if needed.

### Should Agent nodes be shared across cycles or duplicated?

| Option | Description | Selected |
|--------|-------------|----------|
| Shared across cycles (Recommended) | 100 Agent nodes exist once. Decisions scoped by cycle_id. | ✓ |
| Duplicated per cycle | Each cycle creates own 100 Agent nodes. Full isolation. | |

**User's choice:** Shared across cycles
**Notes:** None

---

## Claude's Discretion

- Neo4j async driver connection pool configuration
- Exact composite index definitions beyond required ones
- PeerDecision return type design
- Internal transaction function signatures
- Test fixture design for Neo4j integration tests
- Error types for Neo4j failures

## Deferred Ideas

None — discussion stayed within phase scope
