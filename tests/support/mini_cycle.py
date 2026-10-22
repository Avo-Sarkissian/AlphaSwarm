"""Small hand-built cycles for focused neo4j tests.

Everything goes through the public write API (create_cycle_with_seed_event,
write_decisions, write_rationale_episodes, write_narrative_edges,
compute_influence_edges, write_shock_event), so these tests exercise the same
Cypher the engine runs. Fictional data only.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import AgentDecision, EntityType, SeedEntity, SeedEvent, SignalType
from alphaswarm.write_buffer import EpisodeRecord, compute_flip_type

MINI_RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
MINI_ENTITIES: tuple[SeedEntity, ...] = (
    SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.6),
    SeedEntity(name="QQQX Robotics", type=EntityType.COMPANY, relevance=0.8, sentiment=0.4),
    SeedEntity(name="Industrial Automation", type=EntityType.SECTOR, relevance=0.5, sentiment=0.2),
)


def dec(
    signal: SignalType,
    confidence: float = 0.7,
    *,
    sentiment: float = 0.1,
    rationale: str = "fictional rationale",
    cited: Sequence[str] = (),
) -> AgentDecision:
    """Build an AgentDecision with test defaults."""
    return AgentDecision(
        signal=signal,
        confidence=confidence,
        sentiment=sentiment,
        rationale=rationale,
        cited_agents=list(cited),
    )


async def write_mini_cycle(
    gm: GraphStateManager,
    *,
    num_rounds: int,
    rounds: Mapping[int, Sequence[tuple[str, AgentDecision]]],
    entities: Sequence[SeedEntity] = MINI_ENTITIES,
    shock: tuple[int, str] | None = None,
) -> str:
    """Write a cycle with the given decisions per round and return its id.

    Influence edges are computed after every round >= 2 with the active
    (non-PARSE_ERROR) count, exactly as run_simulation does. `shock` is
    (injected_before_round, text).
    """
    cycle_id = await gm.create_cycle_with_seed_event(
        MINI_RUMOR,
        SeedEvent(raw_rumor=MINI_RUMOR, entities=list(entities), overall_sentiment=0.3),
        num_rounds=num_rounds,
    )
    entity_names = await gm.read_cycle_entities(cycle_id)
    previous: dict[str, SignalType] = {}
    for round_num in sorted(rounds):
        if shock is not None and shock[0] == round_num:
            await gm.write_shock_event(cycle_id, shock[1], injected_before_round=round_num)
        decisions = list(rounds[round_num])
        ids = [str(uuid.uuid4()) for _ in decisions]
        await gm.write_decisions(decisions, cycle_id, round_num, decision_ids=ids)
        episodes = [
            EpisodeRecord(
                decision_id=decision_id,
                agent_id=agent_id,
                rationale=decision.rationale,
                peer_context_received="",
                flip_type=compute_flip_type(previous.get(agent_id), decision.signal).value,
                round_num=round_num,
                cycle_id=cycle_id,
            )
            for decision_id, (agent_id, decision) in zip(ids, decisions, strict=True)
        ]
        await gm.write_rationale_episodes(episodes)
        await gm.write_narrative_edges(episodes, entity_names)
        if round_num >= 2:
            active = sum(1 for _, d in decisions if d.signal != SignalType.PARSE_ERROR)
            await gm.compute_influence_edges(cycle_id, up_to_round=round_num, total_agents=active)
        previous.update({agent_id: d.signal for agent_id, d in decisions})
    return cycle_id


async def cypher(gm: GraphStateManager, query: str, **params: Any) -> list[dict[str, Any]]:
    """Run one auto-commit query on the manager's (test) database and return the rows."""
    async with gm._driver.session(database=gm._database) as session:
        result = await session.run(query, **params)
        return [dict(record) async for record in result]
