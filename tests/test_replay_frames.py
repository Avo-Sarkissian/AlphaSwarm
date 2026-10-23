"""Replay sends the same versioned StateFrame (docs/DECISIONS.md#adr-replaystore-separate)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from alphaswarm.state import AgentState, JobStatus, StateStore
from alphaswarm.types import SignalType
from alphaswarm.web.broadcaster import snapshot_to_json
from alphaswarm.web.replay_manager import ReplayManager, _rationale_entries_from_rows

CYCLE = "00000000-0000-4000-8000-0000000000c3"
SIGNALS = {
    ("quants_01", 1): AgentState(SignalType.BUY, 0.8),
    ("quants_01", 2): AgentState(SignalType.SELL, 0.6),
}


def _row(agent_id: str, signal: str, round_num: int) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "signal": signal,
        "rationale": "fictional",
        "round_num": round_num,
    }


class _ReplayGraph:
    """Only the two per-round reads ReplayManager makes."""

    def __init__(self, rationale_rows: dict[int, list[dict[str, Any]]]) -> None:
        self._rows = rationale_rows

    async def read_bracket_narratives_for_round(self, cycle_id: str, round_num: int) -> list[dict[str, Any]]:
        return []

    async def read_rationale_entries_for_round(
        self, cycle_id: str, round_num: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self._rows.get(round_num, [])


def test_rationale_rows_are_numbered_per_round_without_wall_clock() -> None:
    entries = _rationale_entries_from_rows([_row("quants_01", "buy", 1), _row("degens_02", "sell", 1)])
    assert [(e.seq, e.ts, e.agent_id, e.signal) for e in entries] == [
        (1, 0.0, "quants_01", SignalType.BUY),
        (2, 0.0, "degens_02", SignalType.SELL),
    ]


async def test_replay_start_and_advance_serve_versioned_frames() -> None:
    live = StateStore()
    live.set_job_status("report", JobStatus("running", CYCLE))
    manager = ReplayManager(SimpleNamespace(state_store=live))  # type: ignore[arg-type]
    graph = _ReplayGraph(
        {
            1: [_row("quants_01", "buy", 1), _row("degens_02", "sell", 1)],
            2: [_row("macro_03", "hold", 2)],
        }
    )

    await manager.start(CYCLE, SIGNALS, graph)  # type: ignore[arg-type]
    first = json.loads(snapshot_to_json(live, manager))
    assert (first["schema_version"], first["mode"], first["phase"]) == (1, "replay", "replay")
    assert (first["cycle_id"], first["num_rounds"], first["round_num"], first["edges_version"]) == (
        CYCLE,
        2,
        1,
        0,
    )
    assert [(e["seq"], e["ts"], e["agent_id"]) for e in first["rationale_entries"]] == [
        (1, 0.0, "quants_01"),
        (2, 0.0, "degens_02"),
    ]
    assert first["jobs"]["report"] == {"state": "running", "cycle_id": CYCLE, "error_code": None}

    assert await manager.advance(graph) == 2  # type: ignore[arg-type]
    second = json.loads(snapshot_to_json(live, manager))
    assert (second["round_num"], second["edges_version"]) == (2, 1)
    assert [(e["seq"], e["agent_id"]) for e in second["rationale_entries"]] == [(1, "macro_03")]
    assert second["agent_states"] == {"quants_01": {"signal": "sell", "confidence": 0.6}}
