# Phase 4: Neo4j Graph State - Research

**Researched:** 2026-03-25
**Domain:** Neo4j graph database integration (async Python driver, Docker, Cypher schema, batch writes)
**Confidence:** HIGH

## Summary

Phase 4 delivers the persistence layer for agent decisions and influence relationships. The core components are: (1) a Neo4j 5.26 LTS Community Edition Docker container with health-checked startup, (2) an idempotent graph schema with composite indexes applied via `ensure_schema()`, (3) a `GraphStateManager` class that wraps the `neo4j` async Python driver with session-per-method isolation and UNWIND batch writes, and (4) agent node seeding from the existing `AgentPersona` config.

The Neo4j Python driver 5.28.x provides a mature async API (`AsyncGraphDatabase`, `AsyncSession`, `execute_read`/`execute_write`) that maps directly to the project's 100% async constraint. The UNWIND batch pattern eliminates the 100-individual-transactions anti-pattern. Composite range indexes on `(Decision.cycle_id, Decision.round)` and a uniqueness constraint on `Agent.id` enable sub-5ms peer decision reads. The session-per-method pattern (each public method opens and closes its own `AsyncSession`) naturally prevents the corrupted-reads problem under concurrent coroutines, since Neo4j sessions are explicitly documented as not safe for sharing across tasks.

**Primary recommendation:** Use `neo4j==5.28.3` Python driver with `neo4j:5.26-community` Docker image. Use managed async transactions (`execute_write`/`execute_read`) with UNWIND for all batch operations. Each `GraphStateManager` method opens a fresh `AsyncSession` internally -- callers never see or manage sessions.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Decision modeled as a node, not a relationship. Agent-[:MADE]->Decision-[:FOR]->Cycle. Each Decision node holds: cycle_id, round, signal, confidence, sentiment, rationale. 300 Decision nodes per cycle (100 agents x 3 rounds).
- **D-02:** INFLUENCED_BY connects Decision-to-Decision (not Agent-to-Agent). Provides granular traceability of exactly which decision influenced which. Weight property on the edge. Implemented in Phase 8 -- schema/index created in Phase 4.
- **D-03:** cited_agents stored as explicit CITED relationships (Decision-[:CITED]->Agent), not as a list property. Enables graph-native citation queries. Separate from INFLUENCED_BY -- CITED is raw LLM output, INFLUENCED_BY is computed topology (Phase 8).
- **D-04:** docker-compose.yml at project root with Neo4j 5 Community Edition. Ports: 7687 (Bolt), 7474 (Browser). Auth: neo4j/alphaswarm (matching existing Neo4jSettings defaults). Volume mount for data persistence. Health check via cypher-shell.
- **D-05:** Schema auto-applied on startup via `GraphStateManager.ensure_schema()` -- idempotent `CREATE ... IF NOT EXISTS` for all constraints and indexes. Zero manual steps after `docker compose up -d`.
- **D-06:** All 100 Agent nodes eagerly seeded during `ensure_schema()` via UNWIND + MERGE from persona config. Agents are always present before any simulation runs.
- **D-07:** Session-per-method pattern -- each public method opens its own short-lived `async with self._driver.session()` internally. Callers never see or manage sessions. Aligns with session-per-coroutine requirement (INFRA-06).
- **D-08:** Minimal core API surface for Phase 4:
  - `ensure_schema()` -- constraints, indexes, agent node seeding
  - `seed_agents(agents: list[AgentPersona])` -- MERGE agent nodes from config
  - `create_cycle(seed_rumor: str) -> str` -- creates Cycle node, returns uuid4 cycle_id
  - `write_decisions(agent_decisions: list[tuple[str, AgentDecision]], cycle_id: str, round_num: int)` -- UNWIND batch write of Decision nodes + MADE/FOR/CITED relationships
  - `read_peer_decisions(agent_id: str, cycle_id: str, round_num: int, limit: int = 5) -> list[PeerDecision]` -- top-N peer decisions for a given round
  - `close()` -- driver cleanup
  - Influence topology methods (write_influence_edges, read_bracket_aggregation, etc.) deferred to Phase 8.
- **D-09:** Pre-Phase 8 peer ranking uses static `influence_weight_base` from Agent node properties (set from AgentPersona config). `ORDER BY a.influence_weight_base DESC LIMIT 5`. Phase 8 replaces with dynamic citation-based INFLUENCED_BY edge weights.
- **D-10:** cycle_id generated via `uuid.uuid4()` -- globally unique, no collision risk.
- **D-11:** Keep all cycles indefinitely, no pruning. Composite indexes on cycle_id keep queries fast regardless of history size. Manual cleanup via Cypher if needed.
- **D-12:** Agent nodes shared across cycles -- 100 persistent Agent nodes. Decisions, MADE, FOR, CITED relationships are scoped by cycle_id. Different simulations share the same agent graph.

### Claude's Discretion
- Neo4j async driver connection pool configuration (max_connection_pool_size, connection_acquisition_timeout)
- Exact composite index definitions beyond the required (Agent.id) and (Decision.cycle_id, Decision.round)
- PeerDecision return type design (dataclass vs TypedDict vs Pydantic)
- Internal transaction function signatures (_batch_write_tx, etc.)
- Test fixture design for Neo4j integration tests (testcontainers vs real Docker instance)
- Error types for Neo4j failures (connection errors, constraint violations)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-05 | Neo4j graph schema with cycle-scoped composite indexes on (Agent.id, INFLUENCED_BY.cycle_id) for sub-5ms peer decision reads | Composite range indexes verified via Neo4j Cypher Manual; `CREATE INDEX IF NOT EXISTS` syntax confirmed; D-01/D-02/D-03 define the exact schema |
| INFRA-06 | GraphStateManager with session-per-coroutine pattern and UNWIND batch writes (100 decisions per transaction, not 100 transactions) | Neo4j async driver `execute_write` + UNWIND pattern verified; session-per-method confirmed as the correct async pattern per official concurrency docs |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **100% async (asyncio):** All Neo4j operations must use `AsyncGraphDatabase`, `AsyncSession`, async `execute_read`/`execute_write`. No blocking I/O.
- **Python 3.11+, strict typing:** All new code fully typed with mypy strict mode.
- **Package manager: uv:** Dependencies added via `uv add`, not pip install.
- **Testing: pytest-asyncio:** Integration tests use `asyncio_mode = "auto"` per existing `pyproject.toml`.
- **Validation: pydantic:** Return types should use frozen Pydantic models or frozen dataclasses per existing patterns.
- **Logging: structlog:** `structlog.get_logger(component="graph")` for GraphStateManager logging.
- **Config: pydantic-settings:** `Neo4jSettings` already exists in `config.py` with correct defaults.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `neo4j` | 5.28.3 | Async Python driver for Neo4j Bolt protocol | Official Neo4j driver; `AsyncGraphDatabase` provides native asyncio support; 5.28.x is latest 5.x line, stable with 5.26 LTS server |
| `neo4j` Docker image | 5.26-community | Neo4j 5.26 LTS Community Edition server | LTS supported until June 2028; native ARM64 support for M1 Max; Community Edition sufficient (no enterprise features needed) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `neo4j-rust-ext` | 5.28.3.0 | Optional Rust extension for 3-10x driver speedup | Add if profiling shows driver serialization as bottleneck; has ARM64 macOS wheels; drop-in replacement (no code changes) |
| `testcontainers[neo4j]` | 4.14.2 | Ephemeral Neo4j containers for integration tests | Use for CI or isolated test runs; alternative: direct Docker instance with `@pytest.mark.skipif` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `neo4j` 5.28.3 | `neo4j` 6.1.0 | 6.x drops Python 3.9, changes exception hierarchy (ConnectionAcquisitionTimeoutError, TransactionError). Works with Neo4j 5.26 server. Could upgrade later if needed, but 5.28.x is more conservative and avoids breaking-change risk. |
| `neo4j` driver | `neomodel` OGM | OGM adds abstraction overhead; we need raw Cypher control for UNWIND batches and composite indexes. Not appropriate for performance-critical path. |
| testcontainers | Real Docker instance | Simpler setup, faster test startup, but requires Docker running. Recommend real Docker for local dev, testcontainers optional for CI isolation. |

**Installation:**
```bash
# Core dependency
uv add "neo4j>=5.28,<6.0"

# Dev dependency (optional, for CI integration tests)
uv add --group dev "testcontainers[neo4j]>=4.14"
```

**Version verification:** `neo4j` 5.28.3 confirmed via PyPI (latest 5.x as of 2026-03-25). Docker image `neo4j:5.26-community` confirmed as LTS via Neo4j Supported Versions page.

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
    graph.py              # GraphStateManager class + PeerDecision type
    errors.py             # + Neo4jConnectionError, Neo4jWriteError (extend hierarchy)
    config.py             # Neo4jSettings (already exists, no changes)
    app.py                # AppState + create_app_state (extended with graph_manager)
    types.py              # AgentDecision, AgentPersona (already exist, no changes)
docker-compose.yml        # Neo4j 5.26 Community Edition (project root)
tests/
    test_graph.py         # Unit tests (mocked driver)
    test_graph_integration.py  # Integration tests (real Neo4j)
    conftest.py           # + Neo4j fixtures
```

### Pattern 1: Session-Per-Method with Managed Transactions
**What:** Each public method on GraphStateManager opens its own `AsyncSession`, executes a managed transaction (`execute_write` or `execute_read`), and closes the session when done.
**When to use:** Always -- this is the locked decision (D-07).
**Example:**
```python
# Source: Neo4j Python Driver Manual - concurrency docs
# https://neo4j.com/docs/python-manual/current/concurrency/

from neo4j import AsyncGraphDatabase, AsyncDriver

class GraphStateManager:
    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    async def create_cycle(self, seed_rumor: str) -> str:
        cycle_id = str(uuid.uuid4())
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(
                self._create_cycle_tx, cycle_id, seed_rumor
            )
        return cycle_id

    @staticmethod
    async def _create_cycle_tx(
        tx: AsyncManagedTransaction, cycle_id: str, seed_rumor: str
    ) -> None:
        await tx.run(
            "CREATE (c:Cycle {cycle_id: $cycle_id, seed_rumor: $seed_rumor, "
            "created_at: datetime()})",
            cycle_id=cycle_id,
            seed_rumor=seed_rumor,
        )
```

### Pattern 2: UNWIND Batch Write for Decisions
**What:** Pass all 100 agent decisions as a list parameter and use `UNWIND` to create Decision nodes + MADE/FOR/CITED relationships in a single transaction.
**When to use:** `write_decisions()` -- the core write path.
**Example:**
```python
# Source: Neo4j Performance docs + UNWIND Cypher Manual
# https://neo4j.com/docs/python-manual/current/performance/

async def write_decisions(
    self,
    agent_decisions: list[tuple[str, AgentDecision]],
    cycle_id: str,
    round_num: int,
) -> None:
    # Transform to parameter list for UNWIND
    params = [
        {
            "agent_id": agent_id,
            "signal": decision.signal.value,
            "confidence": decision.confidence,
            "sentiment": decision.sentiment,
            "rationale": decision.rationale,
            "cited_agents": list(decision.cited_agents),
        }
        for agent_id, decision in agent_decisions
    ]
    async with self._driver.session(database=self._database) as session:
        await session.execute_write(
            self._batch_write_decisions_tx, params, cycle_id, round_num
        )

@staticmethod
async def _batch_write_decisions_tx(
    tx: AsyncManagedTransaction,
    decisions: list[dict],
    cycle_id: str,
    round_num: int,
) -> None:
    # Create Decision nodes + MADE + FOR relationships
    await tx.run(
        """
        UNWIND $decisions AS d
        MATCH (a:Agent {id: d.agent_id})
        MATCH (c:Cycle {cycle_id: $cycle_id})
        CREATE (dec:Decision {
            decision_id: randomUUID(),
            cycle_id: $cycle_id,
            round: $round_num,
            signal: d.signal,
            confidence: d.confidence,
            sentiment: d.sentiment,
            rationale: d.rationale
        })
        CREATE (a)-[:MADE]->(dec)
        CREATE (dec)-[:FOR]->(c)
        WITH dec, d
        UNWIND d.cited_agents AS cited_id
        MATCH (cited:Agent {id: cited_id})
        CREATE (dec)-[:CITED]->(cited)
        """,
        decisions=decisions,
        cycle_id=cycle_id,
        round_num=round_num,
    )
```

### Pattern 3: Idempotent Schema Bootstrap
**What:** `ensure_schema()` uses `CREATE ... IF NOT EXISTS` for all constraints and indexes, then `MERGE` for agent nodes. Safe to call on every startup.
**When to use:** Application startup, before any simulation operations.
**Example:**
```python
# Source: Neo4j Cypher Manual - constraints and indexes
# https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/managing-indexes/create-indexes/

SCHEMA_STATEMENTS: list[str] = [
    # Constraints (Community Edition: uniqueness only)
    "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS "
    "FOR (a:Agent) REQUIRE a.id IS UNIQUE",

    "CREATE CONSTRAINT cycle_id_unique IF NOT EXISTS "
    "FOR (c:Cycle) REQUIRE c.cycle_id IS UNIQUE",

    # Composite range indexes for Decision lookup
    "CREATE INDEX decision_cycle_round IF NOT EXISTS "
    "FOR (d:Decision) ON (d.cycle_id, d.round)",

    # Single-property indexes for common lookups
    "CREATE INDEX agent_id_idx IF NOT EXISTS "
    "FOR (a:Agent) ON (a.id)",

    # Index for INFLUENCED_BY queries (Phase 8 schema, created now)
    "CREATE INDEX decision_id_idx IF NOT EXISTS "
    "FOR (d:Decision) ON (d.decision_id)",
]
```

### Pattern 4: Peer Decision Read with Static Ranking
**What:** Read top-N peer decisions for a given round, ranked by the agent's static `influence_weight_base`, excluding the requesting agent.
**When to use:** `read_peer_decisions()` -- the core read path used in Rounds 2 and 3.
**Example:**
```python
@staticmethod
async def _read_peers_tx(
    tx: AsyncManagedTransaction,
    agent_id: str,
    cycle_id: str,
    round_num: int,
    limit: int,
) -> list[dict]:
    result = await tx.run(
        """
        MATCH (a:Agent)-[:MADE]->(d:Decision)
        WHERE d.cycle_id = $cycle_id
          AND d.round = $round_num
          AND a.id <> $agent_id
        RETURN a.id AS agent_id,
               a.bracket AS bracket,
               d.signal AS signal,
               d.confidence AS confidence,
               d.sentiment AS sentiment,
               d.rationale AS rationale
        ORDER BY a.influence_weight_base DESC
        LIMIT $limit
        """,
        agent_id=agent_id,
        cycle_id=cycle_id,
        round_num=round_num,
        limit=limit,
    )
    return [dict(record) async for record in result]
```

### Anti-Patterns to Avoid
- **Individual transaction per decision:** Never `for decision in decisions: await session.execute_write(...)`. UNWIND handles the batch in a single transaction.
- **Shared session across coroutines:** Neo4j sessions are explicitly documented as not thread/task safe. Each method MUST create its own session.
- **Blocking driver calls:** Never use `GraphDatabase.driver()` (sync). Always `AsyncGraphDatabase.driver()`.
- **Hardcoded Cypher parameters:** Never f-string or concatenate values into Cypher queries. Always use `$param` placeholders.
- **Missing result consumption:** Always consume `AsyncResult` before the session/transaction closes. Use `await result.consume()`, `async for record in result`, or `await result.data()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection pooling | Custom connection manager | `AsyncGraphDatabase.driver()` built-in pool | Driver manages pool size (default 100), health checks, connection lifecycle |
| Transaction retry logic | Manual retry loops | `execute_read()`/`execute_write()` managed transactions | Driver automatically retries on transient errors (network hiccups, leader election) |
| Schema migration | Custom migration framework | `CREATE ... IF NOT EXISTS` idempotent Cypher | Schema is small (5-7 statements), idempotent Cypher eliminates need for migration tracking |
| UUID generation | Custom ID scheme | `uuid.uuid4()` for cycle_id, `randomUUID()` in Cypher for decision_id | Standard, collision-free, no coordination needed |
| Session management | Context manager wrapper | `async with self._driver.session()` | Driver's native context manager handles cleanup, error propagation, CancelledError |

**Key insight:** The neo4j async driver already solves connection pooling, transaction retries, session lifecycle, and cancellation handling. The GraphStateManager should be a thin Cypher-query wrapper, not a database abstraction layer.

## Common Pitfalls

### Pitfall 1: Forgetting to Consume AsyncResult
**What goes wrong:** `AsyncResult` is a lazy cursor. If you return from the transaction function without consuming records, the result buffer is discarded and you get empty data.
**Why it happens:** Sync code patterns (where `result.data()` works implicitly) don't translate directly to async.
**How to avoid:** Always `await result.data()`, `[record async for record in result]`, or `await result.consume()` inside the transaction function before returning.
**Warning signs:** Methods return empty lists when data is known to exist.

### Pitfall 2: Reusing Sessions Across Coroutines
**What goes wrong:** Two coroutines share the same `AsyncSession`, one commits while the other is mid-read, causing corrupted or partial results.
**Why it happens:** Optimization instinct -- "reuse the session for efficiency." Neo4j docs explicitly state sessions are not safe for concurrent use.
**How to avoid:** Session-per-method pattern (D-07). Each public method opens its own `async with self._driver.session()`.
**Warning signs:** Intermittent `SessionError` or inconsistent read results under load.

### Pitfall 3: MERGE vs CREATE Confusion in Batch Writes
**What goes wrong:** Using `MERGE` for Decision nodes (which should be unique per write) causes Neo4j to scan for existing matches on every insert, dramatically slowing batch writes.
**Why it happens:** MERGE seems "safer" but it adds a full-index-scan cost per node.
**How to avoid:** Use `CREATE` for Decision nodes (they are always new). Use `MERGE` only for Agent nodes (idempotent seeding) and Cycle nodes (if called multiple times).
**Warning signs:** `write_decisions()` takes >100ms for 100 decisions instead of <10ms.

### Pitfall 4: Missing `database` Parameter on Session
**What goes wrong:** Omitting `database=` forces the driver to make an extra round-trip to discover the default database, adding latency to every operation.
**Why it happens:** Default behavior seems fine in development.
**How to avoid:** Always pass `database=self._database` to `self._driver.session()`.
**Warning signs:** Extra 5-10ms latency on first query of each session.

### Pitfall 5: Cypher UNWIND with Empty List
**What goes wrong:** `UNWIND [] AS x` produces zero rows, which means all subsequent `CREATE`/`MATCH` clauses never execute. If the UNWIND is for `cited_agents` (which can be empty), the entire Decision creation is skipped.
**Why it happens:** Empty `cited_agents` list in `AgentDecision`.
**How to avoid:** Split the UNWIND for CITED relationships into a `WITH` block after Decision creation, using `CASE WHEN size(d.cited_agents) > 0` or a separate `FOREACH` / conditional `UNWIND`.
**Warning signs:** Round 1 decisions (which have no citations) are never persisted.

### Pitfall 6: Neo4j Container Not Ready on First Connection
**What goes wrong:** `GraphStateManager.ensure_schema()` runs before Neo4j has fully started, causing `ServiceUnavailable` exception.
**Why it happens:** Docker health check passes but Neo4j is still warming up indexes.
**How to avoid:** Use `await driver.verify_connectivity()` with a retry loop before calling `ensure_schema()`. Or rely on `execute_write` managed transaction retries.
**Warning signs:** Intermittent startup failures, especially on cold Docker starts.

## Code Examples

Verified patterns from official sources:

### Driver Initialization
```python
# Source: https://neo4j.com/docs/python-manual/current/concurrency/
from neo4j import AsyncGraphDatabase

async def create_driver(settings: Neo4jSettings) -> AsyncDriver:
    driver = AsyncGraphDatabase.driver(
        settings.uri,
        auth=(settings.username, settings.password),
        max_connection_pool_size=50,  # Default is 100, 50 sufficient for this app
        connection_acquisition_timeout=30.0,
    )
    await driver.verify_connectivity()
    return driver
```

### Idempotent Schema Application
```python
# Source: https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/managing-indexes/create-indexes/
# Source: https://neo4j.com/docs/cypher-manual/current/schema/constraints/create-constraints/

async def ensure_schema(self) -> None:
    """Apply all constraints, indexes, and seed Agent nodes. Idempotent."""
    async with self._driver.session(database=self._database) as session:
        for statement in SCHEMA_STATEMENTS:
            await session.run(statement)
    # Seed agents after schema is in place
    await self.seed_agents(self._personas)
```

### Agent Node Seeding via UNWIND + MERGE
```python
# Source: https://neo4j.com/docs/python-manual/current/performance/

async def seed_agents(self, agents: list[AgentPersona]) -> None:
    params = [
        {
            "id": a.id,
            "name": a.name,
            "bracket": a.bracket.value,
            "risk_profile": a.risk_profile,
            "temperature": a.temperature,
            "influence_weight_base": a.influence_weight_base,
        }
        for a in agents
    ]
    async with self._driver.session(database=self._database) as session:
        await session.execute_write(self._seed_agents_tx, params)

@staticmethod
async def _seed_agents_tx(
    tx: AsyncManagedTransaction, agents: list[dict]
) -> None:
    await tx.run(
        """
        UNWIND $agents AS a
        MERGE (agent:Agent {id: a.id})
        SET agent.name = a.name,
            agent.bracket = a.bracket,
            agent.risk_profile = a.risk_profile,
            agent.temperature = a.temperature,
            agent.influence_weight_base = a.influence_weight_base
        """,
        agents=agents,
    )
```

### UNWIND Batch Write Handling Empty cited_agents
```python
# Handling the empty-UNWIND pitfall for cited_agents:
# Split into two statements within the same transaction

@staticmethod
async def _batch_write_decisions_tx(
    tx: AsyncManagedTransaction,
    decisions: list[dict],
    cycle_id: str,
    round_num: int,
) -> None:
    # Step 1: Create Decision nodes + MADE + FOR relationships
    await tx.run(
        """
        UNWIND $decisions AS d
        MATCH (a:Agent {id: d.agent_id})
        MATCH (c:Cycle {cycle_id: $cycle_id})
        CREATE (dec:Decision {
            decision_id: d.decision_id,
            cycle_id: $cycle_id,
            round: $round_num,
            signal: d.signal,
            confidence: d.confidence,
            sentiment: d.sentiment,
            rationale: d.rationale
        })
        CREATE (a)-[:MADE]->(dec)
        CREATE (dec)-[:FOR]->(c)
        """,
        decisions=decisions,
        cycle_id=cycle_id,
        round_num=round_num,
    )

    # Step 2: Create CITED relationships (only for decisions with citations)
    cited_params = [
        {"decision_id": d["decision_id"], "cited_id": cited_id}
        for d in decisions
        for cited_id in d["cited_agents"]
    ]
    if cited_params:
        await tx.run(
            """
            UNWIND $cited AS c
            MATCH (dec:Decision {decision_id: c.decision_id})
            MATCH (agent:Agent {id: c.cited_id})
            CREATE (dec)-[:CITED]->(agent)
            """,
            cited=cited_params,
        )
```

### docker-compose.yml
```yaml
# Source: https://neo4j.com/docs/operations-manual/current/docker/introduction/
services:
  neo4j:
    image: neo4j:5.26-community
    container_name: alphaswarm-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/alphaswarm
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p alphaswarm 'RETURN 1'"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  neo4j_data:
```

### PeerDecision Return Type (Discretion: frozen dataclass)
```python
# Follows project convention: frozen dataclasses for immutable read data
# (matches StateSnapshot, GovernorMetrics pattern in state.py)

from dataclasses import dataclass

@dataclass(frozen=True)
class PeerDecision:
    """Immutable peer decision read from Neo4j for influence rounds."""
    agent_id: str
    bracket: str
    signal: str
    confidence: float
    sentiment: float
    rationale: str
```

### Error Types (Discretion: extend existing hierarchy)
```python
# Follows project convention: domain exceptions in errors.py
# (matches OllamaInferenceError, GovernorCrisisError pattern)

class Neo4jConnectionError(Exception):
    """Raised when Neo4j driver cannot connect or verify connectivity."""
    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error

class Neo4jWriteError(Exception):
    """Raised when a Neo4j write transaction fails after retries."""
    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `neo4j-driver` package | `neo4j` package | v5.0 (2022) | Old package name deprecated; import path unchanged |
| `session.write_transaction()` | `session.execute_write()` | v5.0 | Old name deprecated; new name is idiomatic |
| `session.read_transaction()` | `session.execute_read()` | v5.0 | Old name deprecated; new name is idiomatic |
| `GraphDatabase.driver()` sync-only | `AsyncGraphDatabase.driver()` | v5.0 | Native asyncio support; no need for thread pool executor |
| Neo4j 5.x versioning | Neo4j 2025.x/2026.x calendar versioning | 2025 | Server versioning changed; 5.26 is last 5.x LTS |
| BTREE indexes | RANGE indexes (default) | Neo4j 5.0 | RANGE is the new default; old BTREE syntax deprecated |

**Deprecated/outdated:**
- `neo4j-driver` package: Use `neo4j` instead
- `session.write_transaction()` / `session.read_transaction()`: Use `execute_write()` / `execute_read()`
- `CREATE INDEX ON :Label(prop)`: Use `CREATE INDEX name FOR (n:Label) ON (n.prop)` (named index syntax)
- BTREE index provider: RANGE is default in Neo4j 5+

## Open Questions

1. **Neo4j Rust Extension Performance**
   - What we know: `neo4j-rust-ext` provides 3-10x speedup for driver serialization; ARM64 macOS wheels available.
   - What's unclear: Whether the speedup is meaningful for this workload (100 decisions per batch is small).
   - Recommendation: Skip for Phase 4. Add in Phase 7-8 if profiling shows driver overhead.

2. **Connection Pool Sizing**
   - What we know: Default pool is 100 connections. App will have at most ~8-16 concurrent coroutines (governor limit).
   - What's unclear: Optimal pool size for M1 Max with Neo4j in Docker.
   - Recommendation: Set `max_connection_pool_size=50` (conservative). Tune later if connection acquisition stalls.

3. **Decision ID Generation**
   - What we know: `randomUUID()` in Cypher generates UUIDs server-side. `uuid.uuid4()` generates client-side.
   - What's unclear: Whether server-side or client-side UUID generation is preferable for the split-UNWIND pattern (CITED relationships need to reference decision_id).
   - Recommendation: Generate `decision_id` client-side via `str(uuid.uuid4())` and pass as parameter. This avoids a second query to retrieve server-generated IDs.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | Neo4j container | Yes | 29.3.0 | -- |
| Docker Compose | docker-compose.yml | Yes | v5.1.0 | -- |
| `neo4j` Python package | GraphStateManager | No (not yet installed) | Will install 5.28.3 | `uv add` in Phase 4 |
| Neo4j 5.26 Docker image | Database server | Not pulled yet | Will pull 5.26-community | `docker compose up` pulls automatically |
| Python 3.11+ | Runtime | Yes | 3.11+ (project minimum) | -- |

**Missing dependencies with no fallback:**
- None -- all required tools are available.

**Missing dependencies with fallback:**
- None -- `neo4j` Python package and Docker image will be installed/pulled as part of Phase 4 execution.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_graph.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-05 | Schema created with composite indexes (idempotent) | integration | `uv run pytest tests/test_graph_integration.py::test_ensure_schema_idempotent -x` | No -- Wave 0 |
| INFRA-05 | Peer decision reads complete under 5ms with index | integration | `uv run pytest tests/test_graph_integration.py::test_peer_read_latency -x` | No -- Wave 0 |
| INFRA-06 | write_decisions batches 100 decisions in single UNWIND tx | integration | `uv run pytest tests/test_graph_integration.py::test_batch_write_100_decisions -x` | No -- Wave 0 |
| INFRA-06 | Session-per-method prevents corrupted concurrent reads | integration | `uv run pytest tests/test_graph_integration.py::test_concurrent_peer_reads -x` | No -- Wave 0 |
| D-08 | GraphStateManager API surface (ensure_schema, create_cycle, write_decisions, read_peer_decisions, close) | unit | `uv run pytest tests/test_graph.py -x` | No -- Wave 0 |
| D-06 | Agent nodes seeded from persona config via MERGE | integration | `uv run pytest tests/test_graph_integration.py::test_seed_agents_idempotent -x` | No -- Wave 0 |
| D-04 | Docker compose starts Neo4j with health check | manual | `docker compose up -d && docker compose ps` | N/A |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_graph.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_graph.py` -- Unit tests for GraphStateManager (mocked driver); covers D-08 API surface
- [ ] `tests/test_graph_integration.py` -- Integration tests requiring running Neo4j; covers INFRA-05, INFRA-06
- [ ] `tests/conftest.py` -- Add Neo4j fixtures (driver, cleanup between tests)
- [ ] `neo4j` package install: `uv add "neo4j>=5.28,<6.0"`

## Sources

### Primary (HIGH confidence)
- [Neo4j Python Driver Concurrency Docs](https://neo4j.com/docs/python-manual/current/concurrency/) -- async driver patterns, session safety rules
- [Neo4j Python Driver Performance Docs](https://neo4j.com/docs/python-manual/current/performance/) -- UNWIND batch pattern, connection pool, database parameter
- [Neo4j Python Driver Transactions Docs](https://neo4j.com/docs/python-manual/current/transactions/) -- execute_read/execute_write, managed transactions, retry semantics
- [Neo4j Python Driver 6.1 Async API](https://neo4j.com/docs/api/python-driver/current/async_api.html) -- AsyncGraphDatabase, AsyncSession, AsyncManagedTransaction
- [Neo4j Cypher Manual - Create Indexes](https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/managing-indexes/create-indexes/) -- CREATE INDEX IF NOT EXISTS, composite range indexes
- [Neo4j Cypher Manual - Create Constraints](https://neo4j.com/docs/cypher-manual/current/schema/constraints/create-constraints/) -- CREATE CONSTRAINT IF NOT EXISTS, uniqueness constraints
- [Neo4j Docker Introduction](https://neo4j.com/docs/operations-manual/current/docker/introduction/) -- Docker image tags, environment variables, volume mounts
- [Neo4j Supported Versions](https://neo4j.com/developer/kb/neo4j-supported-versions/) -- 5.26 LTS support timeline, version compatibility matrix
- [PyPI neo4j](https://pypi.org/project/neo4j/) -- Version 5.28.3, latest 5.x release

### Secondary (MEDIUM confidence)
- [DeepWiki - Async Driver and Sessions](https://deepwiki.com/neo4j/neo4j-python-driver/7.1-async-driver-and-sessions) -- Comprehensive async patterns, verified against official docs
- [DeepWiki - Driver Configuration](https://deepwiki.com/neo4j/neo4j-python-driver/5.1-driver-configuration) -- Pool size defaults (100), connection_acquisition_timeout
- [Neo4j Python Driver 6.x Changelog](https://github.com/neo4j/neo4j-python-driver/wiki/6.x-Changelog) -- Breaking changes 5.x to 6.x

### Tertiary (LOW confidence)
- None -- all critical claims verified against official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- versions verified via PyPI, Docker Hub, Neo4j supported versions matrix
- Architecture: HIGH -- session-per-method, UNWIND batch, and composite index patterns verified via official Neo4j driver and Cypher documentation
- Pitfalls: HIGH -- empty UNWIND, session sharing, MERGE vs CREATE performance documented in official sources and community issues

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (30 days -- Neo4j 5.x is stable LTS)
