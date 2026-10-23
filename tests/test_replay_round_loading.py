"""Replay manager API and round loading."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from alphaswarm.errors import Neo4jQueryError
from alphaswarm.state import AgentState, StateStore
from alphaswarm.types import SignalType
from alphaswarm.web.replay_manager import ReplayManager

CYCLE = "00000000-0000-4000-8000-0000000000a1"
SIGNALS = {
    ("quants_01", 1): AgentState(signal=SignalType.BUY, confidence=0.8),
    ("quants_01", 2): AgentState(signal=SignalType.SELL, confidence=0.6),
    ("quants_01", 3): AgentState(signal=SignalType.HOLD, confidence=0.5),
}


class RoundGraph:
    """Replay reads with distinct rows per round; one round can fail or pause."""

    def __init__(self, *, fail_round: int | None = None, gate_round: int | None = None) -> None:
        self.fail_round = fail_round
        self.gate_round = gate_round
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.reads: list[tuple[str, int]] = []

    async def read_bracket_narratives_for_round(
        self,
        cycle_id: str,
        round_num: int,
    ) -> list[dict[str, object]]:
        self.reads.append(("brackets", round_num))
        return [
            {
                "bracket": "quants",
                "buy_count": round_num,
                "sell_count": 0,
                "hold_count": 0,
                "total": round_num,
                "avg_confidence": 0.5,
                "avg_sentiment": 0.0,
            }
        ]

    async def read_rationale_entries_for_round(
        self,
        cycle_id: str,
        round_num: int,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        self.reads.append(("rationales", round_num))
        if round_num == self.gate_round:
            self.entered.set()
            await self.release.wait()
        if round_num == self.fail_round:
            raise Neo4jQueryError("simulated read failure", op="read_rationale_entries_for_round")
        return [
            {
                "agent_id": "quants_01",
                "signal": "buy",
                "rationale": f"round {round_num} view",
                "round_num": round_num,
            }
        ]


def new_manager() -> ReplayManager:
    return ReplayManager(SimpleNamespace(state_store=StateStore()))  # type: ignore[arg-type]


async def test_replay_api_takes_no_connection_manager() -> None:
    manager = new_manager()
    graph = RoundGraph()
    await manager.start(CYCLE, SIGNALS, graph)  # type: ignore[arg-type]
    assert await manager.advance(graph) == 2  # type: ignore[arg-type]
    await manager.stop()
    assert not manager.is_active
    assert not hasattr(manager, "seed_rumor")


def shown(manager: ReplayManager) -> tuple[int, int, int, set[int]]:
    """(manager round, streamed round, quants buy_count, rationale rounds) as a frame shows them."""
    snap = manager.store.snapshot()
    quants_buy = next(b.buy_count for b in snap.bracket_summaries if b.bracket == "quants")
    return manager.round_num, snap.round_num, quants_buy, {e.round_num for e in snap.rationale_entries}


async def test_failed_advance_keeps_the_previous_round() -> None:
    manager = new_manager()
    graph = RoundGraph(fail_round=2)
    await manager.start(CYCLE, SIGNALS, graph)  # type: ignore[arg-type]
    with pytest.raises(Neo4jQueryError):
        await manager.advance(graph)  # type: ignore[arg-type]
    assert shown(manager) == (1, 1, 1, {1})


async def test_pending_advance_never_shows_a_mixed_round() -> None:
    manager = new_manager()
    graph = RoundGraph(gate_round=2)
    await manager.start(CYCLE, SIGNALS, graph)  # type: ignore[arg-type]
    task = asyncio.create_task(manager.advance(graph))  # type: ignore[arg-type]
    await graph.entered.wait()
    assert shown(manager) == (1, 1, 1, {1})
    graph.release.set()
    assert await task == 2
    assert shown(manager) == (2, 2, 2, {2})


async def test_advance_retries_after_a_failure() -> None:
    manager = new_manager()
    graph = RoundGraph(fail_round=2)
    await manager.start(CYCLE, SIGNALS, graph)  # type: ignore[arg-type]
    with pytest.raises(Neo4jQueryError):
        await manager.advance(graph)  # type: ignore[arg-type]
    graph.fail_round = None
    assert await manager.advance(graph) == 2  # type: ignore[arg-type]
    assert shown(manager) == (2, 2, 2, {2})


async def test_failed_start_leaves_no_replay() -> None:
    manager = new_manager()
    with pytest.raises(Neo4jQueryError):
        await manager.start(CYCLE, SIGNALS, RoundGraph(fail_round=1))  # type: ignore[arg-type]
    assert not manager.is_active
    assert not manager.has_store


async def test_advance_stops_at_the_cycle_depth() -> None:
    two_rounds = {key: state for key, state in SIGNALS.items() if key[1] <= 2}
    manager = new_manager()
    graph = RoundGraph()
    await manager.start(CYCLE, two_rounds, graph)  # type: ignore[arg-type]
    assert await manager.advance(graph) == 2  # type: ignore[arg-type]
    assert await manager.advance(graph) == 2  # type: ignore[arg-type]
    assert ("brackets", 3) not in graph.reads
