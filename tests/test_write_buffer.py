"""Unit tests for WriteBuffer (Plan 11-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from alphaswarm.episodes import EpisodeRecord
from alphaswarm.types import FlipType
from alphaswarm.write_buffer import WriteBuffer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record(
    decision_id: str = "dec-001",
    agent_id: str = "agent-01",
    round_num: int = 1,
    cycle_id: str = "cycle-abc",
) -> EpisodeRecord:
    return EpisodeRecord(
        decision_id=decision_id,
        agent_id=agent_id,
        rationale="Agent sees upside risk.",
        peer_context_received="",
        flip_type=FlipType.NONE.value,
        round_num=round_num,
        cycle_id=cycle_id,
    )


# ---------------------------------------------------------------------------
# WriteBuffer push / drain tests
# ---------------------------------------------------------------------------


async def test_buffer_push_and_drain() -> None:
    buf = WriteBuffer(maxsize=10)
    r1 = make_record(decision_id="d1")
    r2 = make_record(decision_id="d2")
    await buf.push(r1)
    await buf.push(r2)
    drained = buf.drain()
    assert len(drained) == 2
    assert drained[0].decision_id == "d1"
    assert drained[1].decision_id == "d2"


async def test_buffer_drain_empty_queue_returns_empty_list() -> None:
    buf = WriteBuffer(maxsize=10)
    assert buf.drain() == []


async def test_buffer_drain_empties_queue() -> None:
    buf = WriteBuffer(maxsize=10)
    await buf.push(make_record())
    buf.drain()
    assert buf.drain() == []


async def test_buffer_full_drops_oldest() -> None:
    buf = WriteBuffer(maxsize=2)
    r1 = make_record(decision_id="old-1")
    r2 = make_record(decision_id="old-2")
    r3 = make_record(decision_id="new-3")
    await buf.push(r1)
    await buf.push(r2)
    await buf.push(r3)  # should drop r1, keep r2 and r3
    drained = buf.drain()
    ids = [r.decision_id for r in drained]
    assert "old-1" not in ids
    assert "old-2" in ids
    assert "new-3" in ids


# ---------------------------------------------------------------------------
# WriteBuffer flush tests
# ---------------------------------------------------------------------------


async def test_buffer_flush_returns_zero_on_empty() -> None:
    buf = WriteBuffer(maxsize=10)
    mock_gm = MagicMock()
    count = await buf.flush(mock_gm, entity_names=["ACME"])
    assert count == 0
    mock_gm.write_rationale_episodes.assert_not_called()
    mock_gm.write_narrative_edges.assert_not_called()


async def test_buffer_flush_calls_graph_manager_and_returns_count() -> None:
    buf = WriteBuffer(maxsize=10)
    r1 = make_record(decision_id="d1")
    r2 = make_record(decision_id="d2")
    await buf.push(r1)
    await buf.push(r2)

    mock_gm = MagicMock()
    mock_gm.write_rationale_episodes = AsyncMock(return_value=None)
    mock_gm.write_narrative_edges = AsyncMock(return_value=None)

    count = await buf.flush(mock_gm, entity_names=["ACME", "Tesla"])

    assert count == 2
    mock_gm.write_rationale_episodes.assert_called_once()
    mock_gm.write_narrative_edges.assert_called_once()


async def test_buffer_flush_passes_records_to_write_rationale_episodes() -> None:
    buf = WriteBuffer(maxsize=10)
    r1 = make_record(decision_id="d1")
    await buf.push(r1)

    mock_gm = MagicMock()
    mock_gm.write_rationale_episodes = AsyncMock(return_value=None)
    mock_gm.write_narrative_edges = AsyncMock(return_value=None)

    await buf.flush(mock_gm, entity_names=["ACME"])

    call_args = mock_gm.write_rationale_episodes.call_args
    records_passed = call_args[0][0]
    assert len(records_passed) == 1
    assert records_passed[0].decision_id == "d1"


async def test_buffer_flush_passes_entity_names_to_write_narrative_edges() -> None:
    buf = WriteBuffer(maxsize=10)
    await buf.push(make_record())

    mock_gm = MagicMock()
    mock_gm.write_rationale_episodes = AsyncMock(return_value=None)
    mock_gm.write_narrative_edges = AsyncMock(return_value=None)

    entity_names = ["ACME", "Tesla", "Goldman"]
    await buf.flush(mock_gm, entity_names=entity_names)

    call_args = mock_gm.write_narrative_edges.call_args
    assert call_args[0][1] == entity_names
