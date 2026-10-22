"""scripts/peer_exposure.py: exposure tables, invariant verdict, read-only queries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "peer_exposure.py"
# R2 slot counts of the legacy selector (docs/DECISIONS.md#adr-diverse-peer-context).
LEGACY_SLOTS = {"sell_side": 700, "narrators": 100, "institutions": 100, "event_driven": 100}


@pytest.fixture(scope="module")
def peer_exposure() -> ModuleType:
    spec = importlib.util.spec_from_file_location("peer_exposure_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _legacy_props(brackets: tuple[str, ...]) -> dict[str, Any]:
    props: dict[str, Any] = {"agent_count": 100, "r2_distinct_peers_shown": 46}
    for bracket in brackets:
        props[f"r2_exposure_{bracket}"] = LEGACY_SLOTS.get(bracket, 0)
        props[f"r2_readers_seeing_{bracket}"] = 100 if bracket in LEGACY_SLOTS else 0
    return props


class _FakeResult:
    def __init__(
        self, *, single: dict[str, Any] | None = None, data: list[dict[str, Any]] | None = None
    ) -> None:
        self._single = single
        self._data = data or []

    def single(self) -> dict[str, Any] | None:
        return self._single

    def data(self) -> list[dict[str, Any]]:
        return self._data


class _FakeSession:
    def __init__(self, props: dict[str, Any] | None, citation_rows: list[dict[str, Any]]) -> None:
        self._props = props
        self._rows = citation_rows
        self.queries: list[str] = []

    def run(self, query: str, **params: Any) -> _FakeResult:
        self.queries.append(query)
        if "properties(c)" in query:
            return _FakeResult(single=None if self._props is None else {"props": self._props})
        return _FakeResult(data=self._rows)


def test_legacy_feed_fails_the_invariant(peer_exposure: ModuleType) -> None:
    rounds = peer_exposure.exposure_rounds(
        _legacy_props(peer_exposure.BRACKETS), {2: {"sell_side": 70, "quants": 30}}
    )

    assert [r.round_num for r in rounds] == [2]
    (r2,) = rounds
    assert r2.total_slots == 1000
    assert r2.passes() is False
    sell_side = next(r for r in r2.rows if r.bracket == "sell_side")
    assert r2.slot_share(sell_side) == pytest.approx(0.7)
    assert r2.citation_share(sell_side) == pytest.approx(0.7)
    text = peer_exposure.format_round(r2, markdown=True)
    assert "| sell_side | 700 | 70.0% | 100% | 70.0% |" in text
    assert text.rstrip("\n").endswith("-> FAIL")


def test_markdown_keeps_each_table_and_verdict_in_its_own_block(
    peer_exposure: ModuleType,
) -> None:
    """GFM folds a line that directly follows a table into it, so blank lines separate blocks."""
    (r2,) = peer_exposure.exposure_rounds(_legacy_props(peer_exposure.BRACKETS), {})

    lines = peer_exposure.format_round(r2, markdown=True).split("\n")

    verdict = next(i for i, line in enumerate(lines) if line.startswith("R2: "))
    assert lines[verdict - 1] == ""
    assert lines[verdict - 2].startswith("| allocators |")
    assert lines[verdict + 1 :] == [""]  # print() adds the newline that ends the block


def test_balanced_feed_passes_both_rounds(peer_exposure: ModuleType) -> None:
    props: dict[str, Any] = {
        "agent_count": 100,
        "r2_distinct_peers_shown": 100,
        "r3_distinct_peers_shown": 99,
    }
    for n in (2, 3):
        for bracket in peer_exposure.BRACKETS:
            props[f"r{n}_exposure_{bracket}"] = 100
            props[f"r{n}_readers_seeing_{bracket}"] = 60

    rounds = peer_exposure.exposure_rounds(props, {})

    assert [r.round_num for r in rounds] == [2, 3]
    assert all(r.passes() for r in rounds)
    assert peer_exposure.format_round(rounds[1], markdown=False).endswith("PASS")


def test_cycle_without_exposure_keys_has_no_rounds(peer_exposure: ModuleType) -> None:
    assert peer_exposure.exposure_rounds({"agent_count": 100}, {}) == []


def test_read_cycle_parses_props_and_citations_read_only(peer_exposure: ModuleType) -> None:
    session = _FakeSession(
        {"agent_count": 100, "r2_distinct_peers_shown": 90},
        [
            {"round_num": 2, "bracket": "sell_side", "n": 7},
            {"round_num": 3, "bracket": "quants", "n": 4},
        ],
    )

    props, citations = peer_exposure._read_cycle(session, "00000000-0000-4000-8000-000000000001")

    assert props == {"agent_count": 100, "r2_distinct_peers_shown": 90}
    assert citations == {2: {"sell_side": 7}, 3: {"quants": 4}}
    write_words = ("CREATE", "MERGE", " SET ", "DELETE", "REMOVE")
    assert not any(word in query.upper() for query in session.queries for word in write_words)


def test_read_cycle_missing_cycle_stops_after_one_query(peer_exposure: ModuleType) -> None:
    session = _FakeSession(None, [])

    assert peer_exposure._read_cycle(session, "00000000-0000-4000-8000-000000000002") == (None, {})
    assert len(session.queries) == 1


def test_header_names_selector_version_mode_and_git(peer_exposure: ModuleType) -> None:
    header = peer_exposure._cycle_header(
        "00000000-0000-4000-8000-000000000003",
        {
            "peer_selection_version": 2,
            "inference_mode": "local",
            "worker_model": "alphaswarm-worker",
            "git_sha": "0123456789abcdef0123456789abcdef01234567",
            "r2_parse_errors": 0,
            "r3_parse_errors": 1,
        },
    )

    assert "peer_selection_version=2" in header
    assert "mode=local" in header
    assert "worker=alphaswarm-worker" in header
    assert "git=01234567" in header


def test_header_names_the_effective_peer_knobs(peer_exposure: ModuleType) -> None:
    """Before/after evidence must show that both cycles ran one peer configuration."""
    header = peer_exposure._cycle_header(
        "00000000-0000-4000-8000-000000000004",
        {
            "peer_limit": 10,
            "peer_min_brackets": 4,
            "peer_personal_boost": 0.3,
            "peer_budget_chars": 4000,
            "peer_seed_source": "cycle_id",
        },
    )

    assert header.rstrip("\n").split("\n")[-1] == (
        "peers: limit=10 min_brackets=4 bracket_cap=- personal_boost=0.3"
        " budget_chars=4000 seed_source=cycle_id"
    )
    assert header.endswith("\n")  # print() adds the blank line before the first table
