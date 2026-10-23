"""ISOL-06: pytest-socket gate smoke tests (docs/DECISIONS.md#adr-test-network-gate).

The tripwires accept only pytest_socket.SocketBlockedError. Accepting OSError
let them pass when the gate was off and a connect merely failed
(ConnectionRefusedError), so they could never fail.
"""

from __future__ import annotations

import socket

import pytest
import pytest_socket


def test_raw_socket_creation_is_blocked() -> None:
    """docs/DECISIONS.md#p37-d-09: creating any INET socket must fail under --disable-socket."""
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_loopback_connect_is_blocked_by_default() -> None:
    """docs/DECISIONS.md#p37-d-10: loopback is not an allow-listed escape; the block happens at creation."""
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.create_connection(("127.0.0.1", 65432), timeout=0.1)


@pytest.mark.enable_socket
def test_enable_socket_marker_allows_raw_socket_creation() -> None:
    """docs/DECISIONS.md#adr-test-network-gate: @pytest.mark.enable_socket re-enables socket access."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    assert s is not None
    s.close()
