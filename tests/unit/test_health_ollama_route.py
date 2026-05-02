"""NR-7: GET /api/health/ollama route tests.

The endpoint surfaces Ollama connection state to the frontend useOllamaHealth
hook so the UI can detect orchestrator-model unloads after macOS sleep without
parsing log lines. The endpoint MUST always return 200 (no propagation of
backend exceptions to the polling loop).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.routes.health import router as health_router


def _make_app(*, ollama_client: Any = None) -> FastAPI:
    app = FastAPI()
    app.include_router(health_router, prefix="/api")

    app_state = SimpleNamespace(ollama_client=ollama_client)
    app.state.app_state = app_state
    return app


def test_health_ollama_returns_connected_with_models() -> None:
    """ps() returns ProcessResponse-like object → connected=True with names."""
    fake_model = SimpleNamespace(name="alphaswarm-orchestrator")
    fake_response = SimpleNamespace(models=[fake_model])
    raw_client = SimpleNamespace(ps=AsyncMock(return_value=fake_response))
    ollama = SimpleNamespace(raw_client=raw_client)

    app = _make_app(ollama_client=ollama)
    r = TestClient(app).get("/api/health/ollama")

    assert r.status_code == 200
    body = r.json()
    assert body == {"connected": True, "models_loaded": ["alphaswarm-orchestrator"]}


def test_health_ollama_disconnected_when_client_none() -> None:
    """No ollama_client on app_state → connected=False, empty models."""
    app = _make_app(ollama_client=None)
    r = TestClient(app).get("/api/health/ollama")

    assert r.status_code == 200
    assert r.json() == {"connected": False, "models_loaded": []}


def test_health_ollama_disconnected_when_ps_raises() -> None:
    """ps() raises → caught defensively, returns connected=False."""

    async def _boom() -> Any:
        raise ConnectionError("ollama down")

    raw_client = SimpleNamespace(ps=_boom)
    ollama = SimpleNamespace(raw_client=raw_client)

    app = _make_app(ollama_client=ollama)
    r = TestClient(app).get("/api/health/ollama")

    assert r.status_code == 200
    assert r.json() == {"connected": False, "models_loaded": []}


def test_health_ollama_handles_dict_response() -> None:
    """Defensive path: ps() returns a dict shape (older ollama versions)."""
    raw_client = SimpleNamespace(
        ps=AsyncMock(return_value={"models": [{"name": "qwen3.5:7b"}, {"name": ""}]}),
    )
    ollama = SimpleNamespace(raw_client=raw_client)

    app = _make_app(ollama_client=ollama)
    r = TestClient(app).get("/api/health/ollama")

    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    # Empty-string entries are filtered out.
    assert body["models_loaded"] == ["qwen3.5:7b"]


@pytest.mark.parametrize("models_field", [None, []])
def test_health_ollama_empty_models(models_field: Any) -> None:
    """Empty / None models list → connected=True, empty array."""
    raw_client = SimpleNamespace(
        ps=AsyncMock(return_value=SimpleNamespace(models=models_field)),
    )
    ollama = SimpleNamespace(raw_client=raw_client)

    app = _make_app(ollama_client=ollama)
    r = TestClient(app).get("/api/health/ollama")

    assert r.status_code == 200
    body = r.json()
    assert body == {"connected": True, "models_loaded": []}
