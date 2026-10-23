"""Whole-token entity matching (docs/DECISIONS.md#p11-d-08)."""

from __future__ import annotations

from alphaswarm.episodes import EntityRef, EpisodeRecord, match_entities

CYCLE = "00000000-0000-4000-8000-000000000001"


def _rec(decision_id: str, rationale: str) -> EpisodeRecord:
    return EpisodeRecord(
        decision_id=decision_id,
        agent_id="quants_01",
        rationale=rationale,
        peer_context_received="",
        flip_type="none",
        round_num=1,
        cycle_id=CYCLE,
    )


def test_short_name_matches_only_whole_tokens() -> None:
    records = [
        _rec("d1", "She said again that margins expand."),
        _rec("d2", "AI demand is the driver."),
        _rec("d3", "The ai-led rally continues."),
    ]

    matches = match_entities(records, [EntityRef(name="AI", type="sector")])

    assert [(m.decision_id, m.match_type) for m in matches] == [("d2", "token"), ("d3", "token")]


def test_common_word_prefixes_do_not_match() -> None:
    records = [
        _rec("d1", "The metadata looks fine."),
        _rec("d2", "federal policy is unclear."),
        _rec("d3", "Meta and the Fed both moved."),
    ]
    entities = [EntityRef(name="Meta", type="company"), EntityRef(name="Fed", type="person")]

    matches = match_entities(records, entities)

    assert [(m.decision_id, m.entity_name) for m in matches] == [("d3", "Meta"), ("d3", "Fed")]


def test_regex_metacharacters_match_literally() -> None:
    records = [
        _rec("d1", "C++ tooling and the S&P 500 rallied; AT&T flat."),
        _rec("d2", "C tooling only."),
    ]
    entities = [
        EntityRef(name="C++", type="sector"),
        EntityRef(name="S&P 500", type="sector"),
        EntityRef(name="AT&T", type="company"),
    ]

    matches = match_entities(records, entities)

    assert [(m.decision_id, m.entity_name) for m in matches] == [
        ("d1", "C++"),
        ("d1", "S&P 500"),
        ("d1", "AT&T"),
    ]


def test_name_under_two_types_is_skipped() -> None:
    entities = [
        EntityRef(name="ZZZT Holdings", type="company"),
        EntityRef(name="zzzt holdings", type="sector"),
    ]

    assert match_entities([_rec("d1", "ZZZT Holdings rallied.")], entities) == []


def test_same_type_case_variants_link_every_ref() -> None:
    entities = [
        EntityRef(name="ZZZT Holdings", type="company"),
        EntityRef(name="Zzzt Holdings", type="company"),
    ]

    matches = match_entities([_rec("d1", "zzzt holdings rallied.")], entities)

    assert [(m.entity_name, m.entity_type) for m in matches] == [
        ("ZZZT Holdings", "company"),
        ("Zzzt Holdings", "company"),
    ]


def test_possessive_and_repeat_mentions_give_one_match() -> None:
    records = [_rec("d1", "QQQX Robotics's backlog grew, per QQQX Robotics.")]

    matches = match_entities(records, [EntityRef(name="QQQX Robotics", type="company")])

    assert len(matches) == 1


def test_blank_names_are_ignored() -> None:
    assert match_entities([_rec("d1", "anything")], [EntityRef(name="  ", type="company")]) == []
