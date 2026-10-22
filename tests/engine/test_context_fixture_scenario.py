"""A fixture's block reaches Round 1 prompts (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphaswarm.ingestion.fixture import build_fixture_packet

PACKET = build_fixture_packet(
    event_id="evt-001",
    as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
    ticker="ZZZT",
    close=Decimal("123.45"),
    volume=1_000_000,
    headlines=("ZZZT Holdings names a new chief executive (fictional)",),
)


def _text(call: Any) -> str:
    return "\n".join(str(message["content"]) for message in call.messages)


def _round1(worker: Any) -> list[Any]:
    return [c for c in worker.calls_for("decision") if c.round_num == 1]


async def test_round1_prompts_carry_the_fixture_block(
    run_scenario: Any, scripted_worker: Any
) -> None:
    await run_scenario(num_rounds=2, context_fixture=PACKET)
    round1 = _round1(scripted_worker)
    assert len(round1) == 100
    assert all("== ZZZT ==" in _text(c) and "Price: $123.45" in _text(c) for c in round1)


async def test_no_fixture_and_no_providers_send_no_block(
    run_scenario: Any, scripted_worker: Any
) -> None:
    await run_scenario(num_rounds=2)
    assert not any("Price: $123.45" in _text(c) for c in _round1(scripted_worker))
