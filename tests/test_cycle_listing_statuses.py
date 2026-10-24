"""read_completed_cycles accepts a status filter."""

from __future__ import annotations

from typing import Any

import pytest

from alphaswarm.graph import replay_interview


async def test_statuses_reach_the_query_sorted() -> None:
    seen: list[tuple[Any, ...]] = []

    async def fake_read(fn: Any, *args: Any, op: str) -> list[Any]:
        seen.append(args)
        return []

    await replay_interview.read_completed_cycles(fake_read, 5, statuses=("failed", "complete"))
    await replay_interview.read_completed_cycles(fake_read, 5)

    assert seen[0][-1] == ["complete", "failed"]
    assert seen[1][-1] == ["complete"]


@pytest.mark.parametrize("statuses", [(), ("done",), ("complete", "archived")])
async def test_bad_statuses_are_rejected(statuses: tuple[str, ...]) -> None:
    async def fake_read(fn: Any, *args: Any, op: str) -> list[Any]:
        raise AssertionError("must not read")

    with pytest.raises(ValueError, match="statuses"):
        await replay_interview.read_completed_cycles(fake_read, statuses=statuses)  # type: ignore[arg-type]
