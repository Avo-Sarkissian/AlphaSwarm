"""Neo4j graph state management for AlphaSwarm consensus cycles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

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
    # Stub methods (implemented in Plan 02)
    # ------------------------------------------------------------------

    async def write_decisions(
        self,
        agent_decisions: list[tuple[str, AgentDecision]],
        cycle_id: str,
        round_num: int,
    ) -> None:
        """Write agent decisions to Neo4j. Implemented in 04-02."""
        raise NotImplementedError("Implemented in 04-02")

    async def read_peer_decisions(
        self,
        agent_id: str,
        cycle_id: str,
        round_num: int,
        limit: int = 5,
    ) -> list[PeerDecision]:
        """Read peer decisions from Neo4j. Implemented in 04-02."""
        raise NotImplementedError("Implemented in 04-02")
