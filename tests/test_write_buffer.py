"""Unit tests for WriteBuffer, EpisodeRecord, and compute_flip_type (Plan 11-01)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.types import FlipType, SignalType
from alphaswarm.write_buffer import EpisodeRecord, WriteBuffer, compute_flip_type


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
# FlipType enum tests
# ---------------------------------------------------------------------------


def test_flip_type_has_seven_values() -> None:
    assert len(FlipType) == 7


def test_flip_type_string_construction() -> None:
    assert FlipType("none") == FlipType.NONE
    assert FlipType("buy_to_sell") == FlipType.BUY_TO_SELL


def test_flip_type_all_values_accessible() -> None:
    expected = {
        "none",
        "buy_to_sell",
        "sell_to_buy",
        "buy_to_hold",
        "hold_to_buy",
        "sell_to_hold",
        "hold_to_sell",
    }
    assert {ft.value for ft in FlipType} == expected


# ---------------------------------------------------------------------------
# compute_flip_type tests
# ---------------------------------------------------------------------------


def test_flip_type_buy_to_sell() -> None:
    assert compute_flip_type(SignalType.BUY, SignalType.SELL) == FlipType.BUY_TO_SELL


def test_flip_type_sell_to_buy() -> None:
    assert compute_flip_type(SignalType.SELL, SignalType.BUY) == FlipType.SELL_TO_BUY


def test_flip_type_buy_to_hold() -> None:
    assert compute_flip_type(SignalType.BUY, SignalType.HOLD) == FlipType.BUY_TO_HOLD


def test_flip_type_hold_to_buy() -> None:
    assert compute_flip_type(SignalType.HOLD, SignalType.BUY) == FlipType.HOLD_TO_BUY


def test_flip_type_sell_to_hold() -> None:
    assert compute_flip_type(SignalType.SELL, SignalType.HOLD) == FlipType.SELL_TO_HOLD


def test_flip_type_hold_to_sell() -> None:
    assert compute_flip_type(SignalType.HOLD, SignalType.SELL) == FlipType.HOLD_TO_SELL


def test_flip_type_none_when_prev_is_none() -> None:
    """Round 1: no previous signal -> NONE."""
    assert compute_flip_type(None, SignalType.BUY) == FlipType.NONE


def test_flip_type_none_when_same_signal() -> None:
    assert compute_flip_type(SignalType.BUY, SignalType.BUY) == FlipType.NONE
    assert compute_flip_type(SignalType.SELL, SignalType.SELL) == FlipType.NONE
    assert compute_flip_type(SignalType.HOLD, SignalType.HOLD) == FlipType.NONE


def test_flip_type_none_when_prev_is_parse_error() -> None:
    assert compute_flip_type(SignalType.PARSE_ERROR, SignalType.BUY) == FlipType.NONE


def test_flip_type_none_when_curr_is_parse_error() -> None:
    assert compute_flip_type(SignalType.BUY, SignalType.PARSE_ERROR) == FlipType.NONE


# ---------------------------------------------------------------------------
# EpisodeRecord tests
# ---------------------------------------------------------------------------


def test_episode_record_is_frozen() -> None:
    record = make_record()
    with pytest.raises((AttributeError, TypeError)):
        record.agent_id = "mutated"  # type: ignore[misc]


def test_episode_record_fields() -> None:
    record = EpisodeRecord(
        decision_id="dec-x",
        agent_id="ag-5",
        rationale="Bull case clear.",
        peer_context_received="peer said sell",
        flip_type=FlipType.SELL_TO_BUY.value,
        round_num=2,
        cycle_id="cy-99",
    )
    assert record.decision_id == "dec-x"
    assert record.agent_id == "ag-5"
    assert record.rationale == "Bull case clear."
    assert record.peer_context_received == "peer said sell"
    assert record.flip_type == "sell_to_buy"
    assert record.round_num == 2
    assert record.cycle_id == "cy-99"


# ---------------------------------------------------------------------------
# WriteBuffer push / drain tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_buffer_drain_empty_queue_returns_empty_list() -> None:
    buf = WriteBuffer(maxsize=10)
    assert buf.drain() == []


@pytest.mark.asyncio
async def test_buffer_drain_empties_queue() -> None:
    buf = WriteBuffer(maxsize=10)
    await buf.push(make_record())
    buf.drain()
    assert buf.drain() == []


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_buffer_flush_returns_zero_on_empty() -> None:
    buf = WriteBuffer(maxsize=10)
    mock_gm = MagicMock()
    count = await buf.flush(mock_gm, entity_names=["ACME"])
    assert count == 0
    mock_gm.write_rationale_episodes.assert_not_called()
    mock_gm.write_narrative_edges.assert_not_called()


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
