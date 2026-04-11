"""Neo4j graph state management for AlphaSwarm consensus cycles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from neo4j.exceptions import Neo4jError

from alphaswarm.errors import Neo4jConnectionError, Neo4jWriteError
from alphaswarm.interview import InterviewContext, RoundDecision, _strip_json_instructions

from alphaswarm.types import SignalType

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


@dataclass(frozen=True)
class RankedPost:
    """A peer's published rationale post ranked by influence weight."""

    post_id: str
    agent_id: str
    bracket: str
    signal: str
    confidence: float
    content: str
    influence_weight: float
    round_num: int


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
    "CREATE INDEX episode_cycle_round IF NOT EXISTS FOR (re:RationaleEpisode) ON (re.cycle_id, re.round)",
    "CREATE INDEX post_cycle_round IF NOT EXISTS FOR (p:Post) ON (p.cycle_id, p.round_num)",
    "CREATE INDEX post_id_idx IF NOT EXISTS FOR (p:Post) ON (p.post_id)",
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
        *,
        decision_ids: list[str] | None = None,
    ) -> list[str]:
        """Batch-write agent decisions via UNWIND. Per D-08, D-01, D-03.

        Args:
            agent_decisions: List of (agent_id, AgentDecision) tuples.
            cycle_id: Current simulation cycle ID.
            round_num: Current round number (1, 2, or 3).
            decision_ids: Optional pre-generated decision IDs. If provided, must have
                the same length as agent_decisions. If None, UUIDs are generated
                internally (backward compatible). Pre-generating IDs allows the caller
                to pass the same IDs to WriteBuffer.push() before Decision nodes exist
                in Neo4j (Pitfall 1 from RESEARCH.md).

        Returns:
            list[str]: The decision_id strings for each decision written.
                Callers can pass these to WriteBuffer.push() to link EpisodeRecords.
        """
        if decision_ids is not None and len(decision_ids) != len(agent_decisions):
            raise ValueError(
                f"decision_ids length {len(decision_ids)} != agent_decisions length {len(agent_decisions)}"
            )
        ids = decision_ids if decision_ids is not None else [str(uuid.uuid4()) for _ in agent_decisions]
        params = [
            {
                "decision_id": did,
                "agent_id": agent_id,
                "signal": decision.signal.value,
                "confidence": decision.confidence,
                "sentiment": decision.sentiment,
                "rationale": decision.rationale,
                "cited_agents": list(decision.cited_agents),
            }
            for did, (agent_id, decision) in zip(ids, agent_decisions)
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
        return ids

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

    # ------------------------------------------------------------------
    # Phase 12: Post nodes for social influence dynamics
    # ------------------------------------------------------------------

    async def write_posts(
        self,
        agent_decisions: list[tuple[str, AgentDecision]],
        decision_ids: list[str],
        cycle_id: str,
        round_num: int,
    ) -> list[str]:
        """Batch-write Post nodes from Decision rationale with zero extra inference (SOCIAL-01).

        Creates Post nodes linked to Agent (AUTHORED) and Decision (HAS_POST).
        Filters out PARSE_ERROR decisions to prevent error text from becoming posts.

        Args:
            agent_decisions: List of (agent_id, AgentDecision) tuples.
            decision_ids: Pre-generated decision IDs from write_decisions(). Must match
                length of agent_decisions. PARSE_ERROR entries are skipped along with
                their corresponding decision_id.
            cycle_id: Current simulation cycle ID.
            round_num: Current round number (1, 2, or 3).

        Returns:
            list[str]: The post_id strings for each Post written (PARSE_ERROR excluded).
        """
        posts: list[dict] = []  # type: ignore[type-arg]
        post_ids: list[str] = []
        for did, (agent_id, decision) in zip(decision_ids, agent_decisions):
            if decision.signal == SignalType.PARSE_ERROR:
                continue
            pid = str(uuid.uuid4())
            post_ids.append(pid)
            posts.append({
                "post_id": pid,
                "decision_id": did,
                "agent_id": agent_id,
                "content": decision.rationale,
                "signal": decision.signal.value,
                "confidence": decision.confidence,
                "round_num": round_num,
                "cycle_id": cycle_id,
            })
        if not posts:
            return []
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(
                    self._batch_write_posts_tx, posts, cycle_id, round_num,
                )
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to write {len(posts)} posts for cycle {cycle_id} round {round_num}",
                original_error=exc,
            ) from exc
        self._log.info(
            "posts_written", cycle_id=cycle_id, round_num=round_num, count=len(posts),
        )
        return post_ids

    @staticmethod
    async def _batch_write_posts_tx(
        tx: AsyncManagedTransaction,
        posts: list[dict],  # type: ignore[type-arg]
        cycle_id: str,
        round_num: int,
    ) -> None:
        """UNWIND batch create Post nodes linked to Agent (AUTHORED) and Decision (HAS_POST)."""
        await tx.run(
            """
            UNWIND $posts AS p
            MATCH (a:Agent {id: p.agent_id})
            MATCH (d:Decision {decision_id: p.decision_id})
            CREATE (post:Post {
                post_id: p.post_id,
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
            """,
            posts=posts,
            cycle_id=cycle_id,
            round_num=round_num,
        )

    async def read_ranked_posts(
        self,
        agent_id: str,
        cycle_id: str,
        source_round: int,
        limit: int = 10,
    ) -> list[RankedPost]:
        """Read top-K peer posts ranked by INFLUENCED_BY weight (SOCIAL-02).

        Uses OPTIONAL MATCH on INFLUENCED_BY edges from the reading agent to
        the post author. Falls back to author's influence_weight_base when no
        dynamic edge exists. Excludes self-posts and PARSE_ERROR posts.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.execute_read(
                    self._read_ranked_posts_tx, agent_id, cycle_id, source_round, limit,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read ranked posts for agent {agent_id} cycle {cycle_id} round {source_round}",
                original_error=exc,
            ) from exc
        self._log.debug(
            "ranked_posts_read", agent_id=agent_id, count=len(result),
        )
        return result

    @staticmethod
    async def _read_ranked_posts_tx(
        tx: AsyncManagedTransaction,
        agent_id: str,
        cycle_id: str,
        source_round: int,
        limit: int,
    ) -> list[RankedPost]:
        """Transaction function for reading peer posts ranked by influence weight."""
        result = await tx.run(
            """
            MATCH (p:Post)
            WHERE p.cycle_id = $cycle_id AND p.round_num = $source_round
              AND p.agent_id <> $agent_id
              AND p.signal <> 'parse_error'
            WITH p
            MATCH (author:Agent {id: p.agent_id})
            OPTIONAL MATCH (reader:Agent {id: $agent_id})-[infl:INFLUENCED_BY {cycle_id: $cycle_id, round: $source_round}]->(author)
            RETURN p.post_id AS post_id,
                   p.agent_id AS agent_id,
                   author.bracket AS bracket,
                   p.signal AS signal,
                   p.confidence AS confidence,
                   p.content AS content,
                   p.round_num AS round_num,
                   coalesce(infl.weight, author.influence_weight_base) AS influence_weight
            ORDER BY influence_weight DESC
            LIMIT $limit
            """,
            agent_id=agent_id,
            cycle_id=cycle_id,
            source_round=source_round,
            limit=limit,
        )
        records = [r async for r in result]
        return [
            RankedPost(
                post_id=r["post_id"],
                agent_id=r["agent_id"],
                bracket=r["bracket"],
                signal=r["signal"],
                confidence=r["confidence"],
                content=r["content"],
                influence_weight=r["influence_weight"],
                round_num=r["round_num"],
            )
            for r in records
        ]

    async def write_read_post_edges(
        self,
        agent_ids: list[str],
        post_ids: list[str],
        round_num: int,
        cycle_id: str,
    ) -> None:
        """Batch-write READ_POST edges: every agent -> all posts (SOCIAL-02).

        Creates N_agents * N_posts edges in a single UNWIND transaction.
        Semantics: agent had access to this post during this round.
        """
        if not agent_ids or not post_ids:
            return
        pairs = [
            {"agent_id": aid, "post_id": pid}
            for aid in agent_ids
            for pid in post_ids
        ]
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(
                    self._batch_write_read_post_edges_tx, pairs, round_num, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to write {len(pairs)} READ_POST edges for cycle {cycle_id} round {round_num}",
                original_error=exc,
            ) from exc
        self._log.info(
            "read_post_edges_written",
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(pairs),
        )

    @staticmethod
    async def _batch_write_read_post_edges_tx(
        tx: AsyncManagedTransaction,
        pairs: list[dict],  # type: ignore[type-arg]
        round_num: int,
        cycle_id: str,
    ) -> None:
        """UNWIND batch create READ_POST edges from Agent to Post."""
        await tx.run(
            """
            UNWIND $pairs AS pair
            MATCH (a:Agent {id: pair.agent_id})
            MATCH (p:Post {post_id: pair.post_id})
            CREATE (a)-[:READ_POST {round_num: $round_num, cycle_id: $cycle_id}]->(p)
            """,
            pairs=pairs,
            round_num=round_num,
            cycle_id=cycle_id,
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
    # Phase 11: RationaleEpisode writes, entity reads, narrative writes
    # ------------------------------------------------------------------

    async def write_rationale_episodes(
        self,
        records: list,  # list of EpisodeRecord or dicts with same fields
    ) -> None:
        """Batch-write RationaleEpisode nodes linked to Decision via HAS_EPISODE (D-04, D-07).

        Called by WriteBuffer.flush() after write_decisions() ensures Decision nodes exist.
        Single UNWIND transaction for all episodes in the batch.
        """
        if not records:
            return
        episodes = [
            {
                "decision_id": r.decision_id if hasattr(r, "decision_id") else r["decision_id"],
                "rationale": r.rationale if hasattr(r, "rationale") else r["rationale"],
                "peer_context_received": (
                    r.peer_context_received if hasattr(r, "peer_context_received") else r["peer_context_received"]
                ),
                "flip_type": r.flip_type if hasattr(r, "flip_type") else r["flip_type"],
                "round_num": r.round_num if hasattr(r, "round_num") else r["round_num"],
                "cycle_id": r.cycle_id if hasattr(r, "cycle_id") else r["cycle_id"],
            }
            for r in records
        ]
        cycle_id = episodes[0]["cycle_id"]
        round_num = episodes[0]["round_num"]
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(
                    self._batch_write_episodes_tx, episodes, cycle_id, round_num,
                )
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to write {len(episodes)} rationale episodes for cycle {cycle_id} round {round_num}",
                original_error=exc,
            ) from exc
        self._log.info(
            "episodes_written", cycle_id=cycle_id, round_num=round_num, count=len(episodes),
        )

    @staticmethod
    async def _batch_write_episodes_tx(
        tx: AsyncManagedTransaction,
        episodes: list[dict],  # type: ignore[type-arg]
        cycle_id: str,
        round_num: int,
    ) -> None:
        """UNWIND batch create RationaleEpisode nodes linked to Decision nodes."""
        await tx.run(
            """
            UNWIND $episodes AS ep
            MATCH (d:Decision {decision_id: ep.decision_id})
            CREATE (re:RationaleEpisode {
                rationale: ep.rationale,
                timestamp: datetime(),
                peer_context_received: ep.peer_context_received,
                flip_type: ep.flip_type,
                round: $round_num,
                cycle_id: $cycle_id
            })
            CREATE (d)-[:HAS_EPISODE]->(re)
            """,
            episodes=episodes,
            cycle_id=cycle_id,
            round_num=round_num,
        )

    async def write_narrative_edges(
        self,
        records: list,  # list of EpisodeRecord or dicts
        entity_names: list[str],
    ) -> None:
        """Create REFERENCES edges between Decision and Entity nodes (D-08, D-09).

        Python-side case-insensitive substring matching determines which decisions
        reference which entities. Matched pairs are then written via UNWIND.
        Entity names are passed as ORIGINAL casing (not lowercased) to match
        Entity nodes in Neo4j (Pitfall 4).
        """
        if not records or not entity_names:
            return
        # Python-side matching (avoids N*M Cypher cross-product)
        matches: list[dict] = []  # type: ignore[type-arg]
        for r in records:
            rationale = (r.rationale if hasattr(r, "rationale") else r["rationale"]).lower()
            decision_id = r.decision_id if hasattr(r, "decision_id") else r["decision_id"]
            for name in entity_names:
                if name.lower() in rationale:
                    matches.append({"decision_id": decision_id, "entity_name": name})
        if not matches:
            self._log.debug("no_entity_matches", record_count=len(records), entity_count=len(entity_names))
            return
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(self._batch_write_references_tx, matches)
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to write {len(matches)} REFERENCES edges",
                original_error=exc,
            ) from exc
        self._log.info("references_written", match_count=len(matches))

    @staticmethod
    async def _batch_write_references_tx(
        tx: AsyncManagedTransaction,
        matches: list[dict],  # type: ignore[type-arg]
    ) -> None:
        """UNWIND batch create REFERENCES edges from Decision to Entity."""
        await tx.run(
            """
            UNWIND $matches AS m
            MATCH (d:Decision {decision_id: m.decision_id})
            MATCH (e:Entity {name: m.entity_name})
            CREATE (d)-[:REFERENCES {match_type: "substring"}]->(e)
            """,
            matches=matches,
        )

    async def read_cycle_entities(self, cycle_id: str) -> list[str]:
        """Read entity names for a cycle. Loaded once at cycle start, cached by caller (D-09).

        Returns entity names in their ORIGINAL casing (same as stored during seed injection).
        Callers must NOT lowercase these names; they are used as-is in MATCH clauses.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                """
                MATCH (c:Cycle {cycle_id: $cycle_id})-[:MENTIONS]->(e:Entity)
                RETURN e.name AS name
                """,
                cycle_id=cycle_id,
            )
            return [record["name"] async for record in result]

    async def write_decision_narratives(
        self,
        narratives: list[dict],  # [{"agent_id": str, "narrative": str}]
    ) -> None:
        """Batch-write decision_narrative property to Agent nodes (D-10).

        Args:
            narratives: List of {"agent_id": str, "narrative": str} dicts.
        """
        if not narratives:
            return
        try:
            async with self._driver.session(database=self._database) as session:
                await session.execute_write(self._batch_write_narratives_tx, narratives)
        except Neo4jError as exc:
            raise Neo4jWriteError(
                f"Failed to write {len(narratives)} decision narratives",
                original_error=exc,
            ) from exc
        self._log.info("narratives_written", count=len(narratives))

    @staticmethod
    async def _batch_write_narratives_tx(
        tx: AsyncManagedTransaction,
        narratives: list[dict],  # type: ignore[type-arg]
    ) -> None:
        """UNWIND batch SET decision_narrative on Agent nodes."""
        await tx.run(
            """
            UNWIND $narratives AS n
            MATCH (a:Agent {id: n.agent_id})
            SET a.decision_narrative = n.narrative
            """,
            narratives=narratives,
        )

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

    # ------------------------------------------------------------------
    # Phase 14: Interview context reads
    # ------------------------------------------------------------------

    async def read_agent_interview_context(
        self, agent_id: str, cycle_id: str,
    ) -> InterviewContext:
        """Read agent context for post-simulation interview (INT-01, D-04, D-06).

        Reconstructs InterviewContext from Neo4j Agent + Decision nodes and
        the in-memory persona list for system_prompt lookup.

        Args:
            agent_id: The agent to interview.
            cycle_id: The simulation cycle to pull decisions from.

        Returns:
            InterviewContext with persona, narrative, and per-round decisions.

        Raises:
            Neo4jConnectionError: When Neo4j query fails.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_interview_context_tx, agent_id, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read interview context for agent {agent_id} cycle {cycle_id}",
                original_error=exc,
            ) from exc

        # Look up persona from in-memory list (D-06: avoids second Neo4j query)
        persona = next((p for p in self._personas if p.id == agent_id), None)
        interview_system_prompt = (
            _strip_json_instructions(persona.system_prompt) if persona else ""
        )

        # Extract agent-level fields from first record
        first = records[0] if records else {}
        agent_name = first.get("name", "")
        bracket = first.get("bracket", "")
        decision_narrative = first.get("decision_narrative") or ""

        # Build per-round decisions (skip records with no round_num, e.g. OPTIONAL MATCH miss)
        decisions = [
            RoundDecision(
                round_num=r["round_num"],
                signal=r["signal"],
                confidence=r["confidence"],
                sentiment=r["sentiment"],
                rationale=r["rationale"],
            )
            for r in records
            if r.get("round_num") is not None
        ]

        self._log.debug(
            "interview_context_read",
            agent_id=agent_id,
            cycle_id=cycle_id,
            decision_count=len(decisions),
        )

        return InterviewContext(
            agent_id=agent_id,
            agent_name=agent_name,
            bracket=bracket,
            interview_system_prompt=interview_system_prompt,
            decision_narrative=decision_narrative,
            decisions=decisions,
        )

    @staticmethod
    async def _read_interview_context_tx(
        tx: AsyncManagedTransaction,
        agent_id: str,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for reading agent interview context."""
        result = await tx.run(
            """
            MATCH (a:Agent {id: $agent_id})
            OPTIONAL MATCH (a)-[:MADE]->(d:Decision)
            WHERE d.cycle_id = $cycle_id
            RETURN a.id AS agent_id,
                   a.name AS name,
                   a.bracket AS bracket,
                   a.decision_narrative AS decision_narrative,
                   d.round AS round_num,
                   d.signal AS signal,
                   d.confidence AS confidence,
                   d.sentiment AS sentiment,
                   d.rationale AS rationale
            ORDER BY d.round
            """,
            agent_id=agent_id,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    # ------------------------------------------------------------------
    # Phase 15: Report query tools
    # ------------------------------------------------------------------

    async def read_consensus_summary(self, cycle_id: str) -> dict:  # type: ignore[type-arg]
        """Count BUY/SELL/HOLD decisions in Round 3 for cycle (REPORT-02).

        Returns plain dict for JSON-serializable ToolObservation.result.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                record = await session.execute_read(
                    self._read_consensus_summary_tx, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read consensus summary for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug(
            "report_consensus_summary", cycle_id=cycle_id,
        )
        return record

    @staticmethod
    async def _read_consensus_summary_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> dict:  # type: ignore[type-arg]
        """Transaction function for consensus summary Cypher."""
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: 3})
            RETURN
                sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
                sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
                sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_count,
                count(d) AS total
            """,
            cycle_id=cycle_id,
        )
        record = await result.single()
        return dict(record) if record else {"buy_count": 0, "sell_count": 0, "hold_count": 0, "total": 0}

    async def read_round_timeline(self, cycle_id: str) -> list[dict]:  # type: ignore[type-arg]
        """Return per-round BUY/SELL/HOLD counts across all agents (REPORT-02).

        Returns list ordered by round_num ascending.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_round_timeline_tx, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read round timeline for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_round_timeline", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_round_timeline_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for per-round signal breakdown."""
        result = await tx.run(
            """
            MATCH (d:Decision {cycle_id: $cycle_id})
            RETURN
                d.round AS round_num,
                sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
                sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
                sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_count,
                count(d) AS total
            ORDER BY d.round
            """,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict]:  # type: ignore[type-arg]
        """Return per-bracket signal stance and confidence for Round 3 (REPORT-02).

        Returns list ordered by bracket name.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_bracket_narratives_tx, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read bracket narratives for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_bracket_narratives", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_bracket_narratives_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for per-bracket stance summary."""
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: 3})
            RETURN
                a.bracket AS bracket,
                sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
                sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
                sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_count,
                avg(d.confidence) AS avg_confidence,
                avg(d.sentiment) AS avg_sentiment
            ORDER BY bracket
            """,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    async def read_key_dissenters(self, cycle_id: str) -> list[dict]:  # type: ignore[type-arg]
        """Find agents whose Round 3 signal differs from their bracket majority (REPORT-02).

        Returns list of dissenters with agent_id, name, bracket, signal, bracket_majority.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_key_dissenters_tx, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read key dissenters for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_key_dissenters", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_key_dissenters_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for finding dissenters vs bracket majority."""
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: 3})
            WITH a.bracket AS bracket,
                 collect({agent_id: a.id, name: a.name, signal: d.signal}) AS agents,
                 sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
                 sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
                 sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_count
            WITH bracket, agents,
                 CASE
                   WHEN buy_count >= sell_count AND buy_count >= hold_count THEN 'BUY'
                   WHEN sell_count >= buy_count AND sell_count >= hold_count THEN 'SELL'
                   ELSE 'HOLD'
                 END AS bracket_majority
            UNWIND agents AS ag
            WITH bracket, bracket_majority, ag
            WHERE ag.signal <> bracket_majority
            RETURN
                ag.agent_id AS agent_id,
                ag.name AS name,
                bracket AS bracket,
                ag.signal AS signal,
                bracket_majority AS bracket_majority
            ORDER BY bracket, agent_id
            """,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    async def read_influence_leaders(
        self, cycle_id: str, limit: int = 10,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Return top agents by cumulative INFLUENCED_BY weight in Round 3 (REPORT-02).

        Filters to round=3 to avoid double-counting across rounds (Pitfall 1).

        Args:
            cycle_id: Simulation cycle ID.
            limit: Maximum number of leaders to return (default 10).

        Returns:
            List of dicts with agent_id, name, bracket, total_influence_weight, citation_count.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_influence_leaders_tx, cycle_id, limit,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read influence leaders for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_influence_leaders", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_influence_leaders_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        limit: int,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for top influence leaders by edge weight."""
        result = await tx.run(
            """
            MATCH (src:Agent)-[infl:INFLUENCED_BY {cycle_id: $cycle_id, round: 3}]->(tgt:Agent)
            RETURN
                tgt.id AS agent_id,
                tgt.name AS name,
                tgt.bracket AS bracket,
                sum(infl.weight) AS total_influence_weight,
                count(src) AS citation_count
            ORDER BY total_influence_weight DESC
            LIMIT $limit
            """,
            cycle_id=cycle_id,
            limit=limit,
        )
        return [dict(record) async for record in result]

    async def read_signal_flips(self, cycle_id: str) -> list[dict]:  # type: ignore[type-arg]
        """Return agents who changed position between rounds (REPORT-02).

        Uses RationaleEpisode.flip_type from Phase 11.
        Filters out NONE flip_type using string comparison (Pitfall 2).

        Returns:
            List of dicts with agent_id, name, bracket, round_num, flip_type, final_signal.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_signal_flips_tx, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read signal flips for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_signal_flips", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_signal_flips_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for signal flip episodes."""
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
            MATCH (d)-[:HAS_EPISODE]->(re:RationaleEpisode)
            WHERE re.flip_type <> 'NONE'
            RETURN
                a.id AS agent_id,
                a.name AS name,
                a.bracket AS bracket,
                re.round_num AS round_num,
                re.flip_type AS flip_type,
                d.signal AS final_signal
            ORDER BY re.round_num, a.bracket
            """,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    async def read_entity_impact(self, cycle_id: str) -> list[dict]:  # type: ignore[type-arg]
        """Return per-entity sentiment aggregation via REFERENCES edges (REPORT-02).

        Uses REFERENCES edges created by Phase 11 write_narrative_edges().

        Returns:
            List of dicts with entity_name, entity_type, avg_sentiment, mention_count,
            buy_mentions, sell_mentions, hold_mentions.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_entity_impact_tx, cycle_id,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read entity impact for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_entity_impact", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_entity_impact_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for entity-level sentiment aggregation."""
        result = await tx.run(
            """
            MATCH (d:Decision {cycle_id: $cycle_id})-[:REFERENCES]->(e:Entity)
            RETURN
                e.name AS entity_name,
                e.type AS entity_type,
                avg(d.sentiment) AS avg_sentiment,
                count(d) AS mention_count,
                sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_mentions,
                sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_mentions,
                sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_mentions
            ORDER BY mention_count DESC
            """,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    async def read_social_post_reach(
        self, cycle_id: str, limit: int = 10,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Return top posts by READ_POST edge count for the cycle (REPORT-02).

        Uses READ_POST edges created by Phase 12 write_read_post_edges().

        Args:
            cycle_id: Simulation cycle ID.
            limit: Maximum number of posts to return (default 10).

        Returns:
            List of dicts with post_id, author_name, bracket, signal, round_num,
            content, reader_count.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                records = await session.execute_read(
                    self._read_social_post_reach_tx, cycle_id, limit,
                )
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Failed to read social post reach for cycle {cycle_id}",
                original_error=exc,
            ) from exc
        self._log.debug("report_social_post_reach", cycle_id=cycle_id, count=len(records))
        return records

    @staticmethod
    async def _read_social_post_reach_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        limit: int,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction function for top posts by reader count."""
        result = await tx.run(
            """
            MATCH (a:Agent)-[:READ_POST {cycle_id: $cycle_id}]->(p:Post)
            WITH p, count(a) AS reader_count
            MATCH (author:Agent {id: p.agent_id})
            RETURN
                p.post_id AS post_id,
                author.name AS author_name,
                author.bracket AS bracket,
                p.signal AS signal,
                p.round_num AS round_num,
                p.content AS content,
                reader_count
            ORDER BY reader_count DESC
            LIMIT $limit
            """,
            cycle_id=cycle_id,
            limit=limit,
        )
        return [dict(record) async for record in result]

    async def read_latest_cycle_id(self) -> str | None:
        """Return the most recent cycle_id from Neo4j, or None if no cycles exist.

        Used by CLI `--cycle` flag default: `alphaswarm report` without explicit cycle.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(
                    "MATCH (c:Cycle) RETURN c.cycle_id AS cycle_id ORDER BY c.created_at DESC LIMIT 1",
                )
                record = await result.single()
                return str(record["cycle_id"]) if record else None
        except Neo4jError as exc:
            raise Neo4jConnectionError(
                "Failed to read latest cycle_id",
                original_error=exc,
            ) from exc
