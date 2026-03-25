# Phase 4: Neo4j Graph State - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 persists agent decisions and influence relationships in Neo4j with sub-5ms read performance and safe concurrent access. Delivers: Docker setup for Neo4j Community Edition, graph schema with composite indexes, a GraphStateManager with UNWIND batch writes and session-per-coroutine reads, and agent node seeding. No simulation logic, no TUI rendering, no influence topology computation (Phase 8).

</domain>

<decisions>
## Implementation Decisions

### Graph Schema Design
- **D-01:** Decision modeled as a node, not a relationship. Agent-[:MADE]->Decision-[:FOR]->Cycle. Each Decision node holds: cycle_id, round, signal, confidence, sentiment, rationale. 300 Decision nodes per cycle (100 agents x 3 rounds).
- **D-02:** INFLUENCED_BY connects Decision-to-Decision (not Agent-to-Agent). Provides granular traceability of exactly which decision influenced which. Weight property on the edge. Implemented in Phase 8 — schema/index created in Phase 4.
- **D-03:** cited_agents stored as explicit CITED relationships (Decision-[:CITED]->Agent), not as a list property. Enables graph-native citation queries. Separate from INFLUENCED_BY — CITED is raw LLM output, INFLUENCED_BY is computed topology (Phase 8).

### Docker & Bootstrap
- **D-04:** docker-compose.yml at project root with Neo4j 5 Community Edition. Ports: 7687 (Bolt), 7474 (Browser). Auth: neo4j/alphaswarm (matching existing Neo4jSettings defaults). Volume mount for data persistence. Health check via cypher-shell.
- **D-05:** Schema auto-applied on startup via `GraphStateManager.ensure_schema()` — idempotent `CREATE ... IF NOT EXISTS` for all constraints and indexes. Zero manual steps after `docker compose up -d`.
- **D-06:** All 100 Agent nodes eagerly seeded during `ensure_schema()` via UNWIND + MERGE from persona config. Agents are always present before any simulation runs.

### GraphStateManager API
- **D-07:** Session-per-method pattern — each public method opens its own short-lived `async with self._driver.session()` internally. Callers never see or manage sessions. Aligns with session-per-coroutine requirement (INFRA-06).
- **D-08:** Minimal core API surface for Phase 4:
  - `ensure_schema()` — constraints, indexes, agent node seeding
  - `seed_agents(agents: list[AgentPersona])` — MERGE agent nodes from config
  - `create_cycle(seed_rumor: str) -> str` — creates Cycle node, returns uuid4 cycle_id
  - `write_decisions(agent_decisions: list[tuple[str, AgentDecision]], cycle_id: str, round_num: int)` — UNWIND batch write of Decision nodes + MADE/FOR/CITED relationships
  - `read_peer_decisions(agent_id: str, cycle_id: str, round_num: int, limit: int = 5) -> list[PeerDecision]` — top-N peer decisions for a given round
  - `close()` — driver cleanup
  - Influence topology methods (write_influence_edges, read_bracket_aggregation, etc.) deferred to Phase 8.
- **D-09:** Pre-Phase 8 peer ranking uses static `influence_weight_base` from Agent node properties (set from AgentPersona config). `ORDER BY a.influence_weight_base DESC LIMIT 5`. Phase 8 replaces with dynamic citation-based INFLUENCED_BY edge weights.

### Data Lifecycle
- **D-10:** cycle_id generated via `uuid.uuid4()` — globally unique, no collision risk.
- **D-11:** Keep all cycles indefinitely, no pruning. Composite indexes on cycle_id keep queries fast regardless of history size. Manual cleanup via Cypher if needed.
- **D-12:** Agent nodes shared across cycles — 100 persistent Agent nodes. Decisions, MADE, FOR, CITED relationships are scoped by cycle_id. Different simulations share the same agent graph.

### Claude's Discretion
- Neo4j async driver connection pool configuration (max_connection_pool_size, connection_acquisition_timeout)
- Exact composite index definitions beyond the required (Agent.id) and (Decision.cycle_id, Decision.round)
- PeerDecision return type design (dataclass vs TypedDict vs Pydantic)
- Internal transaction function signatures (_batch_write_tx, etc.)
- Test fixture design for Neo4j integration tests (testcontainers vs real Docker instance)
- Error types for Neo4j failures (connection errors, constraint violations)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — INFRA-05 (composite indexes, sub-5ms reads), INFRA-06 (GraphStateManager, session-per-coroutine, UNWIND batch writes)
- `.planning/ROADMAP.md` — Phase 4 success criteria and dependencies

### Existing Implementation
- `src/alphaswarm/config.py` — Neo4jSettings (uri, username, password, database), AppSettings.neo4j
- `src/alphaswarm/app.py` — AppState container with commented neo4j_driver slot (line 34), create_app_state factory
- `src/alphaswarm/types.py` — AgentDecision (signal, confidence, sentiment, rationale, cited_agents), AgentPersona, BracketType, SimulationPhase
- `src/alphaswarm/state.py` — StateStore stub, StateSnapshot, GovernorMetrics
- `src/alphaswarm/errors.py` — Existing error hierarchy (OllamaInferenceError, ModelLoadError, ParseError)

### Prior Phase Context
- `.planning/phases/01-project-foundation/01-CONTEXT.md` — AppState container pattern, frozen Pydantic models, structlog with contextvars
- `.planning/phases/02-ollama-integration/02-CONTEXT.md` — AgentDecision type, WorkerPersonaConfig TypedDict pattern
- `.planning/phases/03-resource-governance/03-CONTEXT.md` — Governor metrics emission pattern (state change only), StateStore data contract

### Project Context
- `.planning/PROJECT.md` — Key decision: "Cycle-scoped Neo4j edges (cycle_id on relationships)"
- `.planning/research/ARCHITECTURE.md` — Component boundaries and data flow

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Neo4jSettings` in `config.py` — connection config already defined with defaults matching docker-compose
- `AppState` in `app.py` — has commented slot for neo4j_driver; factory pattern for initialization order
- `AgentDecision` in `types.py` — the data model being persisted, with all required fields
- `AgentPersona` in `types.py` — source for Agent node properties (id, name, bracket, influence_weight_base)
- Error hierarchy in `errors.py` — pattern to follow for Neo4j-specific errors

### Established Patterns
- `asynccontextmanager` for resource lifecycle (from worker.py)
- `structlog.get_logger(component="...")` for component-scoped logging
- Pydantic `BaseModel` for settings, `TypedDict` for hot-path configs
- `create_app_state()` factory with initialization order enforcement
- Frozen dataclasses for immutable data (StateSnapshot, GovernorMetrics)

### Integration Points
- `AppState` — GraphStateManager (or AsyncDriver) added here; `create_app_state()` extended
- `Neo4jSettings` — already wired into `AppSettings.neo4j`
- `AgentPersona` list — `app.personas` provides the 100 personas for Agent node seeding
- `StateStore` — potential future integration for graph metrics (not Phase 4 scope)

</code_context>

<specifics>
## Specific Ideas

- Graph structure: `(:Agent)-[:MADE]->(:Decision)-[:FOR]->(:Cycle)` with `(:Decision)-[:CITED]->(:Agent)` and `(:Decision)-[:INFLUENCED_BY]->(:Decision)` (Phase 8)
- Neo4j 5 Community Edition in Docker — matches the `neo4j` async driver package
- `neo4j` async driver package needs to be added to pyproject.toml dependencies
- UNWIND pattern for batch writes matches the 100-decisions-per-transaction requirement
- Pre-Phase 8 peer reads fall back to influence_weight_base ordering — provides meaningful (not random) peer selection even before dynamic topology exists

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-neo4j-graph-state*
*Context gathered: 2026-03-25*
