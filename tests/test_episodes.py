"""alphaswarm.episodes value objects (docs/DECISIONS.md#p4-d-08)."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from alphaswarm.episodes import (
    EntityMatch,
    EntityRef,
    EpisodeRecord,
    compute_flip_type,
    match_entities,
    new_decision_ids,
)
from alphaswarm.types import FlipType, SignalType


def _record(decision_id: str, rationale: str) -> EpisodeRecord:
    return EpisodeRecord(
        decision_id=decision_id,
        agent_id="quants_01",
        rationale=rationale,
        peer_context_received="",
        flip_type=FlipType.NONE.value,
        round_num=1,
        cycle_id="c1",
    )


def test_episode_record_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _record("d1", "x").rationale = "y"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("prev", "curr", "expected"),
    [
        (None, SignalType.BUY, FlipType.NONE),
        (SignalType.BUY, SignalType.BUY, FlipType.NONE),
        (SignalType.PARSE_ERROR, SignalType.BUY, FlipType.NONE),
        (SignalType.BUY, SignalType.PARSE_ERROR, FlipType.NONE),
        (SignalType.BUY, SignalType.SELL, FlipType.BUY_TO_SELL),
        (SignalType.HOLD, SignalType.BUY, FlipType.HOLD_TO_BUY),
    ],
)
def test_compute_flip_type(prev: SignalType | None, curr: SignalType, expected: FlipType) -> None:
    assert compute_flip_type(prev, curr) is expected


def test_flip_type_vocabulary_is_none_plus_six_transitions() -> None:
    # Stored as a string on every RationaleEpisode (docs/DECISIONS.md#p11-d-06).
    assert {ft.value for ft in FlipType} == {
        "none",
        "buy_to_sell",
        "sell_to_buy",
        "buy_to_hold",
        "hold_to_buy",
        "sell_to_hold",
        "hold_to_sell",
    }


def test_match_entities_is_case_insensitive_token() -> None:
    records = [_record("d1", "zzzt holdings looks cheap"), _record("d2", "Nothing relevant")]
    entities = [EntityRef("ZZZT Holdings", "company"), EntityRef("QQQX Robotics", "company")]
    assert match_entities(records, entities) == [
        EntityMatch("d1", "ZZZT Holdings", "company", "token"),
    ]


def test_match_entities_preserves_record_then_entity_order() -> None:
    records = [_record("d1", "QQQX Robotics and ZZZT Holdings"), _record("d2", "ZZZT Holdings")]
    entities = [EntityRef("ZZZT Holdings", "company"), EntityRef("QQQX Robotics", "company")]
    assert [(m.decision_id, m.entity_name) for m in match_entities(records, entities)] == [
        ("d1", "ZZZT Holdings"),
        ("d1", "QQQX Robotics"),
        ("d2", "ZZZT Holdings"),
    ]


def test_empty_entity_name_matches_nothing() -> None:
    # "" is a substring of every string; a sloppy seed parse must not link everything.
    assert match_entities([_record("d1", "anything")], [EntityRef("", "company")]) == []


def test_new_decision_ids_are_distinct_uuid4() -> None:
    ids = new_decision_ids(3)
    assert len(set(ids)) == 3
    assert all(uuid.UUID(i).version == 4 for i in ids)
    assert new_decision_ids(0) == []
    with pytest.raises(ValueError):
        new_decision_ids(-1)
