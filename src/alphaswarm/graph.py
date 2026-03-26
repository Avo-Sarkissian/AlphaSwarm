"""Neo4j graph state management for AlphaSwarm consensus cycles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from neo4j.exceptions import Neo4jError

from alphaswarm.errors import Neo4jConnectionError, Neo4jWriteError

if TYPE_CHECKING:
    from neo4j import AsyncDriver, AsyncManagedTransaction

    from alphaswarm.types import AgentDecision, AgentPersona, SeedEvent

log = structlog.get_logger(component="graph")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PeerDecision:
    """Immutable peer decision read from Neo4j for influence rounds."""

    agent_id: str
    bracket: str
    signal: str
    confidence: float
    sentiment: float
    rationale: str


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

SCHEMA_STATEMENTS: list[str] = [
    "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT cycle_id_unique IF NOT EXISTS FOR (c:Cycle) REQUIRE c.cycle_id IS UNIQUE",
    "CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE",
    "CREATE INDEX decision_cycle_round IF NOT EXISTS FOR (d:Decision) ON (d.cycle_id, d.round)",
    "CREATE INDEX agent_id_idx IF NOT EXISTS FOR (a:Agent) ON (a.id)",
    "CREATE INDEX decision_id_idx IF NOT EXISTS FOR (d:Decision) ON (d.decision_id)",
]


# ---------------------------------------------------------------------------
# GraphStateManager
# ---------------------------------------------------------------------------


class GraphStateManager:
    """Manages Neo4j graph state for consensus simulation cycles.

    Uses session-per-method pattern (D-07) with minimal API surface (D-08).
    """

    def __init__(
        self,
        driver: AsyncDriver,
        personas: list[AgentPersona],
        database: str = "neo4j",
    ) -> None:
        self._driver = driver
        self._personas = personas
        self._database = database
        self._log = structlog.get_logger(component="graph")

    async def ensure_schema(self) -> None:
        """Apply idempotent schema constraints and indexes, then seed agents.

        Per D-05: open one session, execute each statement sequentially,
        then seed all agent nodes.
        """
        async with self._driver.session(database=self._database) as session:
            for stmt in SCHEMA_STATEMENTS:
                await session.run(stmt)

        self._log.info("schema_applied", statement_count=len(SCHEMA_STATEMENTS))
        await self.seed_agents(self._personas)

    async def seed_agents(self, agents: list[AgentPersona]) -> None:
        """Seed Agent nodes from persona config via UNWIND + MERGE.

        Per D-06: transforms AgentPersona list to flat dicts for Cypher parameters.
        """
        agent_params = [
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
            await session.execute_write(self._seed_agents_tx, agent_params)

        self._log.info("agents_seeded", count=len(agents))

    @staticmethod
    async def _seed_agents_tx(
        tx: AsyncManagedTransaction,
        agents: list[dict],  # type: ignore[type-arg]
    ) -> None:
        """Transaction function for UNWIND + MERGE agent seeding."""
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

    async def create_cycle(self, seed_rumor: str) -> str:
        """Create a new Cycle node with a uuid4 cycle_id.

        Per D-10: generate unique cycle_id, persist with seed_rumor and timestamp.
        """
        cycle_id = str(uuid.uuid4())

        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._create_cycle_tx, cycle_id, seed_rumor)

        self._log.info("cycle_created", cycle_id=cycle_id)
        return cycle_id

    @staticmethod
    async def _create_cycle_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        seed_rumor: str,
    ) -> None:
        """Transaction function for Cycle node creation."""
        await tx.run(
            "CREATE (c:Cycle {cycle_id: $cycle_id, seed_rumor: $seed_rumor, created_at: datetime()})",
            cycle_id=cycle_id,
            seed_rumor=seed_rumor,
        )

    async def create_cycle_with_seed_event(
        self, seed_rumor: str, seed_event: SeedEvent,
    ) -> str:
        """Atomically create Cycle node with seed event entities.

        Per review concern: create_cycle() then write_seed_event() as separate
        operations could leave orphan Cycle nodes. This method wraps both in a
        single transaction. Also persists overall_sentiment on the Cycle node.

        Args:
            seed_rumor: Raw rumor text for the Cycle node.
            seed_event: Parsed seed event with entities and overall_sentiment.

        Returns:
            cycle_id: The UUID4 string for the created Cycle.
        """
        cycle_id = str(uuid.uuid4())
        entity_params = [
            {
                "name": e.name,
                "type": e.type.value,
                "relevance": e.relevance,
                "sentiment": e.sentiment,
            }
            for e in seed_event.entities
        ]
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(
                    self._create_cycle_with_entities_tx,
                    cycle_id,
                    seed_rumor,
                    seed_event.overall_sentiment,
                    entity_params,
                )
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to create cycle with seed event for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.info(
            "cycle_with_seed_event_created",
            cycle_id=cycle_id,
            entity_count=len(entity_params),
            overall_sentiment=seed_event.overall_sentiment,
        )
        return cycle_id

    @staticmethod
    async def _create_cycle_with_entities_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        seed_rumor: str,
        overall_sentiment: float,
        entities: list[dict],  # type: ignore[type-arg]
    ) -> None:
        """Single transaction: create Cycle with overall_sentiment, then UNWIND Entity+MENTIONS."""
        # Create Cycle node with overall_sentiment
        await tx.run(
            """
            CREATE (c:Cycle {
                cycle_id: $cycle_id,
                seed_rumor: $seed_rumor,
                overall_sentiment: $overall_sentiment,
                created_at: datetime()
            })
            """,
            cycle_id=cycle_id,
            seed_rumor=seed_rumor,
            overall_sentiment=overall_sentiment,
        )
        # Create Entity nodes + MENTIONS relationships (only if entities exist)
        if entities:
            await tx.run(
                """
                UNWIND $entities AS e
                MERGE (entity:Entity {name: e.name, type: e.type})
                WITH entity, e
                MATCH (c:Cycle {cycle_id: $cycle_id})
                CREATE (c)-[:MENTIONS {relevance: e.relevance, sentiment: e.sentiment}]->(entity)
                """,
                entities=entities,
                cycle_id=cycle_id,
            )

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        await self._driver.close()
        self._log.info("driver_closed")

    # ------------------------------------------------------------------
    # Decision write/read methods (Plan 02)
    # ------------------------------------------------------------------

    async def write_decisions(
        self,
        agent_decisions: list[tuple[str, AgentDecision]],
        cycle_id: str,
        round_num: int,
    ) -> None:
        """Batch-write agent decisions via UNWIND. Per D-08, D-01, D-03."""
        params = [
            {
                "decision_id": str(uuid.uuid4()),
                "agent_id": agent_id,
                "signal": decision.signal.value,
                "confidence": decision.confidence,
                "sentiment": decision.sentiment,
                "rationale": decision.rationale,
                "cited_agents": list(decision.cited_agents),
            }
            for agent_id, decision in agent_decisions
        ]
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(
                    self._batch_write_decisions_tx, params, cycle_id, round_num
                )
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to write {len(agent_decisions)} decisions for cycle {cycle_id} round {round_num}",
                original_error=exc,
            ) from exc
        self._log.info(
            "decisions_written",
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(agent_decisions),
        )

    @staticmethod
    async def _batch_write_decisions_tx(
        tx: AsyncManagedTransaction,
        decisions: list[dict],  # type: ignore[type-arg]
        cycle_id: str,
        round_num: int,
    ) -> None:
        """Transaction function for UNWIND batch decision creation.

        Two-statement split avoids empty-UNWIND pitfall (Pitfall 5 from RESEARCH.md):
        Statement 1: Decision nodes + MADE + FOR relationships.
        Statement 2: CITED relationships (only if any citations exist).
        """
        # Statement 1: Create Decision nodes with MADE and FOR relationships
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

        # Statement 2: Create CITED relationships (only if any citations exist)
        cited_params = [
            {"decision_id": d["decision_id"], "cited_id": cid}
            for d in decisions
            for cid in d["cited_agents"]
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

    async def read_peer_decisions(
        self,
        agent_id: str,
        cycle_id: str,
        round_num: int,
        limit: int = 5,
    ) -> list[PeerDecision]:
        """Read top-N peer decisions ranked by static influence_weight_base. Per D-09."""
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_peers_tx, agent_id, cycle_id, round_num, limit
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read peer decisions for agent {agent_id} cycle {cycle_id} round {round_num}",
                original_error=exc,
            ) from exc
        self._log.debug(
            "peer_decisions_read",
            agent_id=agent_id,
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(records),
        )
        return [
            PeerDecision(
                agent_id=r["agent_id"],
                bracket=r["bracket"],
                signal=r["signal"],
                confidence=r["confidence"],
                sentiment=r["sentiment"],
                rationale=r["rationale"],
            )
            for r in records
        ]

    @staticmethod
    async def _read_peers_tx(
        tx: AsyncManagedTransaction,
        agent_id: str,
        cycle_id: str,
        round_num: int,
        limit: int,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for reading peer decisions by influence weight."""
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

    # ------------------------------------------------------------------
    # Influence edge computation (Phase 8: dynamic influence topology)
    # ------------------------------------------------------------------

    async def compute_influence_edges(
        self,
        cycle_id: str,
        up_to_round: int,
        total_agents: int,
    ) -> dict[str, float]:
        """Compute and write INFLUENCED_BY edges from CITED patterns (D-01, D-02, D-03, D-04).

        Args:
            cycle_id: Current simulation cycle ID.
            up_to_round: Include citations from rounds 1..up_to_round (cumulative per D-04).
            total_agents: Number of agents that produced valid decisions. Used as
                normalization denominator (weight = citations / total_agents).
                Use active agent count, not global swarm size, to handle partial failures.

        Returns:
            dict[str, float]: Mapping of agent_id to normalized influence weight.
                Empty dict if no citations found. Plan 02 depends on this return type
                for downstream peer selection.
        """
        from collections import Counter

        try:
            async with self._driver.session(database=self._database) as session:
                # Read citation PAIRS (source_id, target_id) for pair-aware INFLUENCED_BY edges
                pairs = await session.execute_read(
                    self._read_citation_pairs_tx, cycle_id, up_to_round,
                )
                if not pairs:
                    self._log.info(
                        "no_citations_found",
                        cycle_id=cycle_id,
                        up_to_round=up_to_round,
                    )
                    return {}

                # Compute per-target citation frequency from deduplicated pairs
                target_counts: Counter[str] = Counter(p["target_id"] for p in pairs)

                # Compute normalized weights (D-01: weight = citations / total_agents)
                weights: dict[str, float] = {
                    agent_id: count / total_agents
                    for agent_id, count in target_counts.items()
                }

                # Build edge list: each unique (source, target) pair gets the target's weight
                edges = [
                    {
                        "source_id": p["source_id"],
                        "target_id": p["target_id"],
                        "weight": weights[p["target_id"]],
                    }
                    for p in pairs
                ]

                # Batch-write INFLUENCED_BY edges
                await session.execute_write(
                    self._write_influence_edges_tx, edges, cycle_id, up_to_round,
                )

            self._log.info(
                "influence_edges_computed",
                cycle_id=cycle_id,
                up_to_round=up_to_round,
                edge_count=len(edges),
                agents_with_influence=len(weights),
            )
            return weights

        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to compute influence edges for cycle {cycle_id} round {up_to_round}",
                original_error=exc,
            ) from exc

    @staticmethod
    async def _read_citation_pairs_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        up_to_round: int,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function returning deduplicated (source_id, target_id) citation pairs.

        Pair-aware query: returns DISTINCT (author, cited) pairs with self-citation filter.
        Cumulative across rounds via d.round <= $up_to_round (D-04).
        DISTINCT deduplicates within same (author, cited) pair per round (D-02).
        """
        result = await tx.run(
            """
            MATCH (author:Agent)-[:MADE]->(d:Decision)-[:CITED]->(cited:Agent)
            WHERE d.cycle_id = $cycle_id AND d.round <= $up_to_round
              AND author.id <> cited.id
            RETURN DISTINCT author.id AS source_id, cited.id AS target_id
            """,
            cycle_id=cycle_id,
            up_to_round=up_to_round,
        )
        return [dict(record) async for record in result]

    @staticmethod
    async def _write_influence_edges_tx(
        tx: AsyncManagedTransaction,
        edges: list[dict],  # type: ignore[type-arg]
        cycle_id: str,
        round_num: int,
    ) -> None:
        """Transaction function for UNWIND batch INFLUENCED_BY edge creation.

        Each round writes its own INFLUENCED_BY edges with round property.
        Multiple edges between the same pair across different rounds are expected.
        Downstream queries MUST filter by round to avoid double-counting.
        CREATE (not MERGE) because each round snapshot is a distinct edge.
        """
        if not edges:
            return

        await tx.run(
            """
            UNWIND $edges AS e
            MATCH (src:Agent {id: e.source_id})
            MATCH (tgt:Agent {id: e.target_id})
            CREATE (src)-[:INFLUENCED_BY {
                weight: e.weight,
                cycle_id: $cycle_id,
                round: $round_num
            }]->(tgt)
            """,
            edges=edges,
            cycle_id=cycle_id,
            round_num=round_num,
        )
