"""Replay reads, cycle lookups, agent decisions and interview rows
(docs/DECISIONS.md#adr-neo4j-schema).

Each public function is the body of the GraphStateManager method with the same
name; it receives the facade's read helper (TxRunner) and returns rows from
graph/rows.py.
"""

from __future__ import annotations

import json
import time
from collections.abc import Collection
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast, get_args

import structlog

from alphaswarm.episodes import EntityRef
from alphaswarm.errors import AgentNotFoundError
from alphaswarm.graph.rows import (
    _COMPLETE_ONLY,
    _EFFECTIVE_STATUS,
    AgentDecisionRow,
    AgentInterviewRows,
    BracketRoundRow,
    CompletedCycleRow,
    CycleSignalRow,
    CycleStatus,
    RationaleRoundRow,
    TxRunner,
)
from alphaswarm.state import AgentState
from alphaswarm.types import BracketType, SignalType

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction


log = structlog.get_logger(component="graph")

# One completeness rule for every reader: the stored Cycle.status, else the
# legacy predicate (metrics stamped, or a round-3 decision), so the job routes and
# read_completed_cycles never disagree about a cycle (docs/DECISIONS.md#adr-cycle-metrics).
_CYCLE_STATUS_QUERY: Final = f"MATCH (c:Cycle {{cycle_id: $cycle_id}}) RETURN {_EFFECTIVE_STATUS} AS status"
_CYCLE_STATUSES: Final[frozenset[str]] = frozenset(get_args(CycleStatus))


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


async def read_full_cycle_signals(read: TxRunner, cycle_id: str) -> dict[tuple[str, int], AgentState]:
    """All agents' signals for every round of a cycle, keyed (agent_id, round_num).

    One flat query that starts from the Decision index (docs/DECISIONS.md#p28-d-08);
    about 300 rows for 100 agents x 3 rounds.
    """
    t0 = time.perf_counter()
    rows = await read(_read_full_cycle_signals_tx, cycle_id, op="read_full_cycle_signals")
    log.debug(
        "read_full_cycle_signals",
        cycle_id=cycle_id,
        count=len(rows),
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
    return {
        (row["agent_id"], row["round_num"]): AgentState(
            signal=SignalType(row["signal"]) if row["signal"] else None,
            confidence=row["confidence"],
        )
        for row in rows
    }


async def _read_full_cycle_signals_tx(tx: AsyncManagedTransaction, cycle_id: str) -> list[CycleSignalRow]:
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
    return [
        CycleSignalRow(
            agent_id=str(r["agent_id"]),
            round_num=int(r["round_num"]),
            signal=str(r["signal"]) if r["signal"] else None,
            confidence=float(r["confidence"]),
        )
        async for r in result
    ]


async def read_completed_cycles(
    read: TxRunner,
    limit: int = 20,
    *,
    before: datetime | None = None,
) -> list[CompletedCycleRow]:
    """Return complete cycles (Cycle.status), newest first, one page at a time.

    *before* is the created_at of the previous page's last row; rows
    strictly older than it are returned. A naive *before* is read as UTC.
    """
    rows: list[CompletedCycleRow] = await read(
        _read_completed_cycles_tx, limit, _as_utc(before), op="read_completed_cycles"
    )
    log.debug("completed_cycles_read", count=len(rows), paged=before is not None)
    return rows


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
    read: TxRunner,
    cycle_id: str,
    round_num: int,
) -> list[BracketRoundRow]:
    """Per-bracket distribution for one round (replay).

    total and averages exclude PARSE_ERROR, matching the live frame's
    compute_bracket_summaries; the replay manager maps display names.
    """
    rows = await read(
        _read_bracket_narratives_for_round_tx, cycle_id, round_num, op="read_bracket_narratives_for_round"
    )
    log.debug(
        "read_bracket_narratives_for_round",
        cycle_id=cycle_id,
        round_num=round_num,
        count=len(rows),
    )
    return rows


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
    read: TxRunner,
    cycle_id: str,
    round_num: int,
    limit: int = 10,
) -> list[RationaleRoundRow]:
    """Top rationales for a round by confidence, read from the Decision node.

    RationaleEpisode.rationale is no longer the source (docs/DECISIONS.md#adr-neo4j-schema).
    """
    rows = await read(
        _read_rationale_entries_for_round_tx, cycle_id, round_num, limit, op="read_rationale_entries_for_round"
    )
    log.debug(
        "read_rationale_entries_for_round",
        cycle_id=cycle_id,
        round_num=round_num,
        count=len(rows),
    )
    return rows


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


async def read_agent_decisions(read: TxRunner, cycle_id: str, agent_id: str) -> list[AgentDecisionRow]:
    """All of one agent's stored decisions in a cycle, ascending by round.

    Rounds appear as they are persisted, so a running cycle returns the
    rounds finished so far (docs/DECISIONS.md#p14-d-06).

    Raises:
        Neo4jQueryError / Neo4jUnavailableError: When the read fails.
    """
    rows = await read(_read_agent_decisions_tx, cycle_id, agent_id, op="read_agent_decisions")
    log.debug(
        "agent_decisions_read",
        cycle_id=cycle_id,
        agent_id=agent_id,
        count=len(rows),
    )
    return rows


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


async def read_decision_narrative(read: TxRunner, cycle_id: str, agent_id: str) -> str | None:
    """Narrative stored on the agent's final-round Decision of this cycle, or None."""
    return await read(
        _read_decision_narrative_tx,
        cycle_id,
        agent_id,
        op="read_decision_narrative",
    )


async def _read_decision_narrative_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    agent_id: str,
) -> str | None:
    result = await tx.run(
        """
        MATCH (:Agent {id: $agent_id})-[:MADE]->(d:Decision {cycle_id: $cycle_id})
        RETURN d.narrative AS narrative
        ORDER BY d.round DESC
        LIMIT 1
        """,
        cycle_id=cycle_id,
        agent_id=agent_id,
    )
    record = await result.single()
    if record is None or record["narrative"] is None:
        return None
    return str(record["narrative"])


async def read_cycle_status(read: TxRunner, cycle_id: str) -> CycleStatus | None:
    """Lifecycle status of *cycle_id*, or ``None`` when no such cycle exists.

    Job routes gate on this instead of the in-memory phase, which a restart
    resets to idle (docs/DECISIONS.md#adr-background-tasks).
    """
    return await read(_read_cycle_status_tx, cycle_id, op="read_cycle_status")


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


async def cycle_exists(read: TxRunner, cycle_id: str) -> bool:
    """True when a Cycle node with *cycle_id* exists, whatever its status."""
    return await read_cycle_status(read, cycle_id) is not None


async def read_latest_cycle_id(
    read: TxRunner,
    *,
    statuses: Collection[CycleStatus] = _COMPLETE_ONLY,
) -> str | None:
    """Most recent cycle whose (effective) status is in *statuses*, or None.

    The default serves `alphaswarm report`, which must never pick a running
    or failed cycle (docs/DECISIONS.md#adr-cycle-metrics).
    """
    wanted = list(statuses)
    if not wanted:
        raise ValueError("statuses must not be empty")
    return await read(_read_latest_cycle_id_tx, wanted, op="read_latest_cycle_id")


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


async def read_cycle_seed(read: TxRunner, cycle_id: str) -> str | None:
    """Return the seed_rumor text for a cycle, or None if not found.

    Used by advisory.engine.synthesize so the
    SEED_RUMOR prompt block and the relevance scorer's seed_match term
    operate on the real rumor text instead of an empty string.
    """
    result = await read(_read_cycle_seed_tx, cycle_id, op="read_cycle_seed")
    return result


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


async def read_cycle_entities(read: TxRunner, cycle_id: str) -> list[EntityRef]:
    """Entities the cycle MENTIONS, in their original casing (docs/DECISIONS.md#p11-d-09).

    Read once per cycle before Round 1; ordered by name, then type.
    """
    return await read(_read_cycle_entities_tx, cycle_id, op="read_cycle_entities")


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


async def read_agent_interview_rows(read: TxRunner, agent_id: str, cycle_id: str) -> AgentInterviewRows:
    """One agent's identity, the cycle's stored modifiers, and its decisions and
    narrative in that cycle (docs/DECISIONS.md#p14-d-06).

    The narrative is the one stored on this cycle's final-round Decision, never
    another cycle's.

    Raises:
        AgentNotFoundError: there is no Agent node with this id.
        Neo4jQueryError / Neo4jUnavailableError: When the read fails.
    """
    records = await read(_read_interview_context_tx, agent_id, cycle_id, op="read_agent_interview_rows")
    if not records:
        raise AgentNotFoundError(agent_id, cycle_id)
    decided = [r for r in records if r["round_num"] is not None]
    decisions = [
        AgentDecisionRow(
            round_num=int(r["round_num"]),
            signal=str(r["signal"]),
            confidence=float(r["confidence"]),
            sentiment=float(r["sentiment"]),
            rationale=str(r["rationale"] or ""),
            cited_agents=sorted(str(c) for c in r["cited_agents"]),
        )
        for r in decided
    ]
    log.debug(
        "interview_rows_read",
        agent_id=agent_id,
        cycle_id=cycle_id,
        decision_count=len(decisions),
    )
    return AgentInterviewRows(
        agent_id=agent_id,
        name=str(records[0]["name"]),
        bracket=str(records[0]["bracket"]),
        modifiers=_decode_modifiers(records[0]["modifiers_json"]),
        narrative=str(decided[-1]["narrative"] or "") if decided else "",
        decisions=decisions,
    )


async def _read_interview_context_tx(
    tx: AsyncManagedTransaction,
    agent_id: str,
    cycle_id: str,
) -> list[dict[str, Any]]:
    """One row per stored round (or one null-decision row) with the cycle's modifiers."""
    result = await tx.run(
        """
        MATCH (a:Agent {id: $agent_id})
        OPTIONAL MATCH (c:Cycle {cycle_id: $cycle_id})
        OPTIONAL MATCH (a)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
        OPTIONAL MATCH (d)-[:CITED]->(cited:Agent)
        WITH a, c, d, collect(DISTINCT cited.id) AS cited_agents
        RETURN a.name AS name,
               a.bracket AS bracket,
               c.modifiers_json AS modifiers_json,
               d.round AS round_num,
               d.signal AS signal,
               d.confidence AS confidence,
               d.sentiment AS sentiment,
               d.rationale AS rationale,
               d.narrative AS narrative,
               cited_agents
        ORDER BY round_num
        """,
        agent_id=agent_id,
        cycle_id=cycle_id,
    )
    return [dict(record) async for record in result]


def _decode_modifiers(raw: object) -> dict[BracketType, str] | None:
    """Inverse of _encode_modifiers; unknown brackets and bad JSON are dropped."""
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("cycle_modifiers_decode_failed")
        return None
    if not isinstance(data, dict):
        return None
    known = {b.value for b in BracketType}
    return {BracketType(k): v for k, v in data.items() if k in known and isinstance(v, str)}
