"""Schema statements and every write: agents, cycles, rounds, influence edges,
shocks and narratives (docs/DECISIONS.md#adr-neo4j-schema).

Each public function is the body of the GraphStateManager method with the same
name and receives the facade's helpers (TxRunner). Batches use UNWIND with one
transaction per call (docs/DECISIONS.md#p4-d-08). Nothing here that ensure_schema
runs deletes or rewrites data; retired properties go only through
remove_legacy_properties.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

import structlog

from alphaswarm.errors import Neo4jWriteError
from alphaswarm.graph.rows import _LEGACY_COMPLETE, CitationPairRow, InfluenceEdgeRow, PersistRoundResult, TxRunner
from alphaswarm.influence import citation_weights

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

    from alphaswarm.episodes import EntityMatch, EpisodeRecord
    from alphaswarm.errors import RunErrorCode
    from alphaswarm.graph.rows import CycleStatus
    from alphaswarm.types import AgentDecision, AgentPersona, BracketType, SeedEvent

log = structlog.get_logger(component="graph")

SCHEMA_STATEMENTS: list[str] = [
    # Drops first: the decision_id uniqueness constraint cannot be created while
    # the plain decision_id_idx index exists; post/episode indexes serve no query
    # and agent_id_idx duplicates agent_id_unique (docs/DECISIONS.md#adr-neo4j-schema).
    "DROP INDEX decision_id_idx IF EXISTS",
    "DROP INDEX agent_id_idx IF EXISTS",
    "DROP INDEX post_cycle_round IF EXISTS",
    "DROP INDEX post_id_idx IF EXISTS",
    "DROP INDEX episode_cycle_round IF EXISTS",
    "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT cycle_id_unique IF NOT EXISTS FOR (c:Cycle) REQUIRE c.cycle_id IS UNIQUE",
    "CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE",
    "CREATE CONSTRAINT decision_id_unique IF NOT EXISTS FOR (d:Decision) REQUIRE d.decision_id IS UNIQUE",
    "CREATE CONSTRAINT shock_id_unique IF NOT EXISTS FOR (se:ShockEvent) REQUIRE se.shock_id IS UNIQUE",
    "CREATE INDEX decision_cycle_round IF NOT EXISTS FOR (d:Decision) ON (d.cycle_id, d.round)",
    "CREATE INDEX decision_cycle IF NOT EXISTS FOR (d:Decision) ON (d.cycle_id)",
    "CREATE INDEX influenced_by_cycle_round IF NOT EXISTS FOR ()-[r:INFLUENCED_BY]-() ON (r.cycle_id, r.round)",
    "CREATE INDEX cycle_created IF NOT EXISTS FOR (c:Cycle) ON (c.created_at)",
    "CREATE INDEX cycle_status IF NOT EXISTS FOR (c:Cycle) ON (c.status)",
]

# A uniqueness constraint cannot be created over existing duplicates, and no
# migration may delete data: while duplicate decision ids exist, ensure_schema
# keeps the plain index instead and warns (docs/DECISIONS.md#adr-neo4j-schema).
_DECISION_ID_CONSTRAINT: Final = "decision_id_unique"
_DROP_DECISION_ID_INDEX: Final = "DROP INDEX decision_id_idx IF EXISTS"
_DECISION_ID_INDEX: Final = "CREATE INDEX decision_id_idx IF NOT EXISTS FOR (d:Decision) ON (d.decision_id)"
_DECISION_ID_CONSTRAINT_PRESENT: Final = "SHOW CONSTRAINTS YIELD name WHERE name = $name RETURN count(*) AS n"
_DECISION_ID_DUPLICATES: Final = (
    "MATCH (d:Decision) WHERE d.decision_id IS NOT NULL "
    "WITH d.decision_id AS id, count(*) AS n WHERE n > 1 "
    "RETURN count(*) AS duplicate_ids"
)


def schema_statements(duplicate_decision_ids: int) -> list[str]:
    """The statements ensure_schema runs, given the duplicate decision id count.

    With duplicates the decision_id_idx drop is skipped and the uniqueness
    constraint is replaced by the plain index, so startup never fails on them.
    """
    if duplicate_decision_ids <= 0:
        return list(SCHEMA_STATEMENTS)
    return [
        _DECISION_ID_INDEX if _DECISION_ID_CONSTRAINT in stmt else stmt
        for stmt in SCHEMA_STATEMENTS
        if stmt != _DROP_DECISION_ID_INDEX
    ]


# Idempotent removal of retired properties. Not run by ensure_schema: removing data is the
# owner's call after a backup (docs/RUNBOOK.md §3), so it runs only through
# remove_legacy_properties().
LEGACY_PROPERTY_CLEANUP: Final[tuple[str, ...]] = (
    # Narratives moved to the final-round Decision (docs/DECISIONS.md#p11-d-10);
    # the shared Agent property paired one cycle's text with another's decisions.
    "MATCH (a:Agent) WHERE a.decision_narrative IS NOT NULL REMOVE a.decision_narrative",
)

# ensure_schema() stamps the same rule onto status-less cycles; SET-only, idempotent.
CYCLE_STATUS_BACKFILL: Final = (
    "MATCH (c:Cycle) WHERE c.status IS NULL "
    f"SET c.status = CASE WHEN {_LEGACY_COMPLETE} THEN 'complete' ELSE 'failed' END "
    "RETURN count(c) AS backfilled"
)

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
    error_kind: d.error_kind,
    parse_tier: d.parse_tier,
    peer_ids: d.peer_ids,
    citations_invalid: d.citations_invalid,
    shock_treated: d.shock_treated
})
CREATE (a)-[:MADE]->(dec)
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

# rationale lives on the Decision only (docs/DECISIONS.md#adr-neo4j-schema)
_PERSIST_EPISODES: Final = """
UNWIND $episodes AS ep
MATCH (d:Decision {decision_id: ep.decision_id})
CREATE (re:RationaleEpisode {
    timestamp: datetime(),
    peer_context_received: ep.peer_context_received,
    flip_type: ep.flip_type,
    round: ep.round_num,
    cycle_id: ep.cycle_id
})
CREATE (d)-[:HAS_EPISODE]->(re)
RETURN count(re) AS n
"""

# REFERENCES link a decision only to its own cycle's (name, type) entity, through
# MENTIONS; names are matched on whole tokens in episodes.match_entities. EXISTS
# (not a MENTIONS path) so a seed that lists an entity twice still yields one
# edge per match (docs/DECISIONS.md#p11-d-08).
_PERSIST_REFERENCES: Final = """
UNWIND $matches AS m
MATCH (d:Decision {decision_id: m.decision_id})
MATCH (e:Entity {name: m.entity_name, type: m.entity_type})
WHERE EXISTS { MATCH (:Cycle {cycle_id: $cycle_id})-[:MENTIONS]->(e) }
CREATE (d)-[:REFERENCES {match_type: m.match_type}]->(e)
RETURN count(*) AS n
"""


def _encode_modifiers(modifiers: Mapping[BracketType, str] | None) -> str | None:
    """Canonical JSON of the per-cycle focus lines keyed by bracket value; None stays None."""
    if modifiers is None:
        return None
    return json.dumps(
        {bracket.value: text for bracket, text in modifiers.items()},
        sort_keys=True,
        ensure_ascii=False,
    )


async def resolve_schema_statements(read: TxRunner) -> list[str]:
    """The DDL ensure_schema runs: SCHEMA_STATEMENTS, or the duplicate-safe
    variant while duplicate decision ids exist (they are never deleted)."""
    duplicates = await read(_count_decision_id_duplicates_tx, op="ensure_schema")
    if duplicates:
        log.warning("decision_id_duplicates_found", count=duplicates)
    return schema_statements(duplicates)


async def apply_data_maintenance(write: TxRunner) -> None:
    """Idempotent, SET-only data step ensure_schema runs after the DDL: give
    status-less legacy cycles a status (docs/DECISIONS.md#adr-cycle-metrics)."""
    backfilled = await write(_backfill_cycle_status_tx, op="backfill_cycle_status")
    if backfilled:
        log.info("cycle_status_backfilled", count=backfilled)


async def _count_decision_id_duplicates_tx(tx: AsyncManagedTransaction) -> int:
    """Duplicate decision ids; 0 without a scan once the constraint exists."""
    result = await tx.run(_DECISION_ID_CONSTRAINT_PRESENT, name=_DECISION_ID_CONSTRAINT)
    record = await result.single()
    if record and record["n"]:
        return 0
    result = await tx.run(_DECISION_ID_DUPLICATES)
    record = await result.single()
    return int(record["duplicate_ids"]) if record else 0


async def _backfill_cycle_status_tx(tx: AsyncManagedTransaction) -> int:
    """Give every status-less (legacy) Cycle a status; idempotent."""
    result = await tx.run(CYCLE_STATUS_BACKFILL)
    record = await result.single()
    return int(record["backfilled"]) if record else 0


async def remove_legacy_properties(write: TxRunner) -> None:
    """Remove retired properties (``LEGACY_PROPERTY_CLEANUP``); idempotent.

    Deletes data that nothing reads any more, so it never runs at startup;
    take a backup first (docs/RUNBOOK.md §3).
    """
    await write(_legacy_property_cleanup_tx, op="legacy_property_cleanup")


async def _legacy_property_cleanup_tx(tx: AsyncManagedTransaction) -> None:
    """Idempotent removal of retired properties (no migration framework)."""
    for stmt in LEGACY_PROPERTY_CLEANUP:
        result = await tx.run(stmt)
        await result.consume()


async def seed_agents(write: TxRunner, agents: list[AgentPersona]) -> None:
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

    await write(_seed_agents_tx, agent_params, op="seed_agents")
    pruned = await write(_prune_stale_agents_tx, current_ids, op="prune_stale_agents")

    if pruned:
        log.info("stale_agents_pruned", count=pruned)
    log.info("agents_seeded", count=len(agents))


async def _seed_agents_tx(
    tx: AsyncManagedTransaction,
    agents: list[dict[str, Any]],
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


async def create_cycle_with_seed_event(
    write: TxRunner,
    seed_rumor: str,
    seed_event: SeedEvent,
    *,
    num_rounds: int,
    modifiers: Mapping[BracketType, str] | None = None,
    prompt_template_hash: str | None = None,
) -> str:
    """Atomically create the Cycle (with num_rounds) and its seed entities.

    Cycle, Entity and MENTIONS are written in one transaction so a failure
    cannot leave an orphan Cycle. `num_rounds` is stamped here so running
    and failed cycles carry it too; report queries resolve the final round
    from it (docs/DECISIONS.md#adr-num-rounds). The cycle's generated
    persona modifiers (canonical JSON, absent when None) and the
    prompt-template hash are stored on the same node so a past run's
    prompts can be rebuilt (docs/DECISIONS.md#adr-neo4j-schema).

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
    await write(
        _create_cycle_with_entities_tx,
        cycle_id,
        seed_rumor,
        seed_event.overall_sentiment,
        entity_params,
        num_rounds,
        _encode_modifiers(modifiers),
        prompt_template_hash,
        op="create_cycle_with_seed_event",
    )
    log.info(
        "cycle_with_seed_event_created",
        cycle_id=cycle_id,
        entity_count=len(entity_params),
        overall_sentiment=seed_event.overall_sentiment,
        num_rounds=num_rounds,
        has_modifiers=modifiers is not None,
    )
    return cycle_id


async def _create_cycle_with_entities_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    seed_rumor: str,
    overall_sentiment: float,
    entities: list[dict[str, Any]],
    num_rounds: int,
    modifiers_json: str | None,
    prompt_template_hash: str | None,
) -> None:
    """One transaction: Cycle (metadata, status 'running'), then UNWIND Entity + MENTIONS."""
    await tx.run(
        """
        CREATE (c:Cycle {
            cycle_id: $cycle_id,
            seed_rumor: $seed_rumor,
            overall_sentiment: $overall_sentiment,
            created_at: datetime(),
            num_rounds: $num_rounds,
            modifiers_json: $modifiers_json,
            prompt_template_hash: $prompt_template_hash,
            status: 'running'
        })
        """,
        cycle_id=cycle_id,
        seed_rumor=seed_rumor,
        overall_sentiment=overall_sentiment,
        num_rounds=num_rounds,
        modifiers_json=modifiers_json,
        prompt_template_hash=prompt_template_hash,
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


async def set_cycle_status(
    write: TxRunner,
    cycle_id: str,
    status: CycleStatus,
    *,
    error_code: RunErrorCode | None = None,
) -> None:
    """Record a lifecycle transition (docs/DECISIONS.md#adr-cycle-metrics).

    ``error_code`` goes only with ``failed``; writing any other status
    removes a stored code.

    Raises:
        ValueError: an ``error_code`` was given with a status other than ``failed``.
        Neo4jWriteError: no Cycle has *cycle_id*, or the write failed.
        Neo4jUnavailableError: the database is unreachable.
    """
    if error_code is not None and status != "failed":
        raise ValueError(f"error_code goes only with status 'failed', not {status!r}")
    found = await write(
        _set_cycle_status_tx,
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
    log.info("cycle_status_set", cycle_id=cycle_id, status=status, error_code=error_code)


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


async def write_cycle_metrics(
    write: TxRunner,
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
    await write(_write_cycle_metrics_tx, cycle_id, metrics, op="write_cycle_metrics")
    log.info("cycle_metrics_written", cycle_id=cycle_id, keys=len(metrics))


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


async def persist_round(
    write: TxRunner,
    cycle_id: str,
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    *,
    decision_ids: Sequence[str],
    episodes: Sequence[EpisodeRecord],
    entity_matches: Sequence[EntityMatch],
    control_ids: Collection[str] = (),
    exposures: Mapping[str, Sequence[str]] | None = None,
    citations_invalid: Mapping[str, int] | None = None,
    shock_treated_ids: Collection[str] | None = None,
) -> PersistRoundResult:
    """Write one round in a single transaction (docs/DECISIONS.md#p4-d-08).

    Decisions (with error_kind and parse_tier), CITED, RationaleEpisodes and REFERENCES
    commit together or not at all. Fewer Decisions or episodes than
    passed raises Neo4jWriteError and rolls the round back; citations of
    unknown agents are counted and logged, never raised. Every Decision
    stores ``control``: true for the agents in ``control_ids`` (the seeded
    no-peer holdout), false otherwise
    (docs/DECISIONS.md#adr-diverse-peer-context).

    ``exposures``, ``citations_invalid`` and ``shock_treated_ids`` become
    ``d.peer_ids`` (shown order; ``[]`` for an agent without an entry),
    ``d.citations_invalid`` (0 by default) and ``d.shock_treated``. ``None``
    leaves the property absent, because Neo4j stores no nulls: absent means
    "not recorded" (docs/DECISIONS.md#adr-run-manifest).
    """
    if len(decision_ids) != len(decisions):
        raise ValueError(f"decision_ids length {len(decision_ids)} != decisions length {len(decisions)}")
    pairs = list(zip(decision_ids, decisions, strict=True))
    control_set = frozenset(control_ids)
    shock_set = frozenset(shock_treated_ids) if shock_treated_ids is not None else None
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
            "parse_tier": d.parse_tier,
            # None -> property absent (Neo4j stores no nulls): "not recorded".
            "peer_ids": list(exposures.get(agent_id, ())) if exposures is not None else None,
            "citations_invalid": (citations_invalid.get(agent_id, 0) if citations_invalid is not None else None),
            "shock_treated": (agent_id in shock_set) if shock_set is not None else None,
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
        {
            "decision_id": m.decision_id,
            "entity_name": m.entity_name,
            "entity_type": m.entity_type,
            "match_type": m.match_type,
        }
        for m in entity_matches
    ]
    summary, dropped = await write(
        _persist_round_tx,
        cycle_id,
        round_num,
        decision_rows,
        cited_rows,
        episode_rows,
        reference_rows,
        op="persist_round",
    )
    if dropped:
        log.warning(
            "citations_dropped",
            cycle_id=cycle_id,
            round_num=round_num,
            count=len(dropped),
            cited_ids=",".join(sorted(set(dropped))[:20]),
        )
    log.info(
        "round_persisted",
        cycle_id=cycle_id,
        round_num=round_num,
        decisions=summary.decisions_written,
        episodes=summary.episodes_written,
        citations=summary.citations_written,
        references=summary.references_written,
    )
    return summary


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
        result = await tx.run(_PERSIST_REFERENCES, matches=references, cycle_id=cycle_id)
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


async def compute_influence_edges(
    read: TxRunner,
    write: TxRunner,
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
    if total_agents <= 0:
        # A round in which every agent failed has no denominator
        # (docs/DECISIONS.md#p8-d-01); write nothing.
        log.warning(
            "influence_edges_skipped",
            cycle_id=cycle_id,
            up_to_round=up_to_round,
            total_agents=total_agents,
        )
        return {}

    pairs = await read(
        _read_citation_pairs_tx,
        cycle_id,
        up_to_round,
        op="read_citation_pairs",
    )
    if not pairs:
        log.info("no_citations_found", cycle_id=cycle_id, up_to_round=up_to_round)
        return {}

    # Per-target citation frequency from deduplicated pairs; weight =
    # citations / active agents (docs/DECISIONS.md#p8-d-01).
    weights = citation_weights((p["target_id"] for p in pairs), total_agents)
    edges = [
        InfluenceEdgeRow(
            source_id=p["source_id"],
            target_id=p["target_id"],
            weight=weights[p["target_id"]],
        )
        for p in pairs
    ]
    await write(
        _write_influence_edges_tx,
        edges,
        cycle_id,
        up_to_round,
        op="write_influence_edges",
    )
    log.info(
        "influence_edges_computed",
        cycle_id=cycle_id,
        up_to_round=up_to_round,
        edge_count=len(edges),
        agents_with_influence=len(weights),
    )
    return weights


async def _read_citation_pairs_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    up_to_round: int,
) -> list[CitationPairRow]:
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
    return [
        CitationPairRow(source_id=str(record["source_id"]), target_id=str(record["target_id"]))
        async for record in result
    ]


async def _write_influence_edges_tx(
    tx: AsyncManagedTransaction,
    edges: list[InfluenceEdgeRow],
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


async def write_shock_event(
    write: TxRunner,
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
        Neo4jWriteError / Neo4jUnavailableError: When the write fails, or
            when the database is unreachable or rejects the credentials.
    """
    shock_id = str(uuid.uuid4())
    await write(_write_shock_event_tx, cycle_id, shock_id, shock_text, injected_before_round, op="write_shock_event")
    log.info(
        "shock_event_written",
        cycle_id=cycle_id,
        injected_before_round=injected_before_round,
        shock_length=len(shock_text),
    )
    return shock_id


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


async def write_decision_narrative(write: TxRunner, cycle_id: str, agent_id: str, narrative: str) -> None:
    """Store a narrative on the agent's final-round Decision of this cycle.

    Narratives are per cycle; the shared Agent node never holds one again
    (docs/DECISIONS.md#p11-d-10). With no matching Decision the write is a
    logged no-op.
    """
    updated = await write(
        _write_decision_narrative_tx,
        cycle_id,
        agent_id,
        narrative,
        op="write_decision_narrative",
    )
    if updated == 0:
        log.warning("decision_narrative_target_missing", cycle_id=cycle_id, agent_id=agent_id)
        return
    log.info("decision_narrative_written", cycle_id=cycle_id, agent_id=agent_id)


async def _write_decision_narrative_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    agent_id: str,
    narrative: str,
) -> int:
    result = await tx.run(
        """
        MATCH (:Agent {id: $agent_id})-[:MADE]->(d:Decision {cycle_id: $cycle_id})
        WITH d ORDER BY d.round DESC LIMIT 1
        SET d.narrative = $narrative
        RETURN count(d) AS updated
        """,
        cycle_id=cycle_id,
        agent_id=agent_id,
        narrative=narrative,
    )
    record = await result.single()
    return int(record["updated"]) if record is not None else 0
