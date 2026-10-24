"""persist_round rows for the exposure and holdout Decision properties (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from alphaswarm.graph import GraphStateManager, PersistRoundResult, schema_writes
from alphaswarm.types import AgentDecision, SignalType

AGENTS = ("quants_01", "degens_01", "macro_01")
DECISIONS = [
    ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.7, cited_agents=["degens_01"])),
    ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ("macro_01", AgentDecision(signal=SignalType.HOLD, confidence=0.5)),
]
NEW_KEYWORDS = ("exposures", "control_ids", "citations_invalid", "shock_treated_ids")


async def _rows(**kwargs: Any) -> dict[str, dict[str, Any]]:
    captured: list[tuple[Any, ...]] = []

    async def fake_write(fn: Any, *args: Any, op: str) -> Any:
        captured.append(args)
        rows = args[2]
        return PersistRoundResult(tuple(r["decision_id"] for r in rows), len(rows), 0, 0, 0, 0), ()

    await schema_writes.persist_round(
        fake_write,
        "c1",
        2,
        DECISIONS,
        decision_ids=["d1", "d2", "d3"],
        episodes=[],
        entity_matches=[],
        **kwargs,
    )
    return {row["agent_id"]: row for row in captured[0][2]}


async def test_legacy_call_records_unknowns_as_none() -> None:
    rows = await _rows()

    for agent in AGENTS:
        row = rows[agent]
        assert (row["peer_ids"], row["control"], row["citations_invalid"], row["shock_treated"]) == (
            None,
            False,
            None,
            None,
        )


async def test_new_keywords_become_decision_properties() -> None:
    rows = await _rows(
        exposures={"quants_01": ("degens_01", "macro_01"), "degens_01": ()},
        control_ids=frozenset({"degens_01"}),
        citations_invalid={"quants_01": 2},
        shock_treated_ids=frozenset({"quants_01"}),
    )

    assert [rows[a]["peer_ids"] for a in AGENTS] == [["degens_01", "macro_01"], [], []]
    assert [rows[a]["control"] for a in AGENTS] == [False, True, False]
    assert [rows[a]["citations_invalid"] for a in AGENTS] == [2, 0, 0]
    assert [rows[a]["shock_treated"] for a in AGENTS] == [True, False, False]


def test_facade_exposes_the_keywords() -> None:
    params = inspect.signature(GraphStateManager.persist_round).parameters

    for name in NEW_KEYWORDS:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY


async def test_facade_forwards_the_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake(write: Any, cycle_id: str, round_num: int, decisions: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return PersistRoundResult((), 0, 0, 0, 0, 0)

    monkeypatch.setattr(schema_writes, "persist_round", fake)
    await GraphStateManager(MagicMock(), []).persist_round(
        "c1",
        2,
        [],
        decision_ids=[],
        episodes=[],
        entity_matches=[],
        exposures={"a": ("b",)},
        control_ids=("a",),
        citations_invalid={"a": 1},
        shock_treated_ids=("b",),
    )

    assert seen["exposures"] == {"a": ("b",)}
    assert seen["control_ids"] == ("a",)
    assert seen["citations_invalid"] == {"a": 1}
    assert seen["shock_treated_ids"] == ("b",)
