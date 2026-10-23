"""Readiness probes: bounded, never raising."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.readiness import (
    EXPECTED_OLLAMA_ENV,
    LAUNCHCTL_FIX,
    MLX_FIX,
    NEO4J_AUTH_FIX,
    NEO4J_FIX,
    OLLAMA_FIX,
    CommandResult,
    CommandRunner,
    ComponentStatus,
    check_docker,
    check_launchctl_env,
    check_mlx,
    check_neo4j,
    check_ollama,
    run_command,
)
from alphaswarm.settings import PROJECT_ROOT


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


# ---------------------------------------------------------------------------
# Host probes for the doctor: MLX, launchctl, Docker (all commands faked)
# ---------------------------------------------------------------------------


def _runner(
    *,
    server_env: dict[str, str] | None = None,
    launchctl: dict[str, str] | None = None,
    docker: CommandResult | None = None,
) -> CommandRunner:
    async def run(argv: Sequence[str]) -> CommandResult:
        cmd = tuple(argv)
        if cmd[0] == "pgrep":
            return CommandResult(0, "4242\n") if server_env is not None else CommandResult(1, "")
        if cmd[0] == "ps":
            env = " ".join(f"{k}={v}" for k, v in (server_env or {}).items())
            return CommandResult(
                0,
                "  PID   TT  STAT      TIME COMMAND\n"
                f" 4242   ??  S      0:01.00 /Applications/Ollama.app/ollama serve {env} "
                "HOME=/Users/someone SECRET_TOKEN=do-not-print\n",
            )
        if cmd[:2] == ("launchctl", "getenv"):
            return CommandResult(0, (launchctl or {}).get(cmd[2], "") + "\n")
        if cmd[0] == "docker":
            return docker if docker is not None else CommandResult(1, "")
        raise AssertionError(f"unexpected command {cmd}")

    return run


async def test_mlx_ok_when_the_running_server_has_it(tmp_path: Path) -> None:
    status = await check_mlx(
        required=True,
        run=_runner(server_env={"OLLAMA_USE_MLX": "1"}),
        server_log=tmp_path / "missing.log",
    )
    assert status.ok and status.required
    assert "SECRET_TOKEN" not in (status.detail or "") and "HOME" not in (status.detail or "")


async def test_mlx_fails_when_the_running_server_lacks_it(tmp_path: Path) -> None:
    """With OLLAMA_USE_MLX unset, the doctor reports the llama.cpp fallback."""
    status = await check_mlx(
        required=True,
        run=_runner(server_env={"OLLAMA_NUM_PARALLEL": "4"}),
        server_log=tmp_path / "missing.log",
    )
    assert (status.ok, status.fix) == (False, MLX_FIX)
    assert "OLLAMA_USE_MLX is unset" in (status.detail or "")


async def test_mlx_falls_back_to_the_server_log(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text('time=... level=INFO msg="MLX engine initialized"\n', encoding="utf-8")
    status = await check_mlx(required=False, run=_runner(server_env=None), server_log=log)
    assert status.ok and not status.required


async def test_mlx_unknown_without_env_or_log(tmp_path: Path) -> None:
    status = await check_mlx(required=True, run=_runner(server_env=None), server_log=tmp_path / "no.log")
    assert status.ok is False


async def test_launchctl_ok_when_values_match_and_agent_exists(tmp_path: Path) -> None:
    agent = tmp_path / "com.alphaswarm.ollama-env.plist"
    agent.write_text("<plist/>", encoding="utf-8")
    status = await check_launchctl_env(
        run=_runner(launchctl=dict(EXPECTED_OLLAMA_ENV)), launch_agent=agent, platform="darwin"
    )
    assert status.ok and status.required is False


async def test_launchctl_reports_lost_env_and_missing_agent(tmp_path: Path) -> None:
    status = await check_launchctl_env(
        run=_runner(launchctl={"OLLAMA_NUM_PARALLEL": "16"}),
        launch_agent=tmp_path / "absent.plist",
        platform="darwin",
    )
    assert (status.ok, status.fix) == (False, LAUNCHCTL_FIX)
    detail = status.detail or ""
    assert "OLLAMA_USE_MLX unset (expected 1)" in detail
    assert "OLLAMA_NUM_PARALLEL '16' (expected 4)" in detail
    assert "lost on reboot" in detail


async def test_launchctl_is_skipped_off_macos() -> None:
    """A Linux host never calls launchctl."""

    async def _no_run(argv: Sequence[str]) -> CommandResult:
        raise AssertionError("launchctl called off macOS")

    status = await check_launchctl_env(run=_no_run, platform="linux")
    assert status.ok and status.detail == "not macOS: skipped"


@pytest.mark.parametrize(
    ("result", "ok", "fragment"),
    [
        (CommandResult(0, "healthy\n"), True, "healthy"),
        (CommandResult(0, "unhealthy\n"), False, "is unhealthy"),
        (CommandResult(1, ""), False, "not found"),
        (CommandResult(127, ""), False, "docker CLI not found"),
        (CommandResult(124, ""), False, "did not answer"),
    ],
)
async def test_docker_status(result: CommandResult, ok: bool, fragment: str) -> None:
    status = await check_docker(run=_runner(docker=result))
    assert status.ok is ok and status.required is False
    assert fragment in (status.detail or "")


async def test_docker_finds_a_hand_made_container_named_neo4j() -> None:
    """The Compose name is tried first, then a container created with docker run."""
    seen: list[str] = []

    async def run(argv: Sequence[str]) -> CommandResult:
        seen.append(argv[-1])
        return CommandResult(0, "running\n") if argv[-1] == "neo4j" else CommandResult(1, "")

    status = await check_docker(run=run)
    assert seen == ["alphaswarm-neo4j", "neo4j"]
    assert (status.ok, status.detail) == (True, "neo4j running")


async def test_run_command_reports_a_missing_binary() -> None:
    assert (await run_command(("alphaswarm-no-such-binary-xyz",))).returncode == 127


def _script_values() -> dict[str, str]:
    shared = PROJECT_ROOT / "scripts" / "ollama.env"
    if shared.is_file():
        pairs = (
            line.split("=", 1)
            for line in shared.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#") and "=" in line
        )
        return {k.strip(): v.strip() for k, v in pairs}
    text = (PROJECT_ROOT / "scripts" / "configure_ollama_app_env.sh").read_text(encoding="utf-8")
    return dict(re.findall(r'^\s*"(OLLAMA_[A-Z_]+) ([^"]+)"', text, flags=re.MULTILINE))


def test_expected_env_matches_the_setup_scripts() -> None:
    """The doctor and the setup scripts must agree on every value."""
    assert _script_values() == dict(EXPECTED_OLLAMA_ENV)
