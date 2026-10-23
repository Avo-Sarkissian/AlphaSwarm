"""Marker-driven network policy for the test suite.

Sockets are disabled globally (``--disable-socket``). A test opts in by marker, never by
its path: ``neo4j``, ``live_network`` and ``ollama`` get ``enable_socket``; ``neo4j`` async
tests share the session event loop with the session-scoped driver; ``live_network`` and
``ollama`` tests are skipped unless ``--run-live`` is given.
See docs/DECISIONS.md#adr-test-network-gate.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Final

import pytest

SOCKET_MARKERS: Final[frozenset[str]] = frozenset({"neo4j", "live_network", "ollama"})
LIVE_MARKERS: Final[frozenset[str]] = frozenset({"live_network", "ollama"})
RUN_LIVE_OPTION: Final = "--run-live"
_SKIP_LIVE: Final = pytest.mark.skip(reason="live test: pass --run-live to run it")


def apply_marker_policy(items: Iterable[pytest.Item], *, run_live: bool) -> None:
    """Apply the socket, event-loop and live-skip rules to collected items (in place)."""
    for item in items:
        names = {mark.name for mark in item.iter_markers()}
        if names & SOCKET_MARKERS:
            item.add_marker(pytest.mark.enable_socket)
        if "neo4j" in names and inspect.iscoroutinefunction(getattr(item, "obj", None)):
            # Prepend so it wins over a bare @pytest.mark.asyncio() on the test itself.
            item.add_marker(pytest.mark.asyncio(loop_scope="session"), append=False)
        if names & LIVE_MARKERS and not run_live:
            item.add_marker(_SKIP_LIVE)
