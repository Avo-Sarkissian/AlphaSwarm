"""Report and analytics reads over a finished cycle (docs/DECISIONS.md#adr-neo4j-schema).

Each public function is the body of the GraphStateManager method with the same
name; it receives the facade's read helper (TxRunner) and returns rows from
graph/rows.py. Shock and influence maths live in alphaswarm.influence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import structlog

from alphaswarm.graph.rows import (
    UNKNOWN_SIGNAL,
    BracketNarrativeRow,
    ConsensusSummaryRow,
    EntityImpactRow,
    EvidenceEntityRow,
    FinalDecisionRow,
    InfluenceEdgeRow,
    InfluenceLeaderRow,
    KeyDissenterRow,
    RoundCitationRow,
    RoundTimelineRow,
    ShockEventRow,
    ShockImpactRow,
    SignalFlipRow,
    TxRunner,
)
from alphaswarm.influence import ShockComparisonRow, aggregate_shock_impact
from alphaswarm.personas import BRACKET_DISPLAY_NAMES, bracket_sort_key

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

log = structlog.get_logger(component="graph")


async def read_consensus_summary(read: TxRunner, cycle_id: str) -> ConsensusSummaryRow:
    """Final-round BUY/SELL/HOLD/PARSE_ERROR counts.

    The final round is Cycle.num_rounds (legacy cycles without it: 3),
    resolved inside the query (docs/DECISIONS.md#adr-num-rounds).
    """
    row = await read(_read_consensus_summary_tx, cycle_id, op="read_consensus_summary")
    log.debug("report_consensus_summary", cycle_id=cycle_id, total=row["total"])
    return row


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


async def read_round_timeline(read: TxRunner, cycle_id: str) -> list[RoundTimelineRow]:
    """Per-round counts for every round that ran, ascending."""
    rows = await read(_read_round_timeline_tx, cycle_id, op="read_round_timeline")
    log.debug("report_round_timeline", cycle_id=cycle_id, count=len(rows))
    return rows


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


async def read_bracket_narratives(read: TxRunner, cycle_id: str) -> list[BracketNarrativeRow]:
    """Per-bracket final-round stance in config order.

    Totals and averages exclude PARSE_ERROR; a bracket whose agents all
    failed has total 0 and majority None (never a default BUY).
    """
    rows = await read(_read_bracket_narratives_tx, cycle_id, op="read_bracket_narratives")
    log.debug("report_bracket_narratives", cycle_id=cycle_id, count=len(rows))
    return rows


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
            display_name=BRACKET_DISPLAY_NAMES.get(str(r["bracket"]), str(r["bracket"])),
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
    return sorted(rows, key=lambda row: bracket_sort_key(row["bracket"]))


async def read_key_dissenters(read: TxRunner, cycle_id: str) -> list[KeyDissenterRow]:
    """Agents whose final-round signal differs from their bracket's majority.

    PARSE_ERROR decisions are excluded before the majority is computed, so
    a failed agent is never a dissenter and an all-failed bracket yields none.
    """
    rows = await read(_read_key_dissenters_tx, cycle_id, op="read_key_dissenters")
    log.debug("report_key_dissenters", cycle_id=cycle_id, count=len(rows))
    return rows


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
    read: TxRunner,
    cycle_id: str,
    limit: int = 10,
) -> list[InfluenceLeaderRow]:
    """Most-cited agents in the final round.

    influence_share = citation_count / N, N = active (non-PARSE_ERROR)
    agents in the final round; this equals the D-01 edge weight and is
    no longer the quadratic sum of incoming weights
    (docs/DECISIONS.md#p8-d-01).
    """
    rows = await read(_read_influence_leaders_tx, cycle_id, limit, op="read_influence_leaders")
    log.debug("report_influence_leaders", cycle_id=cycle_id, count=len(rows))
    return rows


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


async def read_signal_flips(read: TxRunner, cycle_id: str) -> list[SignalFlipRow]:
    """Agents who changed position, from RationaleEpisode.flip_type.

    final_signal is the (uppercase) signal after the flip in that round.
    Rows are ordered by round, bracket, then agent id.
    """
    rows = await read(_read_signal_flips_tx, cycle_id, op="read_signal_flips")
    log.debug("report_signal_flips", cycle_id=cycle_id, count=len(rows))
    return rows


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


async def read_entity_impact(read: TxRunner, cycle_id: str) -> list[EntityImpactRow]:
    """Per-entity sentiment over final-round, non-failed decisions.

    Only the cycle's own MENTIONS entities count, so same-name entities
    from other cycles or types cannot leak in (docs/DECISIONS.md#p11-d-08).
    Each decision counts once per entity, even when a seed that listed the
    entity twice left duplicate MENTIONS and REFERENCES edges.
    """
    rows = await read(_read_entity_impact_tx, cycle_id, op="read_entity_impact")
    log.debug("report_entity_impact", cycle_id=cycle_id, count=len(rows))
    return rows


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


async def read_shock_impact(read: TxRunner, cycle_id: str) -> ShockImpactRow:
    """How the swarm moved across the (earliest) shock.

    Compares each agent's decision in the round before the shock with the
    shocked round; agents with a PARSE_ERROR on either side are excluded.
    Zero-filled when the cycle has no shock or no comparable agents.
    """
    row = await read(_read_shock_impact_tx, cycle_id, op="read_shock_impact")
    log.debug(
        "read_shock_impact",
        cycle_id=cycle_id,
        pivot_count=row["pivot_count"],
    )
    return row


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
    rows = [
        ShockComparisonRow(
            agent_id=str(r["agent_id"]),
            bracket=str(r["bracket"]),
            pre_signal=str(r["pre_signal"]),
            post_signal=str(r["post_signal"]),
            shock_round=int(r["shock_round"]),
            shock_text=str(r["shock_text"]),
        )
        async for r in result
    ]
    return aggregate_shock_impact(rows)


async def read_influence_edges(
    read: TxRunner,
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
    records = await read(_read_influence_edges_tx, cycle_id, round_num, op="read_influence_edges")
    log.debug(
        "influence_edges_read",
        cycle_id=cycle_id,
        round=round_num,
        count=len(records),
    )
    return records


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


async def read_shock_event(read: TxRunner, cycle_id: str) -> ShockEventRow | None:
    """Return ShockEvent metadata for the cycle, or None if no shock was injected.

    Used by the CLI and web report pipelines to pre-seed the shock-impact
    section when a shock was injected (SHOCK-04).

    Returns:
        ShockEventRow (shock_id, shock_text, injected_before_round, created_at),
        or None if no ShockEvent exists for the cycle.
    """
    record = await read(_read_shock_event_tx, cycle_id, op="read_shock_event")
    log.debug("read_shock_event", cycle_id=cycle_id)
    return record


async def _read_shock_event_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
) -> ShockEventRow | None:
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
    if record is None:
        return None
    return ShockEventRow(
        shock_id=str(record["shock_id"]),
        shock_text=str(record["shock_text"]),
        injected_before_round=int(record["injected_before_round"]),
        created_at=record["created_at"],
    )


_FINAL_ROUND_DECISIONS_QUERY: Final = """
MATCH (c:Cycle {cycle_id: $cycle_id})
WITH c, coalesce(c.num_rounds, 3) AS final_round
MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
WHERE d.round = final_round
OPTIONAL MATCH (d)-[:REFERENCES]->(e:Entity)<-[m:MENTIONS]-(c)
WITH a, d, collect(DISTINCT {name: e.name, type: e.type, ticker: m.ticker}) AS raw
RETURN a.id AS agent_id,
       a.bracket AS bracket,
       coalesce(a.influence_weight_base, 0.0) AS reach,
       toLower(d.signal) AS signal,
       coalesce(d.confidence, 0.0) AS confidence,
       coalesce(d.sentiment, 0.0) AS sentiment,
       [x IN raw WHERE x.name IS NOT NULL] AS entities
ORDER BY agent_id
"""


async def _read_final_round_decisions_tx(tx: AsyncManagedTransaction, cycle_id: str) -> list[dict[str, Any]]:
    result = await tx.run(_FINAL_ROUND_DECISIONS_QUERY, cycle_id=cycle_id)
    return [dict(record) async for record in result]


async def read_final_round_decisions(read: TxRunner, cycle_id: str) -> list[FinalDecisionRow]:
    """Final-round decisions with the cycle entities each one references.

    The advisory derives its per-holding swarm signal from these rows
    (docs/DECISIONS.md#adr-grounded-advisory); the final round follows the report
    reads (docs/DECISIONS.md#adr-num-rounds).
    """
    records = await read(_read_final_round_decisions_tx, cycle_id, op="read_final_round_decisions")
    rows = [
        FinalDecisionRow(
            agent_id=str(r["agent_id"]),
            bracket=str(r["bracket"]),
            reach=float(r["reach"]),
            signal=str(r["signal"]),
            confidence=float(r["confidence"]),
            sentiment=float(r["sentiment"]),
            entities=sorted(
                (
                    EvidenceEntityRow(
                        name=str(e["name"]),
                        type=str(e["type"]),
                        ticker=str(e["ticker"]) if e["ticker"] is not None else None,
                    )
                    for e in r["entities"]
                ),
                key=lambda e: (e["name"], e["type"]),
            ),
        )
        for r in records
    ]
    log.debug("final_round_decisions_read", cycle_id=cycle_id, count=len(rows))
    return rows


async def read_round_citations(read: TxRunner, cycle_id: str, round_num: int) -> list[RoundCitationRow]:
    """Citations made in *round_num*, each with the signal the cited agent held in
    round_num - 1 (docs/DECISIONS.md#adr-neo4j-schema).

    Per round, never the cumulative INFLUENCED_BY union used for peer weighting.
    Round 1 has no peer context, so it returns [] without a query. Self-citations
    are dropped and duplicate CITED edges collapse to one pair.
    """
    if round_num < 2:
        return []
    rows = await read(_read_round_citations_tx, cycle_id, round_num, op="read_round_citations")
    log.debug("round_citations_read", cycle_id=cycle_id, round_num=round_num, count=len(rows))
    return rows


async def _read_round_citations_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    round_num: int,
) -> list[RoundCitationRow]:
    result = await tx.run(
        """
        MATCH (author:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: $round_num})
              -[:CITED]->(cited:Agent)
        WHERE author.id <> cited.id
        WITH DISTINCT author.id AS source_id, cited
        OPTIONAL MATCH (cited)-[:MADE]->(prev:Decision {cycle_id: $cycle_id, round: $prev_round})
        WITH source_id, cited, head(collect(toLower(prev.signal))) AS cited_signal
        RETURN source_id, cited.id AS target_id, cited_signal
        ORDER BY source_id, target_id
        """,
        cycle_id=cycle_id,
        round_num=round_num,
        prev_round=round_num - 1,
    )
    return [
        RoundCitationRow(
            source_id=str(r["source_id"]),
            target_id=str(r["target_id"]),
            cited_signal=str(r["cited_signal"]) if r["cited_signal"] is not None else UNKNOWN_SIGNAL,
        )
        async for r in result
    ]
