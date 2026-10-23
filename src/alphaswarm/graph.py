"""Neo4j graph state management for AlphaSwarm consensus cycles."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict, TypeVar, cast, get_args

import structlog
from neo4j import unit_of_work
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import DriverError, Neo4jError

from alphaswarm.config import DEFAULT_BRACKETS
from alphaswarm.episodes import EntityRef
from alphaswarm.errors import (
    GraphError,
    Neo4jQueryError,
    Neo4jUnavailableError,
    Neo4jWriteError,
)
from alphaswarm.interview import InterviewContext, RoundDecision, _strip_json_instructions
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from neo4j import AsyncDriver, AsyncManagedTransaction

    from alphaswarm.episodes import EntityMatch, EpisodeRecord
    from alphaswarm.errors import RunErrorCode
    from alphaswarm.state import AgentState
    from alphaswarm.types import AgentDecision, AgentPersona, SeedEvent

log = structlog.get_logger(component="graph")

T = TypeVar("T")

# neo4j 5.x raises a pool-acquisition timeout as a code-less ClientError
# (6.0 plans to make it a DriverError).
_POOL_ACQUISITION_TIMEOUT_MARKER: Final = "failed to obtain a connection from the pool"


def _map_graph_error(exc: Exception, *, op: str, write: bool) -> GraphError:
    """Map a neo4j driver/server error onto the GraphError family.

    ServiceUnavailable and SessionExpired subclass DriverError, not
    Neo4jError; a wrong password is neo4j's AuthError (a ClientError); a
    pool-acquisition timeout is a code-less ClientError. All three mean the
    database is unreachable (docs/DECISIONS.md#p4-d-07).
    """
    unavailable = isinstance(exc, (DriverError, Neo4jAuthError)) or (
        isinstance(exc, Neo4jError) and exc.code is None and _POOL_ACQUISITION_TIMEOUT_MARKER in str(exc)
    )
    if unavailable:
        return Neo4jUnavailableError(f"Neo4j is unavailable ({op})", exc, op=op)
    if write:
        return Neo4jWriteError(f"Neo4j write failed ({op})", exc, op=op)
    return Neo4jQueryError(f"Neo4j query failed ({op})", exc, op=op)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class PersistRoundResult:
    """What one persist_round transaction wrote (docs/DECISIONS.md#p4-d-08)."""

    decision_ids: tuple[str, ...]
    decisions_written: int
    episodes_written: int
    citations_written: int
    citations_dropped: int  # CITED targets that matched no Agent -> r{n}_citations_dropped
    references_written: int


# ---------------------------------------------------------------------------
# Read-model rows returned by the read_* queries. Templates and consumers read
# only these keys; mypy catches drift (docs/DECISIONS.md#adr-report-react).
# ---------------------------------------------------------------------------


class ConsensusSummaryRow(TypedDict):
    """Final-round counts; total = buy + sell + hold + parse_error."""

    buy_count: int
    sell_count: int
    hold_count: int
    parse_error_count: int
    total: int


class RoundTimelineRow(TypedDict):
    round_num: int
    buy_count: int
    sell_count: int
    hold_count: int
    parse_error_count: int
    total: int


class BracketNarrativeRow(TypedDict):
    """Final-round stance per bracket; totals and averages exclude parse errors."""

    bracket: str
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float
    majority: str | None


class KeyDissenterRow(TypedDict):
    agent_id: str
    name: str
    bracket: str
    signal: str
    bracket_majority: str


class InfluenceLeaderRow(TypedDict):
    agent_id: str
    name: str
    bracket: str
    citation_count: int
    influence_share: float


class SignalFlipRow(TypedDict):
    agent_id: str
    name: str
    bracket: str
    round_num: int
    flip_type: str
    final_signal: str


class EntityImpactRow(TypedDict):
    entity_name: str
    entity_type: str
    avg_sentiment: float
    mention_count: int
    buy_mentions: int
    sell_mentions: int
    hold_mentions: int


class ShockImpactRow(TypedDict):
    """bracket_pivots entries: bracket, display_name, comparable, pivots,
    pre_dominant, post_dominant, pre_buy_pct, post_buy_pct, delta_buy_pct,
    dominant_arrow, agents (list of {agent_id, pre_signal, post_signal})."""

    shock_text: str
    injected_before_round: int
    pre_dominant: str | None
    post_dominant: str | None
    pivot_count: int
    pivot_rate: float
    bracket_pivots: list[dict[str, object]]


class InfluenceEdgeRow(TypedDict):
    source_id: str  # citing agent
    target_id: str  # cited agent
    weight: float


class CompletedCycleRow(TypedDict):
    """One complete cycle with the run metrics stamped on its Cycle node.

    Metric columns are None for cycles recorded before metrics existed
    (docs/DECISIONS.md#adr-cycle-metrics).
    """

    cycle_id: str
    created_at: str
    seed_rumor: str
    round_count: int
    status: str
    final_buy: int | None
    final_sell: int | None
    final_hold: int | None
    total_flips: int | None
    total_seconds: float | None
    agent_count: int | None


class AgentDecisionRow(TypedDict):
    """One stored decision of one agent; signal is lowercase."""

    round_num: int
    signal: str
    confidence: float
    sentiment: float
    rationale: str
    cited_agents: list[str]


class BracketRoundRow(TypedDict):
    """Replay per-round bracket row; totals and averages exclude parse errors."""

    bracket: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float


class RationaleRoundRow(TypedDict):
    agent_id: str
    signal: str
    rationale: str
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
    "CREATE CONSTRAINT shock_id_unique IF NOT EXISTS FOR (se:ShockEvent) REQUIRE se.shock_id IS UNIQUE",
    "CREATE INDEX cycle_status IF NOT EXISTS FOR (c:Cycle) ON (c.status)",
]

CycleStatus = Literal["running", "complete", "failed", "cancelled"]

# Completion rule for cycles written before Cycle.status existed
# (docs/DECISIONS.md#adr-cycle-metrics): metrics stamped, or a round-3 decision.
_LEGACY_COMPLETE: Final = (
    "(c.metrics_recorded_at IS NOT NULL OR EXISTS { "
    "MATCH (:Agent)-[:MADE]->(:Decision {cycle_id: c.cycle_id, round: 3}) })"
)
# The status a reader assumes: the stored one, else the legacy rule, so the
# readers are right even before ensure_schema() has back-filled.
_EFFECTIVE_STATUS: Final = f"coalesce(c.status, CASE WHEN {_LEGACY_COMPLETE} THEN 'complete' ELSE 'failed' END)"
# ensure_schema() stamps the same rule onto status-less cycles; SET-only, idempotent.
CYCLE_STATUS_BACKFILL: Final = (
    "MATCH (c:Cycle) WHERE c.status IS NULL "
    f"SET c.status = CASE WHEN {_LEGACY_COMPLETE} THEN 'complete' ELSE 'failed' END "
    "RETURN count(c) AS backfilled"
)

# One completeness rule for every reader: the stored Cycle.status, else the
# legacy predicate (metrics stamped, or a round-3 decision), so the job routes and
# read_completed_cycles never disagree about a cycle (docs/DECISIONS.md#adr-cycle-metrics).
_CYCLE_STATUS_QUERY: Final = f"MATCH (c:Cycle {{cycle_id: $cycle_id}}) RETURN {_EFFECTIVE_STATUS} AS status"
_CYCLE_STATUSES: Final[frozenset[str]] = frozenset(get_args(CycleStatus))

# persist_round's four statements, run in one transaction (docs/DECISIONS.md#p4-d-08).
_PERSIST_DECISIONS: Final = """
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
    rationale: d.rationale,
    control: d.control,
    error_kind: d.error_kind
})
CREATE (a)-[:MADE]->(dec)
CREATE (dec)-[:FOR]->(c)
RETURN count(dec) AS created
"""

# OPTIONAL MATCH + FOREACH: a citation of an unknown agent id is reported
# back (written = false) instead of silently matching nothing.
_PERSIST_CITATIONS: Final = """
UNWIND $cited AS c
MATCH (dec:Decision {decision_id: c.decision_id})
OPTIONAL MATCH (agent:Agent {id: c.cited_id})
FOREACH (ignored IN CASE WHEN agent IS NULL THEN [] ELSE [1] END |
    CREATE (dec)-[:CITED]->(agent))
RETURN c.cited_id AS cited_id, agent IS NOT NULL AS written
"""

_PERSIST_EPISODES: Final = """
UNWIND $episodes AS ep
MATCH (d:Decision {decision_id: ep.decision_id})
CREATE (re:RationaleEpisode {
    rationale: ep.rationale,
    timestamp: datetime(),
    peer_context_received: ep.peer_context_received,
    flip_type: ep.flip_type,
    round: ep.round_num,
    cycle_id: ep.cycle_id
})
CREATE (d)-[:HAS_EPISODE]->(re)
RETURN count(re) AS n
"""

# Name-only MATCH keeps the baseline semantics (docs/DECISIONS.md#p11-d-08).
_PERSIST_REFERENCES: Final = """
UNWIND $matches AS m
MATCH (d:Decision {decision_id: m.decision_id})
MATCH (e:Entity {name: m.entity_name})
CREATE (d)-[:REFERENCES {match_type: m.match_type}]->(e)
RETURN count(*) AS n
"""

# Bracket display names and order come from config so report rows match the
# live frame (simulation.compute_bracket_summaries) — docs/DECISIONS.md#adr-swarm-composition-v2.
_BRACKET_DISPLAY_NAMES: Final[dict[str, str]] = {b.bracket_type.value: b.display_name for b in DEFAULT_BRACKETS}
_BRACKET_ORDER: Final[dict[str, int]] = {b.bracket_type.value: i for i, b in enumerate(DEFAULT_BRACKETS)}


def _bracket_sort_key(bracket: str) -> tuple[int, str]:
    """Config order first; unknown (legacy) brackets last, alphabetically."""
    return (_BRACKET_ORDER.get(bracket, len(_BRACKET_ORDER)), bracket)


def _majority(signals: Sequence[str]) -> str | None:
    """Most common of BUY/SELL/HOLD; ties BUY > SELL > HOLD; None when empty."""
    counts = {sig: 0 for sig in ("BUY", "SELL", "HOLD")}
    for signal in signals:
        if signal in counts:
            counts[signal] += 1
    if not any(counts.values()):
        return None
    best = max(counts.values())
    return next(sig for sig in ("BUY", "SELL", "HOLD") if counts[sig] == best)


def _iso(value: object) -> str:
    """neo4j DateTime or datetime -> ISO-8601 string (CompletedCycleRow.created_at)."""
    iso_format = getattr(value, "iso_format", None)
    if callable(iso_format):
        return str(iso_format())
    if isinstance(value, datetime):
        return value.isoformat()
    return "" if value is None else str(value)


def _as_utc(value: datetime | None) -> datetime | None:
    """Read a naive cursor as UTC.

    Cycle.created_at is a zoned DateTime; Neo4j compares it with a naive
    (LocalDateTime) parameter as null, which would silently return no rows.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _opt_int(value: object) -> int | None:
    """None stays None (metric not recorded); a stored number becomes an int."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


def _opt_float(value: object) -> float | None:
    """None stays None (metric not recorded); a stored number becomes a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


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
        *,
        query_timeout_s: float | None = None,
    ) -> None:
        self._driver = driver
        self._personas = personas
        self._database = database
        self._query_timeout_s = query_timeout_s
        self._log = structlog.get_logger(component="graph")

    def _unit(self, fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """Attach the server-side transaction timeout, when one is configured."""
        if self._query_timeout_s is None:
            return fn
        return unit_of_work(timeout=self._query_timeout_s)(fn)

    async def _read(self, fn: Callable[..., Awaitable[T]], *args: Any, op: str) -> T:
        """Run *fn* in a managed read transaction on a fresh session.

        The only place (with _write and ensure_schema's DDL) that opens a
        session; driver errors leave as GraphError (docs/DECISIONS.md#p4-d-07).
        """
        try:
            async with self._driver.session(database=self._database) as session:
                return await session.execute_read(self._unit(fn), *args)
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op=op, write=False) from exc

    async def _write(self, fn: Callable[..., Awaitable[T]], *args: Any, op: str) -> T:
        """Run *fn* in a managed write transaction on a fresh session."""
        try:
            async with self._driver.session(database=self._database) as session:
                return await session.execute_write(self._unit(fn), *args)
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op=op, write=True) from exc

    async def verify_connectivity(self) -> None:
        """Fail fast when the database is unreachable (docs/DECISIONS.md#p4-d-05).

        Raises only GraphError subclasses (Neo4jUnavailableError for driver and
        auth errors); the web lifespan turns them into a not-ready flag.
        """
        try:
            await self._driver.verify_connectivity()
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op="verify_connectivity", write=False) from exc

    async def ensure_schema(self) -> None:
        """Apply idempotent schema constraints and indexes, then seed agents.

        Per D-05: open one session, execute each statement sequentially,
        then seed all agent nodes.
        """
        try:
            async with self._driver.session(database=self._database) as session:
                for stmt in SCHEMA_STATEMENTS:
                    await session.run(stmt)
        except (DriverError, Neo4jError) as exc:
            raise _map_graph_error(exc, op="ensure_schema", write=True) from exc

        self._log.info("schema_applied", statement_count=len(SCHEMA_STATEMENTS))
        backfilled = await self._write(self._backfill_cycle_status_tx, op="backfill_cycle_status")
        if backfilled:
            self._log.info("cycle_status_backfilled", count=backfilled)
        await self.seed_agents(self._personas)

    @staticmethod
    async def _backfill_cycle_status_tx(tx: AsyncManagedTransaction) -> int:
        """Give every status-less (legacy) Cycle a status; idempotent."""
        result = await tx.run(CYCLE_STATUS_BACKFILL)
        record = await result.single()
        return int(record["backfilled"]) if record else 0

    async def set_cycle_status(
        self,
        cycle_id: str,
        status: CycleStatus,
        *,
        error_code: RunErrorCode | None = None,
    ) -> None:
        """Record a lifecycle transition (docs/DECISIONS.md#adr-cycle-metrics).

        ``error_code`` is stored for ``failed`` and removed otherwise.

        Raises:
            Neo4jWriteError: no Cycle has *cycle_id*.
        """
        found = await self._write(
            self._set_cycle_status_tx,
            cycle_id,
            status,
            error_code,
            op="set_cycle_status",
        )
        if not found:
            raise Neo4jWriteError(
                f"Cycle {cycle_id} not found while setting status {status}",
                op="set_cycle_status",
            )
        self._log.info("cycle_status_set", cycle_id=cycle_id, status=status, error_code=error_code)

    @staticmethod
    async def _set_cycle_status_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        status: str,
        error_code: str | None,
    ) -> bool:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            SET c.status = $status, c.error_code = $error_code
            RETURN count(c) AS n
            """,
            cycle_id=cycle_id,
            status=status,
            error_code=error_code,
        )
        record = await result.single()
        return bool(record and record["n"])

    async def seed_agents(self, agents: list[AgentPersona]) -> None:
        """Seed Agent nodes from persona config via UNWIND + MERGE.

        Per D-06: transforms AgentPersona list to flat dicts for Cypher parameters.

        Also prunes STALE agents — nodes whose id is no longer in the
        configured persona roster (e.g. after the v1→v2 bracket taxonomy
        migration) — but ONLY when they carry no historical decisions:
        agents referenced by old cycles are archival and must survive so
        replay/authorship of past cycles stays intact.
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
        current_ids = [a.id for a in agents]

        await self._write(self._seed_agents_tx, agent_params, op="seed_agents")
        pruned = await self._write(self._prune_stale_agents_tx, current_ids, op="prune_stale_agents")

        if pruned:
            self._log.info("stale_agents_pruned", count=pruned)
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

    @staticmethod
    async def _prune_stale_agents_tx(
        tx: AsyncManagedTransaction,
        current_ids: list[str],
    ) -> int:
        """Delete Agent nodes outside the configured roster with no decision history.

        Agents that MADE decisions in past cycles are kept (archival) so old
        cycles retain authorship and remain replayable.
        """
        result = await tx.run(
            """
            MATCH (a:Agent)
            WHERE NOT a.id IN $current_ids
              AND NOT (a)-[:MADE]->(:Decision)
            DETACH DELETE a
            RETURN count(*) AS pruned
            """,
            current_ids=current_ids,
        )
        record = await result.single()
        return int(record["pruned"]) if record else 0

    async def write_cycle_metrics(
        self,
        cycle_id: str,
        metrics: dict[str, float | int | str | bool],
    ) -> None:
        """Persist flat run metrics onto the Cycle node (measurement infra).

        Written once at simulation end: round durations, flip counts,
        parse-error counts, final signal distribution. Every A/B experiment
        (round count, peer diversity, composition) reads these back with a
        single Cypher query instead of scraping logs. Values must be flat
        scalars: int, float, str or bool (a Neo4j property cannot hold null or
        a map).
        """
        await self._write(self._write_cycle_metrics_tx, cycle_id, metrics, op="write_cycle_metrics")
        self._log.info("cycle_metrics_written", cycle_id=cycle_id, keys=len(metrics))

    @staticmethod
    async def _write_cycle_metrics_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        metrics: dict[str, float | int | str | bool],
    ) -> None:
        """SET metrics map onto the Cycle node."""
        await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            SET c += $metrics, c.metrics_recorded_at = datetime()
            """,
            cycle_id=cycle_id,
            metrics=metrics,
        )

    async def read_cycle_seed(self, cycle_id: str) -> str | None:
        """Return the seed_rumor text for a cycle, or None if not found.

        Used by advisory.engine.synthesize so the
        SEED_RUMOR prompt block and the relevance scorer's seed_match term
        operate on the real rumor text instead of an empty string.
        """
        result = await self._read(self._read_cycle_seed_tx, cycle_id, op="read_cycle_seed")
        return result

    @staticmethod
    async def _read_cycle_seed_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> str | None:
        """Transaction function for reading a cycle's seed_rumor."""
        result = await tx.run(
            "MATCH (c:Cycle {cycle_id: $cycle_id}) RETURN c.seed_rumor AS seed_rumor",
            cycle_id=cycle_id,
        )
        record = await result.single()
        if record is None:
            return None
        value = record["seed_rumor"]
        return str(value) if value is not None else None

    async def create_cycle_with_seed_event(
        self,
        seed_rumor: str,
        seed_event: SeedEvent,
        *,
        num_rounds: int,
    ) -> str:
        """Atomically create the Cycle (with num_rounds) and its seed entities.

        Cycle, Entity and MENTIONS are written in one transaction so a failure
        cannot leave an orphan Cycle. `num_rounds` is stamped here so running
        and failed cycles carry it too; report queries resolve the final round
        from it (docs/DECISIONS.md#adr-num-rounds).

        Returns:
            cycle_id: The UUID4 string for the created Cycle.
        """
        if num_rounds < 1:
            raise ValueError(f"num_rounds must be >= 1, got {num_rounds}")
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
        await self._write(
            self._create_cycle_with_entities_tx,
            cycle_id,
            seed_rumor,
            seed_event.overall_sentiment,
            entity_params,
            num_rounds,
            op="create_cycle_with_seed_event",
        )
        self._log.info(
            "cycle_with_seed_event_created",
            cycle_id=cycle_id,
            entity_count=len(entity_params),
            overall_sentiment=seed_event.overall_sentiment,
            num_rounds=num_rounds,
        )
        return cycle_id

    @staticmethod
    async def _create_cycle_with_entities_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        seed_rumor: str,
        overall_sentiment: float,
        entities: list[dict[str, Any]],
        num_rounds: int,
    ) -> None:
        """Single transaction: Cycle (num_rounds, status 'running') then UNWIND Entity + MENTIONS."""
        await tx.run(
            """
            CREATE (c:Cycle {
                cycle_id: $cycle_id,
                seed_rumor: $seed_rumor,
                overall_sentiment: $overall_sentiment,
                created_at: datetime(),
                num_rounds: $num_rounds,
                status: 'running'
            })
            """,
            cycle_id=cycle_id,
            seed_rumor=seed_rumor,
            overall_sentiment=overall_sentiment,
            num_rounds=num_rounds,
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

    async def persist_round(
        self,
        cycle_id: str,
        round_num: int,
        decisions: Sequence[tuple[str, AgentDecision]],
        *,
        decision_ids: Sequence[str],
        episodes: Sequence[EpisodeRecord],
        entity_matches: Sequence[EntityMatch],
        control_ids: Collection[str] = (),
    ) -> PersistRoundResult:
        """Write one round in a single transaction (docs/DECISIONS.md#p4-d-08).

        Decisions (with error_kind), CITED, RationaleEpisodes and REFERENCES
        commit together or not at all. Fewer Decisions or episodes than
        passed raises Neo4jWriteError and rolls the round back; citations of
        unknown agents are counted and logged, never raised. Every Decision
        stores ``control``: true for the agents in ``control_ids`` (the seeded
        no-peer holdout), false otherwise
        (docs/DECISIONS.md#adr-diverse-peer-context).
        """
        if len(decision_ids) != len(decisions):
            raise ValueError(f"decision_ids length {len(decision_ids)} != decisions length {len(decisions)}")
        pairs = list(zip(decision_ids, decisions, strict=True))
        control_set = frozenset(control_ids)
        decision_rows = [
            {
                "decision_id": did,
                "agent_id": agent_id,
                "signal": d.signal.value,
                "confidence": d.confidence,
                "sentiment": d.sentiment,
                "rationale": d.rationale,
                "control": agent_id in control_set,
                "error_kind": d.error_kind,
            }
            for did, (agent_id, d) in pairs
        ]
        cited_rows = [{"decision_id": did, "cited_id": cited} for did, (_, d) in pairs for cited in d.cited_agents]
        episode_rows = [
            {
                "decision_id": e.decision_id,
                "rationale": e.rationale,
                "peer_context_received": e.peer_context_received,
                "flip_type": e.flip_type,
                "round_num": e.round_num,
                "cycle_id": e.cycle_id,
            }
            for e in episodes
        ]
        reference_rows = [
            {"decision_id": m.decision_id, "entity_name": m.entity_name, "match_type": m.match_type}
            for m in entity_matches
        ]
        summary, dropped = await self._write(
            self._persist_round_tx,
            cycle_id,
            round_num,
            decision_rows,
            cited_rows,
            episode_rows,
            reference_rows,
            op="persist_round",
        )
        if dropped:
            self._log.warning(
                "citations_dropped",
                cycle_id=cycle_id,
                round_num=round_num,
                count=len(dropped),
                cited_ids=",".join(sorted(set(dropped))[:20]),
            )
        self._log.info(
            "round_persisted",
            cycle_id=cycle_id,
            round_num=round_num,
            decisions=summary.decisions_written,
            episodes=summary.episodes_written,
            citations=summary.citations_written,
            references=summary.references_written,
        )
        return summary

    @staticmethod
    async def _persist_round_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        round_num: int,
        decisions: list[dict[str, Any]],
        cited: list[dict[str, str]],
        episodes: list[dict[str, Any]],
        references: list[dict[str, str]],
    ) -> tuple[PersistRoundResult, tuple[str, ...]]:
        """Transaction body; raising here rolls the whole round back."""
        result = await tx.run(_PERSIST_DECISIONS, decisions=decisions, cycle_id=cycle_id, round_num=round_num)
        record = await result.single()
        created = int(record["created"]) if record else 0
        if created < len(decisions):
            raise Neo4jWriteError(
                f"persist_round created {created} of {len(decisions)} decisions "
                f"(cycle {cycle_id}, round {round_num}): missing Agent or Cycle node",
                op="persist_round",
            )

        citations_written = 0
        dropped: list[str] = []
        if cited:
            result = await tx.run(_PERSIST_CITATIONS, cited=cited)
            async for row in result:
                if row["written"]:
                    citations_written += 1
                else:
                    dropped.append(str(row["cited_id"]))

        episodes_written = 0
        if episodes:
            result = await tx.run(_PERSIST_EPISODES, episodes=episodes)
            record = await result.single()
            episodes_written = int(record["n"]) if record else 0
            if episodes_written < len(episodes):
                raise Neo4jWriteError(
                    f"persist_round created {episodes_written} of {len(episodes)} episodes "
                    f"(cycle {cycle_id}, round {round_num})",
                    op="persist_round",
                )

        references_written = 0
        if references:
            result = await tx.run(_PERSIST_REFERENCES, matches=references)
            record = await result.single()
            references_written = int(record["n"]) if record else 0

        summary = PersistRoundResult(
            decision_ids=tuple(str(d["decision_id"]) for d in decisions),
            decisions_written=created,
            episodes_written=episodes_written,
            citations_written=citations_written,
            citations_dropped=len(dropped),
            references_written=references_written,
        )
        return summary, tuple(dropped)

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
            decision_ids: The round's decision IDs from persist_round(). Must match
                length of agent_decisions. PARSE_ERROR entries are skipped along with
                their corresponding decision_id.
            cycle_id: Current simulation cycle ID.
            round_num: Current round number (1, 2, or 3).

        Returns:
            list[str]: The post_id strings for each Post written (PARSE_ERROR excluded).
        """
        posts: list[dict] = []  # type: ignore[type-arg]
        post_ids: list[str] = []
        for did, (agent_id, decision) in zip(decision_ids, agent_decisions, strict=True):
            if decision.signal == SignalType.PARSE_ERROR:
                continue
            pid = str(uuid.uuid4())
            post_ids.append(pid)
            posts.append(
                {
                    "post_id": pid,
                    "decision_id": did,
                    "agent_id": agent_id,
                    "content": decision.rationale,
                    "signal": decision.signal.value,
                    "confidence": decision.confidence,
                    "round_num": round_num,
                    "cycle_id": cycle_id,
                }
            )
        if not posts:
            return []
        await self._write(self._batch_write_posts_tx, posts, cycle_id, round_num, op="write_posts")
        self._log.info(
            "posts_written",
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(posts),
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

    # ------------------------------------------------------------------
    # Entity reads and narrative writes
    # ------------------------------------------------------------------

    async def read_cycle_entities(self, cycle_id: str) -> list[EntityRef]:
        """Entities the cycle MENTIONS, in their original casing (docs/DECISIONS.md#p11-d-09).

        Read once per cycle before Round 1; ordered by name, then type.
        """
        return await self._read(self._read_cycle_entities_tx, cycle_id, op="read_cycle_entities")

    @staticmethod
    async def _read_cycle_entities_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[EntityRef]:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})-[:MENTIONS]->(e:Entity)
            RETURN e.name AS name, e.type AS type
            ORDER BY name, type
            """,
            cycle_id=cycle_id,
        )
        return [EntityRef(str(r["name"]), str(r["type"])) async for r in result]

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
        await self._write(self._batch_write_narratives_tx, narratives, op="write_decision_narratives")
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

        if total_agents <= 0:
            # A round in which every agent failed has no denominator
            # (docs/DECISIONS.md#p8-d-01); write nothing.
            self._log.warning(
                "influence_edges_skipped",
                cycle_id=cycle_id,
                up_to_round=up_to_round,
                total_agents=total_agents,
            )
            return {}

        pairs = await self._read(
            self._read_citation_pairs_tx,
            cycle_id,
            up_to_round,
            op="read_citation_pairs",
        )
        if not pairs:
            self._log.info("no_citations_found", cycle_id=cycle_id, up_to_round=up_to_round)
            return {}

        # Per-target citation frequency from deduplicated pairs; weight =
        # citations / active agents (docs/DECISIONS.md#p8-d-01).
        target_counts: Counter[str] = Counter(p["target_id"] for p in pairs)
        weights: dict[str, float] = {agent_id: count / total_agents for agent_id, count in target_counts.items()}
        edges = [
            {
                "source_id": p["source_id"],
                "target_id": p["target_id"],
                "weight": weights[p["target_id"]],
            }
            for p in pairs
        ]
        await self._write(
            self._write_influence_edges_tx,
            edges,
            cycle_id,
            up_to_round,
            op="write_influence_edges",
        )
        self._log.info(
            "influence_edges_computed",
            cycle_id=cycle_id,
            up_to_round=up_to_round,
            edge_count=len(edges),
            agents_with_influence=len(weights),
        )
        return weights

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

    async def read_influence_edges(
        self,
        cycle_id: str,
        round_num: int,
    ) -> list[InfluenceEdgeRow]:
        """Return INFLUENCED_BY edges for a given cycle and round.

        Args:
            cycle_id: Simulation cycle ID.
            round_num: Round number to filter on (1, 2, or 3).

        Returns:
            InfluenceEdgeRow list (source_id, target_id, weight).
        """
        records = await self._read(self._read_influence_edges_tx, cycle_id, round_num, op="read_influence_edges")
        self._log.debug(
            "influence_edges_read",
            cycle_id=cycle_id,
            round=round_num,
            count=len(records),
        )
        return records

    @staticmethod
    async def _read_influence_edges_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        round_num: int,
    ) -> list[InfluenceEdgeRow]:
        """Transaction function for INFLUENCED_BY edges in a given round."""
        result = await tx.run(
            """
            MATCH (src:Agent)-[infl:INFLUENCED_BY {cycle_id: $cycle_id, round: $round_num}]->(tgt:Agent)
            RETURN
                src.id AS source_id,
                tgt.id AS target_id,
                infl.weight AS weight
            """,
            cycle_id=cycle_id,
            round_num=round_num,
        )
        return [
            InfluenceEdgeRow(
                source_id=str(r["source_id"]),
                target_id=str(r["target_id"]),
                weight=float(r["weight"]),
            )
            async for r in result
        ]

    # ------------------------------------------------------------------
    # Phase 14: Interview context reads
    # ------------------------------------------------------------------

    async def read_agent_interview_context(
        self,
        agent_id: str,
        cycle_id: str,
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
            Neo4jQueryError / Neo4jUnavailableError: When the read fails.
        """
        records = await self._read(
            self._read_interview_context_tx, agent_id, cycle_id, op="read_agent_interview_context"
        )

        # Look up persona from in-memory list (D-06: avoids second Neo4j query)
        persona = next((p for p in self._personas if p.id == agent_id), None)
        interview_system_prompt = _strip_json_instructions(persona.system_prompt) if persona else ""

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

    async def read_agent_decisions(self, cycle_id: str, agent_id: str) -> list[AgentDecisionRow]:
        """All of one agent's stored decisions in a cycle, ascending by round.

        Rounds appear as they are persisted, so a running cycle returns the
        rounds finished so far (docs/DECISIONS.md#p14-d-06).

        Raises:
            Neo4jQueryError / Neo4jUnavailableError: When the read fails.
        """
        rows = await self._read(self._read_agent_decisions_tx, cycle_id, agent_id, op="read_agent_decisions")
        self._log.debug(
            "agent_decisions_read",
            cycle_id=cycle_id,
            agent_id=agent_id,
            count=len(rows),
        )
        return rows

    @staticmethod
    async def _read_agent_decisions_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        agent_id: str,
    ) -> list[AgentDecisionRow]:
        """Decisions plus the ids they CITED, one row per round."""
        result = await tx.run(
            """
            MATCH (:Agent {id: $agent_id})-[:MADE]->(d:Decision {cycle_id: $cycle_id})
            OPTIONAL MATCH (d)-[:CITED]->(cited:Agent)
            WITH d, collect(cited.id) AS cited_ids
            RETURN
                d.round AS round_num,
                d.signal AS signal,
                d.confidence AS confidence,
                d.sentiment AS sentiment,
                d.rationale AS rationale,
                cited_ids
            ORDER BY d.round
            """,
            cycle_id=cycle_id,
            agent_id=agent_id,
        )
        return [
            AgentDecisionRow(
                round_num=int(r["round_num"]),
                signal=str(r["signal"]),
                confidence=float(r["confidence"] or 0.0),
                sentiment=float(r["sentiment"] or 0.0),
                rationale=str(r["rationale"] or ""),
                cited_agents=sorted(str(x) for x in r["cited_ids"]),
            )
            async for r in result
        ]

    # ------------------------------------------------------------------
    # Phase 15: Report query tools
    # ------------------------------------------------------------------

    async def read_consensus_summary(self, cycle_id: str) -> ConsensusSummaryRow:
        """Final-round BUY/SELL/HOLD/PARSE_ERROR counts.

        The final round is Cycle.num_rounds (legacy cycles without it: 3),
        resolved inside the query (docs/DECISIONS.md#adr-num-rounds).
        """
        row = await self._read(self._read_consensus_summary_tx, cycle_id, op="read_consensus_summary")
        self._log.debug("report_consensus_summary", cycle_id=cycle_id, total=row["total"])
        return row

    @staticmethod
    async def _read_consensus_summary_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> ConsensusSummaryRow:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            WITH coalesce(c.num_rounds, 3) AS fr
            OPTIONAL MATCH (d:Decision {cycle_id: $cycle_id})
            WHERE d.round = fr
            WITH d, toLower(d.signal) AS s
            RETURN
                sum(CASE WHEN s = 'buy' THEN 1 ELSE 0 END) AS buy_count,
                sum(CASE WHEN s = 'sell' THEN 1 ELSE 0 END) AS sell_count,
                sum(CASE WHEN s = 'hold' THEN 1 ELSE 0 END) AS hold_count,
                sum(CASE WHEN s = 'parse_error' THEN 1 ELSE 0 END) AS parse_error_count,
                count(d) AS total
            """,
            cycle_id=cycle_id,
        )
        record = await result.single()
        if record is None:
            return ConsensusSummaryRow(
                buy_count=0,
                sell_count=0,
                hold_count=0,
                parse_error_count=0,
                total=0,
            )
        return ConsensusSummaryRow(
            buy_count=int(record["buy_count"]),
            sell_count=int(record["sell_count"]),
            hold_count=int(record["hold_count"]),
            parse_error_count=int(record["parse_error_count"]),
            total=int(record["total"]),
        )

    async def read_round_timeline(self, cycle_id: str) -> list[RoundTimelineRow]:
        """Per-round counts for every round that ran, ascending."""
        rows = await self._read(self._read_round_timeline_tx, cycle_id, op="read_round_timeline")
        self._log.debug("report_round_timeline", cycle_id=cycle_id, count=len(rows))
        return rows

    @staticmethod
    async def _read_round_timeline_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[RoundTimelineRow]:
        result = await tx.run(
            """
            MATCH (d:Decision {cycle_id: $cycle_id})
            WITH d.round AS round_num, toLower(d.signal) AS s
            RETURN
                round_num,
                sum(CASE WHEN s = 'buy' THEN 1 ELSE 0 END) AS buy_count,
                sum(CASE WHEN s = 'sell' THEN 1 ELSE 0 END) AS sell_count,
                sum(CASE WHEN s = 'hold' THEN 1 ELSE 0 END) AS hold_count,
                sum(CASE WHEN s = 'parse_error' THEN 1 ELSE 0 END) AS parse_error_count,
                count(*) AS total
            ORDER BY round_num
            """,
            cycle_id=cycle_id,
        )
        return [
            RoundTimelineRow(
                round_num=int(r["round_num"]),
                buy_count=int(r["buy_count"]),
                sell_count=int(r["sell_count"]),
                hold_count=int(r["hold_count"]),
                parse_error_count=int(r["parse_error_count"]),
                total=int(r["total"]),
            )
            async for r in result
        ]

    async def read_bracket_narratives(self, cycle_id: str) -> list[BracketNarrativeRow]:
        """Per-bracket final-round stance in config order.

        Totals and averages exclude PARSE_ERROR; a bracket whose agents all
        failed has total 0 and majority None (never a default BUY).
        """
        rows = await self._read(self._read_bracket_narratives_tx, cycle_id, op="read_bracket_narratives")
        self._log.debug("report_bracket_narratives", cycle_id=cycle_id, count=len(rows))
        return rows

    @staticmethod
    async def _read_bracket_narratives_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[BracketNarrativeRow]:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            WITH coalesce(c.num_rounds, 3) AS fr
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
            WHERE d.round = fr
            WITH a.bracket AS bracket, d, toLower(d.signal) AS s
            WITH bracket,
                 sum(CASE WHEN s = 'buy' THEN 1 ELSE 0 END) AS buy_count,
                 sum(CASE WHEN s = 'sell' THEN 1 ELSE 0 END) AS sell_count,
                 sum(CASE WHEN s = 'hold' THEN 1 ELSE 0 END) AS hold_count,
                 avg(CASE WHEN s <> 'parse_error' THEN d.confidence END) AS avg_confidence,
                 avg(CASE WHEN s <> 'parse_error' THEN d.sentiment END) AS avg_sentiment
            RETURN
                bracket, buy_count, sell_count, hold_count,
                buy_count + sell_count + hold_count AS total,
                coalesce(avg_confidence, 0.0) AS avg_confidence,
                coalesce(avg_sentiment, 0.0) AS avg_sentiment,
                CASE
                    WHEN buy_count + sell_count + hold_count = 0 THEN null
                    WHEN buy_count >= sell_count AND buy_count >= hold_count THEN 'BUY'
                    WHEN sell_count >= hold_count THEN 'SELL'
                    ELSE 'HOLD'
                END AS majority
            """,
            cycle_id=cycle_id,
        )
        rows = [
            BracketNarrativeRow(
                bracket=str(r["bracket"]),
                display_name=_BRACKET_DISPLAY_NAMES.get(str(r["bracket"]), str(r["bracket"])),
                buy_count=int(r["buy_count"]),
                sell_count=int(r["sell_count"]),
                hold_count=int(r["hold_count"]),
                total=int(r["total"]),
                avg_confidence=float(r["avg_confidence"]),
                avg_sentiment=float(r["avg_sentiment"]),
                majority=r["majority"],
            )
            async for r in result
        ]
        return sorted(rows, key=lambda row: _bracket_sort_key(row["bracket"]))

    async def read_key_dissenters(self, cycle_id: str) -> list[KeyDissenterRow]:
        """Agents whose final-round signal differs from their bracket's majority.

        PARSE_ERROR decisions are excluded before the majority is computed, so
        a failed agent is never a dissenter and an all-failed bracket yields none.
        """
        rows = await self._read(self._read_key_dissenters_tx, cycle_id, op="read_key_dissenters")
        self._log.debug("report_key_dissenters", cycle_id=cycle_id, count=len(rows))
        return rows

    @staticmethod
    async def _read_key_dissenters_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[KeyDissenterRow]:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            WITH coalesce(c.num_rounds, 3) AS fr
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
            WHERE d.round = fr AND toLower(d.signal) <> 'parse_error'
            WITH a.bracket AS bracket,
                 collect({agent_id: a.id, name: a.name, signal: toUpper(d.signal)}) AS agents,
                 sum(CASE WHEN toLower(d.signal) = 'buy' THEN 1 ELSE 0 END) AS buy_count,
                 sum(CASE WHEN toLower(d.signal) = 'sell' THEN 1 ELSE 0 END) AS sell_count,
                 sum(CASE WHEN toLower(d.signal) = 'hold' THEN 1 ELSE 0 END) AS hold_count
            WITH bracket, agents,
                 CASE
                     WHEN buy_count >= sell_count AND buy_count >= hold_count THEN 'BUY'
                     WHEN sell_count >= hold_count THEN 'SELL'
                     ELSE 'HOLD'
                 END AS bracket_majority
            UNWIND agents AS ag
            WITH bracket, bracket_majority, ag
            WHERE ag.signal <> bracket_majority
            RETURN ag.agent_id AS agent_id, ag.name AS name, bracket,
                   ag.signal AS signal, bracket_majority
            ORDER BY bracket, agent_id
            """,
            cycle_id=cycle_id,
        )
        return [
            KeyDissenterRow(
                agent_id=str(r["agent_id"]),
                name=str(r["name"]),
                bracket=str(r["bracket"]),
                signal=str(r["signal"]),
                bracket_majority=str(r["bracket_majority"]),
            )
            async for r in result
        ]

    async def read_influence_leaders(
        self,
        cycle_id: str,
        limit: int = 10,
    ) -> list[InfluenceLeaderRow]:
        """Most-cited agents in the final round.

        influence_share = citation_count / N, N = active (non-PARSE_ERROR)
        agents in the final round; this equals the D-01 edge weight and is
        no longer the quadratic sum of incoming weights
        (docs/DECISIONS.md#p8-d-01).
        """
        rows = await self._read(self._read_influence_leaders_tx, cycle_id, limit, op="read_influence_leaders")
        self._log.debug("report_influence_leaders", cycle_id=cycle_id, count=len(rows))
        return rows

    @staticmethod
    async def _read_influence_leaders_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        limit: int,
    ) -> list[InfluenceLeaderRow]:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            WITH coalesce(c.num_rounds, 3) AS fr
            OPTIONAL MATCH (fd:Decision {cycle_id: $cycle_id})
            WHERE fd.round = fr AND toLower(fd.signal) <> 'parse_error'
            WITH fr, count(fd) AS n_active
            MATCH (src:Agent)-[infl:INFLUENCED_BY {cycle_id: $cycle_id}]->(tgt:Agent)
            WHERE infl.round = fr
            WITH tgt, n_active, count(DISTINCT src) AS citation_count
            RETURN
                tgt.id AS agent_id,
                tgt.name AS name,
                tgt.bracket AS bracket,
                citation_count,
                CASE WHEN n_active > 0
                     THEN toFloat(citation_count) / n_active
                     ELSE 0.0 END AS influence_share
            ORDER BY citation_count DESC, agent_id
            LIMIT $limit
            """,
            cycle_id=cycle_id,
            limit=limit,
        )
        return [
            InfluenceLeaderRow(
                agent_id=str(r["agent_id"]),
                name=str(r["name"]),
                bracket=str(r["bracket"]),
                citation_count=int(r["citation_count"]),
                influence_share=float(r["influence_share"]),
            )
            async for r in result
        ]

    async def read_signal_flips(self, cycle_id: str) -> list[SignalFlipRow]:
        """Agents who changed position, from RationaleEpisode.flip_type.

        final_signal is the (uppercase) signal after the flip in that round.
        Rows are ordered by round, bracket, then agent id.
        """
        rows = await self._read(self._read_signal_flips_tx, cycle_id, op="read_signal_flips")
        self._log.debug("report_signal_flips", cycle_id=cycle_id, count=len(rows))
        return rows

    @staticmethod
    async def _read_signal_flips_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[SignalFlipRow]:
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
            MATCH (d)-[:HAS_EPISODE]->(re:RationaleEpisode)
            WHERE re.flip_type <> 'none'
            RETURN
                a.id AS agent_id,
                a.name AS name,
                a.bracket AS bracket,
                re.round AS round_num,
                re.flip_type AS flip_type,
                toUpper(d.signal) AS final_signal
            ORDER BY round_num, bracket, agent_id
            """,
            cycle_id=cycle_id,
        )
        return [
            SignalFlipRow(
                agent_id=str(r["agent_id"]),
                name=str(r["name"]),
                bracket=str(r["bracket"]),
                round_num=int(r["round_num"]),
                flip_type=str(r["flip_type"]),
                final_signal=str(r["final_signal"]),
            )
            async for r in result
        ]

    async def read_entity_impact(self, cycle_id: str) -> list[EntityImpactRow]:
        """Per-entity sentiment over final-round, non-failed decisions.

        Only the cycle's own MENTIONS entities count, so same-name entities
        from other cycles or types cannot leak in (docs/DECISIONS.md#p11-d-08).
        Each decision counts once per entity, even when a seed that listed the
        entity twice left duplicate MENTIONS and REFERENCES edges.
        """
        rows = await self._read(self._read_entity_impact_tx, cycle_id, op="read_entity_impact")
        self._log.debug("report_entity_impact", cycle_id=cycle_id, count=len(rows))
        return rows

    @staticmethod
    async def _read_entity_impact_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[EntityImpactRow]:
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            WITH c, coalesce(c.num_rounds, 3) AS fr
            MATCH (c)-[:MENTIONS]->(e:Entity)<-[:REFERENCES]-(d:Decision {cycle_id: $cycle_id})
            WHERE d.round = fr AND toLower(d.signal) <> 'parse_error'
            WITH DISTINCT e, d
            WITH e, d, toLower(d.signal) AS s
            RETURN
                e.name AS entity_name,
                e.type AS entity_type,
                avg(d.sentiment) AS avg_sentiment,
                count(d) AS mention_count,
                sum(CASE WHEN s = 'buy' THEN 1 ELSE 0 END) AS buy_mentions,
                sum(CASE WHEN s = 'sell' THEN 1 ELSE 0 END) AS sell_mentions,
                sum(CASE WHEN s = 'hold' THEN 1 ELSE 0 END) AS hold_mentions
            ORDER BY mention_count DESC, entity_name, entity_type
            """,
            cycle_id=cycle_id,
        )
        return [
            EntityImpactRow(
                entity_name=str(r["entity_name"]),
                entity_type=str(r["entity_type"]),
                avg_sentiment=float(r["avg_sentiment"]),
                mention_count=int(r["mention_count"]),
                buy_mentions=int(r["buy_mentions"]),
                sell_mentions=int(r["sell_mentions"]),
                hold_mentions=int(r["hold_mentions"]),
            )
            async for r in result
        ]

    async def read_social_post_reach(
        self,
        cycle_id: str,
        limit: int = 10,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Return top posts by READ_POST edge count for the cycle (REPORT-02).

        READ_POST edges are no longer written (docs/DECISIONS.md#hist-read-post),
        so this returns nothing for new cycles.

        Args:
            cycle_id: Simulation cycle ID.
            limit: Maximum number of posts to return (default 10).

        Returns:
            List of dicts with post_id, author_name, bracket, signal, round_num,
            content, reader_count.
        """
        records = await self._read(self._read_social_post_reach_tx, cycle_id, limit, op="read_social_post_reach")
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

    async def read_latest_cycle_id(
        self,
        *,
        statuses: Collection[CycleStatus] = ("complete",),
    ) -> str | None:
        """Most recent cycle whose (effective) status is in *statuses*, or None.

        The default serves `alphaswarm report`, which must never pick a running
        or failed cycle (docs/DECISIONS.md#adr-cycle-metrics).
        """
        wanted = list(statuses)
        if not wanted:
            raise ValueError("statuses must not be empty")
        return await self._read(self._read_latest_cycle_id_tx, wanted, op="read_latest_cycle_id")

    @staticmethod
    async def _read_latest_cycle_id_tx(
        tx: AsyncManagedTransaction,
        statuses: list[str],
    ) -> str | None:
        result = await tx.run(
            f"""
            MATCH (c:Cycle)
            WHERE {_EFFECTIVE_STATUS} IN $statuses
            RETURN c.cycle_id AS cycle_id
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            statuses=statuses,
        )
        record = await result.single()
        return str(record["cycle_id"]) if record else None

    async def read_cycle_status(self, cycle_id: str) -> CycleStatus | None:
        """Lifecycle status of *cycle_id*, or ``None`` when no such cycle exists.

        Job routes gate on this instead of the in-memory phase, which a restart
        resets to idle (docs/DECISIONS.md#adr-background-tasks).
        """
        return await self._read(self._read_cycle_status_tx, cycle_id, op="read_cycle_status")

    async def cycle_exists(self, cycle_id: str) -> bool:
        """True when a Cycle node with *cycle_id* exists, whatever its status."""
        return await self.read_cycle_status(cycle_id) is not None

    @staticmethod
    async def _read_cycle_status_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> CycleStatus | None:
        result = await tx.run(_CYCLE_STATUS_QUERY, cycle_id=cycle_id)
        record = await result.single()
        if record is None:
            return None
        status = str(record["status"])
        if status not in _CYCLE_STATUSES:
            log.warning("cycle_status_unrecognized", cycle_id=cycle_id, status=status)
            return "failed"
        return cast(CycleStatus, status)

    # ------------------------------------------------------------------
    # Phase 27: Shock analysis read methods (Plan 01)
    # ------------------------------------------------------------------

    async def read_shock_event(self, cycle_id: str) -> dict | None:  # type: ignore[type-arg]
        """Return ShockEvent metadata for the cycle, or None if no shock was injected.

        Used by the CLI and web report pipelines to pre-seed the shock-impact
        section when a shock was injected (SHOCK-04).

        Returns:
            Dict with shock_id, shock_text, injected_before_round, created_at,
            or None if no ShockEvent exists for the cycle.
        """
        record = await self._read(self._read_shock_event_tx, cycle_id, op="read_shock_event")
        self._log.debug("read_shock_event", cycle_id=cycle_id)
        return record

    @staticmethod
    async def _read_shock_event_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> dict | None:  # type: ignore[type-arg]
        """Transaction function for shock event read."""
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
            RETURN se.shock_id AS shock_id,
                   se.shock_text AS shock_text,
                   se.injected_before_round AS injected_before_round,
                   se.created_at AS created_at
            LIMIT 1
            """,
            cycle_id=cycle_id,
        )
        record = await result.single()
        return dict(record) if record else None

    async def read_shock_impact(self, cycle_id: str) -> ShockImpactRow:
        """How the swarm moved across the (earliest) shock.

        Compares each agent's decision in the round before the shock with the
        shocked round; agents with a PARSE_ERROR on either side are excluded.
        Zero-filled when the cycle has no shock or no comparable agents.
        """
        row = await self._read(self._read_shock_impact_tx, cycle_id, op="read_shock_impact")
        self._log.debug(
            "read_shock_impact",
            cycle_id=cycle_id,
            pivot_count=row["pivot_count"],
        )
        return row

    @staticmethod
    async def _read_shock_impact_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> ShockImpactRow:
        """Per-agent (pre, post) signals around the earliest shock, failures excluded.

        WHERE shock_round >= 2 guards injected_before_round=1 (there is no round 0).
        """
        result = await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
            WITH se ORDER BY se.injected_before_round ASC LIMIT 1
            WITH se.injected_before_round AS shock_round, se.shock_text AS shock_text
            WHERE shock_round >= 2
            MATCH (a:Agent)-[:MADE]->(pre:Decision {cycle_id: $cycle_id})
            WHERE pre.round = shock_round - 1 AND toLower(pre.signal) <> 'parse_error'
            MATCH (a)-[:MADE]->(post:Decision {cycle_id: $cycle_id})
            WHERE post.round = shock_round AND toLower(post.signal) <> 'parse_error'
            RETURN a.id AS agent_id,
                   a.bracket AS bracket,
                   toUpper(pre.signal) AS pre_signal,
                   toUpper(post.signal) AS post_signal,
                   shock_round,
                   shock_text
            ORDER BY bracket, agent_id
            """,
            cycle_id=cycle_id,
        )
        rows = [dict(r) async for r in result]
        return GraphStateManager._aggregate_shock_impact(rows)

    @staticmethod
    def _aggregate_shock_impact(rows: list[dict[str, Any]]) -> ShockImpactRow:
        """Pure aggregation of per-agent (pre, post) rows into a ShockImpactRow."""
        if not rows:
            return ShockImpactRow(
                shock_text="",
                injected_before_round=0,
                pre_dominant=None,
                post_dominant=None,
                pivot_count=0,
                pivot_rate=0.0,
                bracket_pivots=[],
            )
        by_bracket: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_bracket.setdefault(str(row["bracket"]), []).append(row)
        bracket_pivots: list[dict[str, object]] = []
        for bracket in sorted(by_bracket, key=_bracket_sort_key):
            members = by_bracket[bracket]
            pre = [str(r["pre_signal"]) for r in members]
            post = [str(r["post_signal"]) for r in members]
            pivoted = [r for r in members if r["pre_signal"] != r["post_signal"]]
            pre_buy_pct = pre.count("BUY") / len(members) * 100
            post_buy_pct = post.count("BUY") / len(members) * 100
            delta = post_buy_pct - pre_buy_pct
            bracket_pivots.append(
                {
                    "bracket": bracket,
                    "display_name": _BRACKET_DISPLAY_NAMES.get(bracket, bracket),
                    "comparable": len(members),
                    "pivots": len(pivoted),
                    "pre_dominant": _majority(pre),
                    "post_dominant": _majority(post),
                    "pre_buy_pct": pre_buy_pct,
                    "post_buy_pct": post_buy_pct,
                    "delta_buy_pct": delta,
                    # The arrow glyph stays in the row until the templates own presentation.
                    "dominant_arrow": "▲" if delta > 0 else "▼" if delta < 0 else "·",
                    "agents": [
                        {
                            "agent_id": str(r["agent_id"]),
                            "pre_signal": str(r["pre_signal"]),
                            "post_signal": str(r["post_signal"]),
                        }
                        for r in pivoted
                    ],
                }
            )
        pivot_count = sum(1 for r in rows if r["pre_signal"] != r["post_signal"])
        return ShockImpactRow(
            shock_text=str(rows[0]["shock_text"]),
            injected_before_round=int(rows[0]["shock_round"]),
            pre_dominant=_majority([str(r["pre_signal"]) for r in rows]),
            post_dominant=_majority([str(r["post_signal"]) for r in rows]),
            pivot_count=pivot_count,
            pivot_rate=pivot_count / len(rows),
            bracket_pivots=bracket_pivots,
        )

    # ------------------------------------------------------------------
    # Shock event writer (B1 wiring fix — see docs/DECISIONS.md#b1)
    # ------------------------------------------------------------------

    async def write_shock_event(
        self,
        cycle_id: str,
        shock_text: str,
        injected_before_round: int,
    ) -> str:
        """Create a ShockEvent node and (Cycle)-[:HAS_SHOCK]->(ShockEvent) edge.

        Counterpart to read_shock_event / read_shock_impact (Phase 27).
        Returns the generated shock_id (UUID4 string).

        Args:
            cycle_id: Target cycle; must exist prior to this call.
            shock_text: Raw shock text. The caller caps its length: the web
                route accepts 10-1000 characters (ShockText,
                docs/DECISIONS.md#hist-shock-max-len).
            injected_before_round: 2 or 3 — the round that receives the shock.

        Raises:
            Neo4jWriteError: wraps any underlying Neo4jError.
        """
        shock_id = str(uuid.uuid4())
        await self._write(
            self._write_shock_event_tx, cycle_id, shock_id, shock_text, injected_before_round, op="write_shock_event"
        )
        self._log.info(
            "shock_event_written",
            cycle_id=cycle_id,
            injected_before_round=injected_before_round,
            shock_length=len(shock_text),
        )
        return shock_id

    @staticmethod
    async def _write_shock_event_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        shock_id: str,
        shock_text: str,
        injected_before_round: int,
    ) -> None:
        """Transaction function: CREATE ShockEvent + HAS_SHOCK edge.

        Uses MATCH on Cycle (not MERGE) so a typo'd cycle_id fails loudly.
        All user input flows via parameters — no f-string interpolation (T-35.1-01).
        """
        await tx.run(
            """
            MATCH (c:Cycle {cycle_id: $cycle_id})
            CREATE (se:ShockEvent {
                shock_id: $shock_id,
                shock_text: $shock_text,
                injected_before_round: $injected_before_round,
                created_at: datetime()
            })
            CREATE (c)-[:HAS_SHOCK]->(se)
            """,
            cycle_id=cycle_id,
            shock_id=shock_id,
            shock_text=shock_text,
            injected_before_round=injected_before_round,
        )

    # ------------------------------------------------------------------
    # Phase 28: Simulation replay read methods (Plan 01)
    # ------------------------------------------------------------------

    async def read_full_cycle_signals(self, cycle_id: str) -> dict[tuple[str, int], AgentState]:
        """Load all agent signals for all rounds of a cycle (REPLAY-01, D-08).

        Returns dict keyed by (agent_id, round_num) -> AgentState.
        Uses flat rows (not COLLECT) for optimal index usage on decision_cycle_round.
        Expected cardinality: 300 rows (100 agents x 3 rounds).

        Performance instrumented via time.perf_counter() (Review concern #13).
        Query starts from Decision node for better index usage (Review concern #6).
        """
        import time as _time

        from alphaswarm.state import AgentState as _AgentState

        t0 = _time.perf_counter()
        records = await self._read(self._read_full_cycle_signals_tx, cycle_id, op="read_full_cycle_signals")
        elapsed_ms = (_time.perf_counter() - t0) * 1000
        self._log.debug(
            "read_full_cycle_signals",
            cycle_id=cycle_id,
            count=len(records),
            duration_ms=round(elapsed_ms, 1),
        )
        result: dict[tuple[str, int], _AgentState] = {}
        for row in records:
            agent_id = row["agent_id"]
            round_num = int(row["round_num"])
            signal_str = row["signal"]
            signal = SignalType(signal_str) if signal_str else None
            confidence = float(row["confidence"])
            result[(agent_id, round_num)] = _AgentState(signal=signal, confidence=confidence)
        return result

    @staticmethod
    async def _read_full_cycle_signals_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Transaction: load all Decision rows for a cycle, starting from Decision node (Review #6)."""
        result = await tx.run(
            """
            MATCH (d:Decision {cycle_id: $cycle_id})<-[:MADE]-(a:Agent)
            RETURN
                a.id AS agent_id,
                d.round AS round_num,
                d.signal AS signal,
                d.confidence AS confidence,
                d.sentiment AS sentiment
            ORDER BY d.round, a.id
            """,
            cycle_id=cycle_id,
        )
        return [dict(record) async for record in result]

    async def read_completed_cycles(
        self,
        limit: int = 20,
        *,
        before: datetime | None = None,
    ) -> list[CompletedCycleRow]:
        """Return complete cycles (Cycle.status), newest first, one page at a time.

        *before* is the created_at of the previous page's last row; rows
        strictly older than it are returned. A naive *before* is read as UTC.
        """
        rows: list[CompletedCycleRow] = await self._read(
            self._read_completed_cycles_tx, limit, _as_utc(before), op="read_completed_cycles"
        )
        self._log.debug("completed_cycles_read", count=len(rows), paged=before is not None)
        return rows

    @staticmethod
    async def _read_completed_cycles_tx(
        tx: AsyncManagedTransaction,
        limit: int,
        before: datetime | None,
    ) -> list[CompletedCycleRow]:
        """Complete cycles older than *before* (when set), newest first.

        Completeness is the shared effective-status rule, so this list and the
        job routes never disagree about a cycle. History columns come from the
        metrics map run_simulation stamps on the Cycle node
        (docs/DECISIONS.md#adr-cycle-metrics).
        """
        result = await tx.run(
            f"""
            MATCH (c:Cycle)
            WHERE {_EFFECTIVE_STATUS} = 'complete'
              AND ($before IS NULL OR c.created_at < $before)
            RETURN
                c.cycle_id AS cycle_id,
                c.created_at AS created_at,
                c.seed_rumor AS seed_rumor,
                coalesce(c.num_rounds, 3) AS round_count,
                c.final_buy AS final_buy,
                c.final_sell AS final_sell,
                c.final_hold AS final_hold,
                c.r2_flips + coalesce(c.r3_flips, 0) AS total_flips,
                c.total_seconds AS total_seconds,
                c.agent_count AS agent_count
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
            limit=limit,
            before=before,
        )
        return [
            CompletedCycleRow(
                cycle_id=str(r["cycle_id"]),
                created_at=_iso(r["created_at"]),
                seed_rumor=str(r["seed_rumor"] or ""),
                round_count=int(r["round_count"]),
                status="complete",
                final_buy=_opt_int(r["final_buy"]),
                final_sell=_opt_int(r["final_sell"]),
                final_hold=_opt_int(r["final_hold"]),
                total_flips=_opt_int(r["total_flips"]),
                total_seconds=_opt_float(r["total_seconds"]),
                agent_count=_opt_int(r["agent_count"]),
            )
            async for r in result
        ]

    async def read_bracket_narratives_for_round(
        self,
        cycle_id: str,
        round_num: int,
    ) -> list[BracketRoundRow]:
        """Per-bracket distribution for one round (replay).

        total and averages exclude PARSE_ERROR, matching the live frame's
        compute_bracket_summaries; the replay manager maps display names.
        """
        rows = await self._read(
            self._read_bracket_narratives_for_round_tx, cycle_id, round_num, op="read_bracket_narratives_for_round"
        )
        self._log.debug(
            "read_bracket_narratives_for_round",
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(rows),
        )
        return rows

    @staticmethod
    async def _read_bracket_narratives_for_round_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        round_num: int,
    ) -> list[BracketRoundRow]:
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: $round_num})
            WITH a.bracket AS bracket, d, toLower(d.signal) AS s
            WITH bracket,
                 sum(CASE WHEN s = 'buy' THEN 1 ELSE 0 END) AS buy_count,
                 sum(CASE WHEN s = 'sell' THEN 1 ELSE 0 END) AS sell_count,
                 sum(CASE WHEN s = 'hold' THEN 1 ELSE 0 END) AS hold_count,
                 avg(CASE WHEN s <> 'parse_error' THEN d.confidence END) AS avg_confidence,
                 avg(CASE WHEN s <> 'parse_error' THEN d.sentiment END) AS avg_sentiment
            RETURN bracket, buy_count, sell_count, hold_count,
                   buy_count + sell_count + hold_count AS total,
                   coalesce(avg_confidence, 0.0) AS avg_confidence,
                   coalesce(avg_sentiment, 0.0) AS avg_sentiment
            ORDER BY bracket
            """,
            cycle_id=cycle_id,
            round_num=round_num,
        )
        return [
            BracketRoundRow(
                bracket=str(r["bracket"]),
                buy_count=int(r["buy_count"]),
                sell_count=int(r["sell_count"]),
                hold_count=int(r["hold_count"]),
                total=int(r["total"]),
                avg_confidence=float(r["avg_confidence"]),
                avg_sentiment=float(r["avg_sentiment"]),
            )
            async for r in result
        ]

    async def read_rationale_entries_for_round(
        self,
        cycle_id: str,
        round_num: int,
        limit: int = 10,
    ) -> list[RationaleRoundRow]:
        """Top rationales for a round by confidence, read from the Decision node.

        RationaleEpisode.rationale is no longer the source (docs/DECISIONS.md#adr-neo4j-schema).
        """
        rows = await self._read(
            self._read_rationale_entries_for_round_tx, cycle_id, round_num, limit, op="read_rationale_entries_for_round"
        )
        self._log.debug(
            "read_rationale_entries_for_round",
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(rows),
        )
        return rows

    @staticmethod
    async def _read_rationale_entries_for_round_tx(
        tx: AsyncManagedTransaction,
        cycle_id: str,
        round_num: int,
        limit: int,
    ) -> list[RationaleRoundRow]:
        result = await tx.run(
            """
            MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: $round_num})
            RETURN
                a.id AS agent_id,
                toLower(d.signal) AS signal,
                coalesce(d.rationale, '') AS rationale,
                d.round AS round_num
            ORDER BY d.confidence DESC, agent_id
            LIMIT $limit
            """,
            cycle_id=cycle_id,
            round_num=round_num,
            limit=limit,
        )
        return [
            RationaleRoundRow(
                agent_id=str(r["agent_id"]),
                signal=str(r["signal"]),
                rationale=str(r["rationale"]),
                round_num=int(r["round_num"]),
            )
            async for r in result
        ]
