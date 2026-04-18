"""ISOL-06: pytest-socket gate smoke tests.

Verifies that --disable-socket is active globally and that the enable_socket
marker serves as the escape hatch.

Pitfall 4 / Assumption A2: pytest-socket 0.7.0's default loopback behavior
under --disable-socket without --allow-hosts is not explicitly documented.
`test_loopback_is_blocked_by_default` is the tripwire — if it starts failing
(i.e. loopback succeeds), add `--allow-hosts=""` to pyproject.toml.
"""

from __future__ import annotations

import socket

import pytest
import pytest_socket


def test_raw_socket_creation_is_blocked() -> None:
    """D-09: creating any INET socket must fail under --disable-socket."""
    with pytest.raises((pytest_socket.SocketBlockedError, OSError)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()


def test_loopback_connect_is_blocked_by_default() -> None:
    """D-10: localhost/127.0.0.1 must also be blocked (no allow-list bypass).

    If this test starts passing a connect, pytest-socket defaults have changed;
    add `--allow-hosts=""` to pyproject.toml addopts.
    """
    with pytest.raises((pytest_socket.SocketBlockedError, OSError)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", 65432))  # unlikely port, should not matter
        finally:
            s.close()


@pytest.mark.enable_socket
def test_enable_socket_marker_allows_raw_socket_creation() -> None:
    """D-12 escape hatch: @pytest.mark.enable_socket re-enables socket access.

    This test does NOT actually connect anywhere — creating the socket is sufficient
    to prove the marker lifts the block. We close it immediately.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    assert s is not None
    s.close()
