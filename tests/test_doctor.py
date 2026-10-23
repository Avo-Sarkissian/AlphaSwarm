"""alphaswarm doctor: every documented setup failure, with its fix."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alphaswarm.doctor import DoctorProbes, DoctorReport, collect_report, render_json, render_text
from alphaswarm.errors import InferenceConfigError, Neo4jUnavailableError
from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig
from alphaswarm.memory_monitor import MemoryMonitor
from alphaswarm.readiness import EXPECTED_OLLAMA_ENV, CommandResult
from alphaswarm.settings import AppSettings, GovernorSettings, Neo4jSettings

ALIASES = ["alphaswarm-orchestrator:latest", "alphaswarm-worker:latest"]


class _Graph:
    def __init__(self, up: bool = True) -> None:
        self.up = up

    async def verify_connectivity(self) -> None:
        if not self.up:
            raise Neo4jUnavailableError("refused", op="verify_connectivity")


class _Ollama:
    def __init__(self, models: list[str], loaded: list[str] | None = None, up: bool = True) -> None:
        self.raw_client = self
        self.models, self.loaded, self.up = models, loaded or [], up

    async def list(self) -> Any:
        if not self.up:
            raise ConnectionError("refused")
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.models])

    async def ps(self) -> Any:
        if not self.up:
            raise ConnectionError("refused")
        return SimpleNamespace(models=[SimpleNamespace(model=m, size=2**30) for m in self.loaded])


@dataclass
class _Inference:
    cfg: InferenceConfig | None

    async def config(self) -> InferenceConfig:
        if self.cfg is None:
            raise InferenceConfigError("invalid")
        return self.cfg


def _opener(graph: object, ollama: object, cfg: InferenceConfig | None):
    runtime = SimpleNamespace(
        app_state=SimpleNamespace(graph_manager=graph, ollama_client=ollama),
        inference=_Inference(cfg),
    )

    @asynccontextmanager
    async def _open(settings: AppSettings) -> AsyncIterator[Any]:
        yield runtime

    return _open


def _local_cfg() -> InferenceConfig:
    return InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-orchestrator"),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
    )


def _cloud_cfg() -> InferenceConfig:
    role = RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-haiku-4-5", api_key="test-key")
    return InferenceConfig(orchestrator=role, worker=role)


def _probes(
    tmp_path: Path, *, mlx: bool = True, launchctl_ok: bool = True, dist: bool = True, docker: str = "healthy"
) -> DoctorProbes:
    agent = tmp_path / "agent.plist"
    if launchctl_ok:
        agent.write_text("<plist/>", encoding="utf-8")
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    if dist:
        (dist_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    server_env = {"OLLAMA_USE_MLX": "1"} if mlx else {"OLLAMA_NUM_PARALLEL": "4"}

    async def run(argv: Sequence[str]) -> CommandResult:
        cmd = tuple(argv)
        if cmd[0] == "pgrep":
            return CommandResult(0, "4242\n")
        if cmd[0] == "ps":
            env = " ".join(f"{k}={v}" for k, v in server_env.items())
            return CommandResult(0, f" 4242 ?? S 0:01.00 ollama serve {env}\n")
        if cmd[:2] == ("launchctl", "getenv"):
            value = EXPECTED_OLLAMA_ENV[cmd[2]] if launchctl_ok else ""
            return CommandResult(0, value + "\n")
        if cmd[0] == "docker":
            return CommandResult(0, docker + "\n")
        raise AssertionError(cmd)

    calm = MemoryMonitor(GovernorSettings(), kernel=True, sysctl=lambda n: 70 if n == "kern.memorystatus_level" else 1)
    return DoctorProbes(
        run=run,
        server_log=tmp_path / "server.log",
        launch_agent=agent,
        dist_dir=dist_dir,
        platform="darwin",
        memory_monitor=calm,
    )


def _settings(password: str = "not-a-real-secret") -> AppSettings:
    return AppSettings(_env_file=None, neo4j=Neo4jSettings(password=password))  # type: ignore[call-arg]


async def _report(
    tmp_path: Path,
    *,
    graph: object = None,
    ollama: object = None,
    cfg: InferenceConfig | None = None,
    settings: AppSettings | None = None,
    **probe_kwargs: Any,
) -> DoctorReport:
    return await collect_report(
        settings or _settings(),
        open_runtime=_opener(graph or _Graph(), ollama or _Ollama(ALIASES), cfg or _local_cfg()),
        probes=_probes(tmp_path, **probe_kwargs),
    )


def _by_name(report: DoctorReport) -> dict[str, Any]:
    return {c.name: c for c in report.components}


async def test_healthy_local_setup_is_ready(tmp_path: Path) -> None:
    report = await _report(tmp_path)
    assert report.ok and report.inference_mode == "local"
    assert all(c.ok for c in report.components)
    assert set(_by_name(report)) == {
        "inference_config",
        "neo4j",
        "docker",
        "ollama",
        "aliases",
        "mlx",
        "launchctl",
        "foreign_models",
        "frontend_dist",
        "memory",
    }


async def test_mlx_fallback_fails_the_doctor(tmp_path: Path) -> None:
    report = await _report(tmp_path, mlx=False)
    assert not report.ok
    assert _by_name(report)["mlx"].required is True


async def test_missing_alias_fails_with_the_create_command(tmp_path: Path) -> None:
    report = await _report(tmp_path, ollama=_Ollama(["alphaswarm-orchestrator:latest"]))
    aliases = _by_name(report)["aliases"]
    assert not report.ok
    assert aliases.fix == "ollama create alphaswarm-worker -f modelfiles/Modelfile.worker"


async def test_neo4j_down_fails(tmp_path: Path) -> None:
    report = await _report(tmp_path, graph=_Graph(up=False), docker="exited")
    assert not report.ok
    assert _by_name(report)["neo4j"].ok is False
    assert _by_name(report)["docker"].ok is False


async def test_missing_password_is_a_neo4j_failure(tmp_path: Path) -> None:
    report = await _report(tmp_path, settings=_settings(password=""))
    neo4j = _by_name(report)["neo4j"]
    assert (neo4j.ok, neo4j.detail) == (False, "ALPHASWARM_NEO4J__PASSWORD is not set")


async def test_warnings_do_not_fail_the_doctor(tmp_path: Path) -> None:
    report = await _report(
        tmp_path,
        launchctl_ok=False,
        dist=False,
        ollama=_Ollama(ALIASES, loaded=["codellama:7b"]),
    )
    names = _by_name(report)
    assert report.ok
    assert not names["launchctl"].ok and not names["frontend_dist"].ok
    assert not names["foreign_models"].ok


async def test_cloud_only_does_not_require_ollama(tmp_path: Path) -> None:
    report = await _report(tmp_path, cfg=_cloud_cfg(), ollama=_Ollama([], up=False), mlx=False)
    names = _by_name(report)
    assert report.ok and report.inference_mode == "cloud"
    assert not names["ollama"].required and not names["mlx"].required


async def test_invalid_inference_config_fails(tmp_path: Path) -> None:
    report = await collect_report(
        _settings(),
        open_runtime=_opener(_Graph(), _Ollama(ALIASES), None),
        probes=_probes(tmp_path),
    )
    assert not report.ok
    assert _by_name(report)["inference_config"].ok is False


async def test_renderers(tmp_path: Path) -> None:
    report = await _report(tmp_path, ollama=_Ollama(["alphaswarm-orchestrator:latest"]), dist=False)
    text = render_text(report, banner="BANNER")
    assert text.splitlines()[0] == "BANNER"
    assert "  FAIL  aliases" in text and "  WARN  frontend_dist" in text
    assert "        fix: ollama create alphaswarm-worker" in text
    assert text.splitlines()[-1].startswith("Result: 1 required check(s) failed: aliases")
    data = json.loads(render_json(report))
    assert data["ok"] is False and data["inference_mode"] == "local"
    assert {"name", "ok", "required", "detail", "fix", "missing"} <= set(data["components"][0])
