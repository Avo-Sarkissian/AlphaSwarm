"""/api/health components, degraded status, cache, self-heal; /api/health/live."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.web.routes.health as health_module
from alphaswarm.config import InferenceConfig, ProviderType, RoleConfig, save_inference_config
from alphaswarm.readiness import ComponentStatus
from alphaswarm.web.routes.health import router as health_router
from tests.support.web_app import make_route_app, route_test_settings


class _Probes:
    def __init__(
        self, neo4j_ok: bool = True, missing: tuple[str, ...] = (), ollama_ok: bool = True
    ) -> None:
        self.neo4j_ok = neo4j_ok
        self.missing = missing
        self.ollama_ok = ollama_ok
        self.neo4j_calls = 0
        self.ollama_calls: list[tuple[tuple[str, ...], bool]] = []

    async def neo4j(self, gm: object, **_: Any) -> ComponentStatus:
        self.neo4j_calls += 1
        if self.neo4j_ok:
            return ComponentStatus("neo4j", ok=True, required=True)
        return ComponentStatus(
            "neo4j",
            ok=False,
            required=True,
            detail="unreachable (X)",
            fix="docker compose up -d neo4j",
        )

    async def ollama(
        self, client: object, aliases: Any, *, required: bool, **_: Any
    ) -> tuple[ComponentStatus, ComponentStatus]:
        self.ollama_calls.append((tuple(aliases), required))
        ollama = ComponentStatus("ollama", ok=self.ollama_ok, required=required)
        if self.missing:
            return ollama, ComponentStatus(
                "aliases",
                ok=False,
                required=required,
                detail="missing: " + ", ".join(self.missing),
                fix="ollama create alphaswarm-worker -f modelfiles/Modelfile.worker",
                missing=self.missing,
            )
        return ollama, ComponentStatus("aliases", ok=True, required=required)


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probes: _Probes) -> FastAPI:
    monkeypatch.setattr(health_module, "check_neo4j", probes.neo4j)
    monkeypatch.setattr(health_module, "check_ollama", probes.ollama)
    return make_route_app(health_router, settings=route_test_settings(tmp_path), graph=AsyncMock())


def test_all_components_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probes = _Probes()
    with TestClient(_app(tmp_path, monkeypatch, probes)) as client:
        data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert set(data["components"]) == {"neo4j", "ollama", "aliases"}
    assert data["components"]["neo4j"] == {
        "ok": True,
        "required": True,
        "detail": None,
        "fix": None,
        "missing": [],
    }
    assert probes.ollama_calls == [(("alphaswarm-orchestrator", "alphaswarm-worker"), True)]


def test_neo4j_down_is_degraded_with_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_app(tmp_path, monkeypatch, _Probes(neo4j_ok=False))) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["components"]["neo4j"]["fix"] == "docker compose up -d neo4j"


def test_missing_alias_is_degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(_app(tmp_path, monkeypatch, _Probes(missing=("alphaswarm-worker",)))) as client:
        aliases = client.get("/api/health").json()["components"]["aliases"]
    assert aliases["missing"] == ["alphaswarm-worker"]
    assert aliases["ok"] is False


def test_cloud_only_config_does_not_require_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = _Probes(ollama_ok=False)
    app = _app(tmp_path, monkeypatch, probes)
    cloud = RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-x")
    save_inference_config(
        InferenceConfig(orchestrator=cloud, worker=cloud), tmp_path / "inference.json"
    )
    with TestClient(app) as client:
        data = client.get("/api/health").json()
    assert data["inference_mode"] == "cloud"
    assert data["status"] == "ok"
    assert probes.ollama_calls == [((), False)]


def test_components_are_cached_for_five_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = _Probes()
    clock = [1000.0]
    monkeypatch.setattr(health_module, "_clock", lambda: clock[0])
    with TestClient(_app(tmp_path, monkeypatch, probes)) as client:
        client.get("/api/health")
        clock[0] += 4.9
        client.get("/api/health")
        assert probes.neo4j_calls == 1
        clock[0] += 0.2
        client.get("/api/health")
    assert probes.neo4j_calls == 2


def test_schema_is_applied_once_when_neo4j_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch, _Probes())
    with TestClient(app) as client:
        app.state.neo4j_ready = False
        client.get("/api/health")
        app.state.health_components = None  # force a fresh probe
        client.get("/api/health")
        graph = app.state.app_state.graph_manager
    graph.ensure_schema.assert_awaited_once()
    assert app.state.neo4j_ready is True


def test_live_endpoint_does_not_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probes = _Probes()
    with TestClient(_app(tmp_path, monkeypatch, probes)) as client:
        assert client.get("/api/health/live").json() == {"status": "ok"}
    assert probes.neo4j_calls == 0
