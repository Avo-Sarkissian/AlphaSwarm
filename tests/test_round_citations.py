"""read_round_citations: Round 1 has no peer context, so it never queries."""

from __future__ import annotations

from typing import Any

from alphaswarm.graph import analytics

CYCLE = "00000000-0000-4000-8000-0000000000a1"


async def test_round_one_returns_empty_without_a_read() -> None:
    calls: list[str] = []

    async def fake_read(fn: Any, *args: Any, op: str) -> list[Any]:
        calls.append(op)
        return []

    assert await analytics.read_round_citations(fake_read, CYCLE, 1) == []
    assert calls == []


async def test_later_rounds_read_once_under_their_op_name() -> None:
    seen: list[tuple[str, tuple[Any, ...]]] = []

    async def fake_read(fn: Any, *args: Any, op: str) -> list[dict[str, str]]:
        seen.append((op, args))
        return [{"source_id": "quants_01", "target_id": "sell_side_01", "cited_signal": "sell"}]

    rows = await analytics.read_round_citations(fake_read, CYCLE, 2)

    assert seen == [("read_round_citations", (CYCLE, 2))]
    assert rows == [{"source_id": "quants_01", "target_id": "sell_side_01", "cited_signal": "sell"}]
