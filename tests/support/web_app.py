"""Helpers for web route tests: fixed cycle ids and a fake graph.

Every value here is fictional.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

CYCLE_A: Final = "00000000-0000-4000-8000-0000000000a1"
CYCLE_B: Final = "00000000-0000-4000-8000-0000000000b2"
CYCLE_UNKNOWN: Final = "00000000-0000-4000-8000-0000000000ff"


class FakeCycleGraph:
    """Minimal GraphStateManager stand-in for the gating reads."""

    def __init__(
        self,
        statuses: Mapping[str, str] | None = None,
        *,
        latest: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.statuses: dict[str, str] = dict(statuses or {})
        self.latest = latest
        self.error = error
        self.status_calls: list[str] = []

    async def read_cycle_status(self, cycle_id: str) -> str | None:
        self.status_calls.append(cycle_id)
        if self.error is not None:
            raise self.error
        return self.statuses.get(cycle_id)

    async def cycle_exists(self, cycle_id: str) -> bool:
        return await self.read_cycle_status(cycle_id) is not None

    async def read_latest_cycle_id(self, *, statuses: Sequence[str] = ("complete",)) -> str | None:
        if self.error is not None:
            raise self.error
        return self.latest

    async def close(self) -> None:
        return None
