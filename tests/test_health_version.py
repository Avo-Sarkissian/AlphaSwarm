"""/api/health reports the installed package version."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import alphaswarm
import alphaswarm.web.routes.health as health_module
from alphaswarm.readiness import ComponentStatus
from alphaswarm.web.routes.health import router as health_router
from tests.support.web_app import make_route_app, route_test_settings


async def _neo4j_ok(gm: object, **_: Any) -> ComponentStatus:
    return ComponentStatus("neo4j", ok=True, required=True)


async def _ollama_ok(
    client: object,
    aliases: Any,
    *,
    required: bool,
    **_: Any,
) -> tuple[ComponentStatus, ComponentStatus]:
    return (
        ComponentStatus("ollama", ok=True, required=required),
        ComponentStatus("aliases", ok=True, required=required),
    )


def test_health_reports_the_installed_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_module, "check_neo4j", _neo4j_ok)
    monkeypatch.setattr(health_module, "check_ollama", _ollama_ok)
    app = make_route_app(health_router, settings=route_test_settings(tmp_path), graph=AsyncMock())
    with TestClient(app) as client:
        data = client.get("/api/health").json()
    assert data["version"] == alphaswarm.__version__
    assert data["version"] == importlib.metadata.version("alphaswarm")
