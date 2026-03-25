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

    from alphaswarm.types import AgentDecision, AgentPersona

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
