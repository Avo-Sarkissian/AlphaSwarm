"""Smoke: auto-applied enable_socket marker actually unblocks sockets."""

from __future__ import annotations

import socket


def test_auto_marker_allows_socket_creation() -> None:
    """If tests/integration/conftest.py's hook works, socket creation succeeds.

    If this ever raises pytest_socket.SocketBlockedError, the hook is broken.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    assert s is not None
    s.close()
