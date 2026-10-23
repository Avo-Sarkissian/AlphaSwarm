"""Fakes and helpers for code that talks to GraphStateManager.

Shared by the engine scenarios (tests/engine/conftest.py), tests/test_simulation.py
and the seeded-cycle builder. Values are fictional.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alphaswarm.episodes import EntityMatch, EntityRef, EpisodeRecord
from alphaswarm.graph import PersistRoundResult
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
