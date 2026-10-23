"""Readiness probes: bounded, never raising."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.readiness import (
    NEO4J_AUTH_FIX,
    NEO4J_FIX,
    OLLAMA_FIX,
    ComponentStatus,
    check_neo4j,
    check_ollama,
)


class _Graph:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    async def verify_connectivity(self) -> None:
        if self.behaviour == "down":
            raise Neo4jUnavailableError("refused", op="verify_connectivity")
        if self.behaviour == "auth":
            raise Neo4jAuthError("unauthorized")
        if self.behaviour == "mapped_down":
            raise Neo4jUnavailableError("unavailable", ServiceUnavailable("refused"), op="verify_connectivity")
        if self.behaviour == "mapped_auth":
            raise Neo4jUnavailableError("unavailable", Neo4jAuthError("unauthorized"), op="verify_connectivity")
        if self.behaviour == "hang":
            await asyncio.sleep(10)


class _Ollama:
    def __init__(self, names: list[str] | None = None, behaviour: str = "ok") -> None:
        self.names = names or []
        self.behaviour = behaviour
        self.raw_client = self

    async def list(self) -> Any:
        if self.behaviour == "down":
            raise ConnectionError("refused")
        if self.behaviour == "hang":
            await asyncio.sleep(10)
        return SimpleNamespace(models=[SimpleNamespace(model=n) for n in self.names])


async def test_neo4j_ok() -> None:
    status = await check_neo4j(_Graph("ok"))  # type: ignore[arg-type]
    assert status == ComponentStatus("neo4j", ok=True, required=True)


@pytest.mark.parametrize(
    ("graph", "detail"),
    [(None, "not configured"), (_Graph("down"), "unreachable (Neo4jUnavailableError)")],
)
async def test_neo4j_failures(graph: _Graph | None, detail: str) -> None:
    status = await check_neo4j(graph)  # type: ignore[arg-type]
    assert (status.ok, status.required, status.detail, status.fix) == (
        False,
        True,
        detail,
        NEO4J_FIX,
    )


async def test_neo4j_rejected_password_names_the_password_fix() -> None:
    """A wrong password is not a stopped database: starting Neo4j would not fix it."""
    status = await check_neo4j(_Graph("auth"))  # type: ignore[arg-type]
    assert (status.ok, status.required, status.detail, status.fix) == (
        False,
        True,
        "credentials rejected (AuthError)",
        NEO4J_AUTH_FIX,
    )
    assert "ALPHASWARM_NEO4J__PASSWORD" in NEO4J_AUTH_FIX
    assert "docker" not in NEO4J_AUTH_FIX


async def test_neo4j_classifies_the_wrapped_driver_error() -> None:
    """GraphStateManager maps driver errors (docs/DECISIONS.md#p4-d-07); the probe reads the cause."""
    auth = await check_neo4j(_Graph("mapped_auth"))  # type: ignore[arg-type]
    assert (auth.detail, auth.fix) == ("credentials rejected (AuthError)", NEO4J_AUTH_FIX)
    down = await check_neo4j(_Graph("mapped_down"))  # type: ignore[arg-type]
    assert (down.detail, down.fix) == ("unreachable (ServiceUnavailable)", NEO4J_FIX)


def test_neo4j_start_fix_covers_a_container_you_created_yourself() -> None:
    """Compose would start a second, empty database next to a stopped hand-made one."""
    assert "docker compose up -d neo4j" in NEO4J_FIX
    assert "docker start <name>" in NEO4J_FIX


async def test_neo4j_timeout() -> None:
    status = await check_neo4j(_Graph("hang"), timeout_s=0.01)  # type: ignore[arg-type]
    assert status.ok is False
    assert status.detail == "no answer within 0.01 s"


async def test_ollama_and_aliases_ok_with_latest_tags() -> None:
    client = _Ollama(["alphaswarm-worker:latest", "alphaswarm-orchestrator:latest"])
    ollama, aliases = await check_ollama(
        client,  # type: ignore[arg-type]
        ["alphaswarm-orchestrator", "alphaswarm-worker"],
        required=True,
    )
    assert ollama.ok and aliases.ok
    assert aliases.missing == ()


async def test_missing_alias_names_the_fix() -> None:
    ollama, aliases = await check_ollama(
        _Ollama(["alphaswarm-orchestrator:latest"]),  # type: ignore[arg-type]
        ["alphaswarm-orchestrator", "alphaswarm-worker"],
        required=True,
    )
    assert ollama.ok is True
    assert aliases.ok is False
    assert aliases.missing == ("alphaswarm-worker",)
    assert aliases.detail == "missing: alphaswarm-worker"
    assert aliases.fix == "ollama create alphaswarm-worker -f modelfiles/Modelfile.worker"


async def test_missing_latest_tagged_alias_is_created_not_pulled() -> None:
    """The Settings model list shows raw Ollama names such as 'alphaswarm-worker:latest'."""
    _, aliases = await check_ollama(
        _Ollama([]),  # type: ignore[arg-type]
        ["alphaswarm-worker:latest"],
        required=True,
    )
    assert aliases.missing == ("alphaswarm-worker:latest",)
    assert aliases.fix == "ollama create alphaswarm-worker -f modelfiles/Modelfile.worker"


async def test_unknown_model_fix_is_a_pull() -> None:
    _, aliases = await check_ollama(_Ollama([]), ["qwen3:8b"], required=True)  # type: ignore[arg-type]
    assert aliases.fix == "ollama pull qwen3:8b"


@pytest.mark.parametrize("behaviour", ["down", "hang"])
async def test_ollama_down_or_slow(behaviour: str) -> None:
    ollama, aliases = await check_ollama(
        _Ollama(behaviour=behaviour),  # type: ignore[arg-type]
        ["alphaswarm-worker"],
        required=True,
        timeout_s=0.01,
    )
    assert (ollama.ok, ollama.fix) == (False, OLLAMA_FIX)
    assert aliases.ok is False
    assert aliases.detail == "not checked: Ollama is not reachable"


async def test_not_required_when_no_role_is_local() -> None:
    ollama, aliases = await check_ollama(_Ollama(behaviour="down"), [], required=False)  # type: ignore[arg-type]
    assert (ollama.required, aliases.required) == (False, False)
