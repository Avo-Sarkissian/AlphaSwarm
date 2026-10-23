"""TrustedHost rejects foreign Host headers on HTTP and the WebSocket.

A DNS-rebinding page re-points its own name at 127.0.0.1, but the browser still
sends that name as Host. These tests build the real create_app() without running
its lifespan: the Host check runs before routing, so a rejected request never
touches app.state.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.testclient import WebSocketDenialResponse

from alphaswarm.config import DEFAULT_TRUSTED_HOSTS, AppSettings
from alphaswarm.web.app import create_app
from alphaswarm.web.origin_guard import OriginGuardMiddleware


def test_trusted_host_is_the_outermost_middleware(web_test_settings: AppSettings) -> None:
    app = create_app(web_test_settings)
    assert app.user_middleware[0].cls is TrustedHostMiddleware
    assert app.user_middleware[1].cls is OriginGuardMiddleware
    assert app.user_middleware[0].kwargs["allowed_hosts"] == [*DEFAULT_TRUSTED_HOSTS, "testserver"]


def test_foreign_host_gets_400_on_get_holdings(web_test_settings: AppSettings) -> None:
    """A rebinding page cannot read the holdings."""
    client = TestClient(create_app(web_test_settings), raise_server_exceptions=False)
    r = client.get("/api/holdings", headers={"host": "attacker.example:8000"})
    assert r.status_code == 400
    assert r.text == "Invalid host header"


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "localhost:5173", "localhost"])
def test_loopback_hosts_pass_the_host_check(web_test_settings: AppSettings, host: str) -> None:
    """The Vite proxy (changeOrigin, Host localhost:8000) and loopback work."""
    client = TestClient(create_app(web_test_settings), raise_server_exceptions=False)
    assert client.get("/api/health/live", headers={"host": host}).status_code == 200


def test_foreign_host_websocket_handshake_is_refused(web_test_settings: AppSettings) -> None:
    """The live stream is closed to a rebinding page."""
    client = TestClient(create_app(web_test_settings))
    with (
        pytest.raises(WebSocketDenialResponse) as excinfo,
        client.websocket_connect(
            "/ws/state",
            headers={"host": "attacker.example:8000", "origin": "http://attacker.example:8000"},
        ),
    ):
        pass
    assert excinfo.value.status_code == 400


def test_lan_host_needs_explicit_opt_in(web_test_settings: AppSettings) -> None:
    """A LAN address is refused until it is added to trusted_hosts."""
    lan = {"host": "192.168.1.20:8000"}
    blocked = TestClient(create_app(web_test_settings), raise_server_exceptions=False)
    assert blocked.get("/api/health/live", headers=lan).status_code == 400
    opened = web_test_settings.model_copy(
        update={"trusted_hosts": (*web_test_settings.trusted_hosts, "192.168.1.20")},
    )
    allowed = TestClient(create_app(opened), raise_server_exceptions=False)
    assert allowed.get("/api/health/live", headers=lan).status_code == 200
