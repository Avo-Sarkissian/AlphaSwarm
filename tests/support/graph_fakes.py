"""Fakes and helpers for code that talks to GraphStateManager.

Shared by the engine scenarios (tests/engine/conftest.py), tests/test_simulation.py
and the seeded-cycle builder. Values are fictional.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alphaswarm.episodes import (
    EntityMatch,
    EntityRef,
    EpisodeRecord,
    compute_flip_type,
    match_entities,
    new_decision_ids,
)
from alphaswarm.graph import GraphStateManager, PersistRoundResult
from alphaswarm.types import AgentDecision

SCENARIO_ENTITIES: Final[tuple[EntityRef, ...]] = (
    EntityRef("ZZZT Holdings", "company"),
    EntityRef("QQQX Robotics", "company"),
    EntityRef("Industrial Automation", "sector"),
)


async def fake_persist_round(
    cycle_id: str,
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    *,
    decision_ids: Sequence[str],
    episodes: Sequence[EpisodeRecord],
    entity_matches: Sequence[EntityMatch],
    **_later_kwargs: object,
) -> PersistRoundResult:
    """side_effect for a mocked GraphStateManager.persist_round: all written, none dropped.

    ``**_later_kwargs`` absorbs keyword arguments added to persist_round later
    (for example the holdout's control ids).
    """
    return PersistRoundResult(
        decision_ids=tuple(decision_ids),
        decisions_written=len(decisions),
        episodes_written=len(episodes),
        citations_written=sum(len(d.cited_agents) for _, d in decisions),
        citations_dropped=0,
        references_written=len(entity_matches),
    )


async def write_round(
    gm: GraphStateManager,
    cycle_id: str,
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    *,
    prev: Sequence[tuple[str, AgentDecision]] | None = None,
    entities: Sequence[EntityRef] = (),
    peer_context: str = "",
) -> list[str]:
    """Write one round through the production API, the way run_simulation does."""
    ids = new_decision_ids(len(decisions))
    prev_signal = {aid: d.signal for aid, d in prev} if prev else {}
    episodes = [
        EpisodeRecord(
            decision_id=did,
            agent_id=aid,
            rationale=d.rationale,
            peer_context_received=peer_context if round_num > 1 else "",
            flip_type=compute_flip_type(prev_signal.get(aid), d.signal).value,
            round_num=round_num,
            cycle_id=cycle_id,
        )
        for did, (aid, d) in zip(ids, decisions, strict=True)
    ]
    result = await gm.persist_round(
        cycle_id,
        round_num,
        decisions,
        decision_ids=ids,
        episodes=episodes,
        entity_matches=match_entities(episodes, entities),
    )
    return list(result.decision_ids)
