"""Pure value objects and helpers for persisting a round's episodes.

Moved out of the deleted ``write_buffer.py``: a round is now persisted in
one ``GraphStateManager.persist_round`` transaction, so only these pure
pieces remain (docs/DECISIONS.md#p11-d-01).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from alphaswarm.types import FlipType, SignalType


@dataclass(frozen=True)
class EpisodeRecord:
    """One agent's inference episode, written as a RationaleEpisode node."""

    decision_id: str  # links to the parent Decision via HAS_EPISODE
    agent_id: str
    rationale: str
    peer_context_received: str  # full formatted peer context; "" in Round 1
    flip_type: str  # FlipType.value (stored as a string for Neo4j)
    round_num: int
    cycle_id: str


def compute_flip_type(prev_signal: SignalType | None, curr_signal: SignalType) -> FlipType:
    """Return the FlipType for prev -> curr (docs/DECISIONS.md#p11-d-06).

    FlipType.NONE when there is no previous signal, either side is a
    PARSE_ERROR, or the signal did not change.
    """
    if prev_signal is None:
        return FlipType.NONE
    if prev_signal == SignalType.PARSE_ERROR:
        return FlipType.NONE
    if curr_signal == SignalType.PARSE_ERROR:
        return FlipType.NONE
    if prev_signal == curr_signal:
        return FlipType.NONE
    return FlipType(f"{prev_signal.value}_to_{curr_signal.value}")


@dataclass(frozen=True)
class EntityRef:
    """An entity linked to a cycle via MENTIONS."""

    name: str
    type: str  # EntityType.value


@dataclass(frozen=True)
class EntityMatch:
    """A (Decision)-[:REFERENCES]->(Entity) edge to write."""

    decision_id: str
    entity_name: str
    entity_type: str
    match_type: Literal["substring", "token"]


def match_entities(
    records: Sequence[EpisodeRecord],
    entities: Sequence[EntityRef],
) -> list[EntityMatch]:
    """Case-insensitive substring match of entity names in each rationale.

    Order: records first, then entities (docs/DECISIONS.md#p11-d-08). Empty
    names never match.
    """
    matches: list[EntityMatch] = []
    for record in records:
        text = record.rationale.lower()
        for entity in entities:
            if entity.name and entity.name.lower() in text:
                matches.append(EntityMatch(record.decision_id, entity.name, entity.type, "substring"))
    return matches


def new_decision_ids(n: int) -> list[str]:
    """Return *n* fresh uuid4 strings for a round's Decision nodes (docs/DECISIONS.md#p4-d-10)."""
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    return [str(uuid.uuid4()) for _ in range(n)]
