"""Tests for the Origin/Referer allow-list guard on state-changing routes (CWE-352).

Motivating defect: every mutating API route (POST /api/simulate/stop,
POST /api/advisory/{cycle_id}, POST /api/replay/*, PUT /api/settings, ...) was
reachable by a cross-site HTML form post from any page the operator happened to
visit — the app had no auth, no CORS/TrustedHost middleware and no CSRF token,
and a body-less form POST is a CORS *simple* request that ships without a
preflight.

Two layers are covered here:
    1. The middleware's own policy, on a minimal app (allowed / foreign /
       missing / null origin, Referer fallback, safe methods untouched).
    2. Production wiring — the real create_app() must reject foreign-origin
       mutations on every router it registers (catches drift when a new
       router is added).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.origin_guard import (
    OriginGuardMiddleware,
    install_origin_guard,
    normalize_origin,
)

ALLOWED_ORIGIN = "http://localhost:5173"
ALLOWED_ORIGINS = (ALLOWED_ORIGIN, "http://127.0.0.1:8000")
FOREIGN_ORIGIN = "http://evil.example"


# ---------------------------------------------------------------------------
# Minimal guarded app — exercises the middleware policy without route state
# ---------------------------------------------------------------------------


def _make_guarded_app() -> FastAPI:
    """Build a tiny app with GET/POST/PUT on one path, behind the guard."""
    app = FastAPI()

    @app.get("/api/echo")
    async def echo_get() -> dict[str, str]:
        return {"method": "GET"}

    @app.post("/api/echo")
    async def echo_post() -> dict[str, str]:
        return {"method": "POST"}

    @app.put("/api/echo")
    async def echo_put() -> dict[str, str]:
        return {"method": "PUT"}

    install_origin_guard(app, ALLOWED_ORIGINS)
    return app


def test_post_with_allowed_origin_passes() -> None:
    """POST from the Vite dev origin reaches the route."""
    with TestClient(_make_guarded_app()) as client:
        r = client.post("/api/echo", headers={"origin": ALLOWED_ORIGIN})
        assert r.status_code == 200
        assert r.json() == {"method": "POST"}


def test_post_with_allowed_origin_case_insensitive() -> None:
    """Origin comparison folds scheme/host case (browsers may vary spelling)."""
    with TestClient(_make_guarded_app()) as client:
        r = client.post("/api/echo", headers={"origin": "HTTP://LocalHost:5173"})
        assert r.status_code == 200


def test_post_with_foreign_origin_rejected() -> None:
    """A drive-by page's POST is refused with 403 before the route runs."""
    with TestClient(_make_guarded_app()) as client:
        r = client.post("/api/echo", headers={"origin": FOREIGN_ORIGIN})
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "origin_not_allowed"


def test_post_with_allowed_host_but_foreign_port_rejected() -> None:
    """localhost on a non-allow-listed port is still a different origin."""
    with TestClient(_make_guarded_app()) as client:
        r = client.post("/api/echo", headers={"origin": "http://localhost:9999"})
        assert r.status_code == 403


def test_post_with_null_origin_rejected() -> None:
    """`Origin: null` (sandboxed iframe / Referrer-Policy: no-referrer) is refused."""
    with TestClient(_make_guarded_app()) as client:
        r = client.post("/api/echo", headers={"origin": "null"})
        assert r.status_code == 403


def test_post_without_origin_or_referer_allowed() -> None:
    """Header-less callers (curl, scripts/, TestClient) still work.

    Browsers always attach Origin to cross-origin POST, so allowing the
    header-less case closes no browser-reachable hole while keeping every
    non-browser caller functional.
    """
    with TestClient(_make_guarded_app()) as client:
        r = client.post("/api/echo")
        assert r.status_code == 200
        assert r.json() == {"method": "POST"}


def test_put_with_foreign_origin_rejected() -> None:
    """The guard covers every non-safe method, not just POST (PUT /api/settings)."""
    with TestClient(_make_guarded_app()) as client:
        assert client.put("/api/echo", headers={"origin": FOREIGN_ORIGIN}).status_code == 403
        assert client.put("/api/echo", headers={"origin": ALLOWED_ORIGIN}).status_code == 200


def test_get_with_foreign_origin_unaffected() -> None:
    """Safe methods are never guarded — read-only routes keep working."""
    with TestClient(_make_guarded_app()) as client:
        r = client.get("/api/echo", headers={"origin": FOREIGN_ORIGIN})
        assert r.status_code == 200
        assert r.json() == {"method": "GET"}
        # HEAD reaches the router too (which answers 405 here — FastAPI does
        # not auto-register HEAD for a GET route); the point is it is not 403.
        assert client.head("/api/echo", headers={"origin": FOREIGN_ORIGIN}).status_code != 403


def test_referer_fallback_when_origin_absent() -> None:
    """With no Origin header, Referer is validated the same way."""
    with TestClient(_make_guarded_app()) as client:
        allowed = client.post("/api/echo", headers={"referer": f"{ALLOWED_ORIGIN}/advisory"})
        assert allowed.status_code == 200
        foreign = client.post("/api/echo", headers={"referer": f"{FOREIGN_ORIGIN}/x"})
        assert foreign.status_code == 403


def test_origin_header_wins_over_referer() -> None:
    """A foreign Origin is not rescued by an allow-listed Referer."""
    with TestClient(_make_guarded_app()) as client:
        r = client.post(
            "/api/echo",
            headers={"origin": FOREIGN_ORIGIN, "referer": f"{ALLOWED_ORIGIN}/x"},
        )
        assert r.status_code == 403


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:5173", "http://localhost:5173"),
        ("HTTP://LOCALHOST:5173", "http://localhost:5173"),
        ("http://localhost:80", "http://localhost"),
        ("https://example.com:443/path?q=1", "https://example.com"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        ("null", None),
        ("", None),
        ("not a url", None),
    ],
)
def test_normalize_origin(raw: str, expected: str | None) -> None:
    """Origins normalise to scheme://host[:port]; non-origins yield None."""
    assert normalize_origin(raw) == expected


# ---------------------------------------------------------------------------
# Production wiring — create_app() must guard every registered router
# ---------------------------------------------------------------------------


def test_create_app_installs_origin_guard() -> None:
    """Production create_app() installs the guard middleware (wiring drift check)."""
    from alphaswarm.web.app import create_app as production_create_app

    prod_app = production_create_app()
    assert any(m.cls is OriginGuardMiddleware for m in prod_app.user_middleware), (
        "OriginGuardMiddleware missing from create_app(); state-changing routes are CSRF-reachable."
    )


# Every mutating route registered by create_app(), one per router.
_MUTATING_ROUTES = [
    ("POST", "/api/simulate/start"),
    ("POST", "/api/simulate/stop"),
    ("POST", "/api/simulate/shock"),
    ("POST", "/api/replay/start/cycle-1"),
    ("POST", "/api/replay/advance"),
    ("POST", "/api/replay/stop"),
    ("POST", "/api/interview/quants_01"),
    ("POST", "/api/report/cycle-1/generate"),
    ("POST", "/api/advisory/cycle-1"),
    ("PUT", "/api/settings"),
    ("POST", "/api/settings/test"),
]


@pytest.mark.parametrize(("method", "path"), _MUTATING_ROUTES)
def test_production_mutating_routes_reject_foreign_origin(method: str, path: str) -> None:
    """Foreign-origin mutations are refused on every router create_app() registers.

    The lifespan is intentionally not started (no Ollama/Neo4j needed): the
    guard runs before routing, so a rejected request never touches app.state.
    """
    from alphaswarm.web.app import create_app as production_create_app

    client = TestClient(production_create_app(), raise_server_exceptions=False)
    r = client.request(method, path, json={}, headers={"origin": FOREIGN_ORIGIN})
    assert r.status_code == 403, f"{method} {path} accepted a foreign origin"
    assert r.json()["detail"]["error"] == "origin_not_allowed"


@pytest.mark.parametrize(("method", "path"), _MUTATING_ROUTES)
def test_production_mutating_routes_accept_allowed_origin(method: str, path: str) -> None:
    """The SPA's own origin is never rejected by the guard.

    Without the lifespan these routes fail on missing app.state, so the
    assertion is only that the guard did NOT reject them (status != 403).
    """
    from alphaswarm.web.app import create_app as production_create_app

    client = TestClient(production_create_app(), raise_server_exceptions=False)
    r = client.request(method, path, json={}, headers={"origin": ALLOWED_ORIGIN})
    assert r.status_code != 403, f"{method} {path} rejected the SPA origin"


def test_production_get_route_unaffected_by_foreign_origin() -> None:
    """GET routes are not guarded — no read path changes behaviour."""
    from alphaswarm.web.app import create_app as production_create_app

    client = TestClient(production_create_app(), raise_server_exceptions=False)
    r = client.get("/api/health", headers={"origin": FOREIGN_ORIGIN})
    assert r.status_code != 403
