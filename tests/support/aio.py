"""Small asyncio helpers for deterministic concurrency tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


async def eventually(predicate: Callable[[], bool], *, max_yields: int = 200, what: str = "condition") -> None:
    """Yield to the event loop until ``predicate()`` is true.

    Only ``asyncio.sleep(0)`` is used, so this never waits on wall-clock time and
    stays compatible with the engine's ``forbid_real_sleep`` guard. After
    ``max_yields`` loop turns it fails the test with an AssertionError naming
    ``what``.
    """
    for _ in range(max_yields):
        if predicate():
            return
        await asyncio.sleep(0)
    if not predicate():
        raise AssertionError(f"{what} did not become true within {max_yields} event-loop turns")
