"""``alphaswarm doctor``: one readiness report for every documented setup failure.

It reuses the /api/health probes (alphaswarm.readiness) and adds the host
checks only a CLI can run: MLX on the Ollama server, the launchctl
environment, Docker, foreign models, the frontend build and the memory signal.
Read-only: it never applies the schema, loads a model or takes the instance lock.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from alphaswarm.errors import InferenceConfigError
from alphaswarm.inference.factory import inference_mode
from alphaswarm.memory_monitor import MemoryMonitor
from alphaswarm.readiness import (
    CommandRunner,
    ComponentStatus,
    check_docker,
    check_foreign_models,
    check_frontend_dist,
    check_launchctl_env,
    check_memory,
    check_mlx,
    check_neo4j,
    check_ollama,
    local_model_aliases,
    run_command,
)
from alphaswarm.settings import PROJECT_ROOT, AppSettings

if TYPE_CHECKING:
    from alphaswarm.inference.config import InferenceConfig
    from alphaswarm.services.runtime import Runtime

InferenceMode = Literal["local", "cloud", "mixed"]
RuntimeOpener = Callable[[AppSettings], AbstractAsyncContextManager["Runtime"]]

NEO4J_PASSWORD_FIX: Final = "Set ALPHASWARM_NEO4J__PASSWORD in .env (see .env.example), then docker compose up -d neo4j"
CONFIG_FIX: Final = "Open Settings and save a valid configuration, or delete the stored inference config file"
_PROBE_TIMEOUT_S: Final = 3.0
_NAME_WIDTH: Final = 15


@dataclass(frozen=True)
class DoctorReport:
    components: tuple[ComponentStatus, ...]
    inference_mode: InferenceMode | None

    @property
    def ok(self) -> bool:
        """True when every required check passed (warnings do not count)."""
        return all(c.ok or not c.required for c in self.components)


@dataclass(frozen=True)
class DoctorProbes:
    """Seams for tests; the defaults probe the real machine."""

    run: CommandRunner = run_command
    server_log: Path | None = None
    launch_agent: Path | None = None
    dist_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    platform: str | None = None
    memory_monitor: MemoryMonitor | None = None


def default_runtime_opener(settings: AppSettings) -> AbstractAsyncContextManager[Runtime]:
    """open_runtime without schema writes; Neo4j only when a password is configured."""
    from alphaswarm.services.runtime import open_runtime

    return open_runtime(settings, with_neo4j=bool(settings.neo4j.password), apply_schema=False)


async def collect_report(
    settings: AppSettings,
    *,
    open_runtime: RuntimeOpener = default_runtime_opener,
    probes: DoctorProbes | None = None,
) -> DoctorReport:
    probes = probes if probes is not None else DoctorProbes()
    components: list[ComponentStatus] = []
    mode: InferenceMode | None
    cfg: InferenceConfig | None
    async with open_runtime(settings) as runtime:
        try:
            cfg = await runtime.inference.config()
        except InferenceConfigError:
            cfg, mode = None, None
            components.append(
                ComponentStatus(
                    "inference_config",
                    ok=False,
                    required=True,
                    detail="the stored inference config is invalid",
                    fix=CONFIG_FIX,
                )
            )
        else:
            mode = inference_mode(cfg)
            components.append(ComponentStatus("inference_config", ok=True, required=True, detail=f"mode {mode}"))
        local = local_model_aliases(cfg, settings.ollama)
        needs_ollama = bool(local)
        if settings.neo4j.password:
            components.append(await check_neo4j(runtime.app_state.graph_manager, timeout_s=_PROBE_TIMEOUT_S))
        else:
            components.append(
                ComponentStatus(
                    "neo4j",
                    ok=False,
                    required=True,
                    detail="ALPHASWARM_NEO4J__PASSWORD is not set",
                    fix=NEO4J_PASSWORD_FIX,
                )
            )
        components.append(await check_docker(run=probes.run))
        client = runtime.app_state.ollama_client
        components.extend(await check_ollama(client, local, required=needs_ollama, timeout_s=_PROBE_TIMEOUT_S))
        components.append(await check_mlx(required=needs_ollama, run=probes.run, server_log=probes.server_log))
        components.append(
            await check_launchctl_env(run=probes.run, launch_agent=probes.launch_agent, platform=probes.platform)
        )
        ours = (settings.ollama.orchestrator_model_alias, settings.ollama.worker_model_alias)
        components.append(await check_foreign_models(client, ours))
        components.append(await check_frontend_dist(probes.dist_dir))
        monitor = probes.memory_monitor or MemoryMonitor(settings.governor)
        components.append(await check_memory(monitor))
    return DoctorReport(components=tuple(components), inference_mode=mode)


def render_text(report: DoctorReport, *, banner: str) -> str:
    lines = [banner, ""]
    for c in report.components:
        label = "OK  " if c.ok else ("FAIL" if c.required else "WARN")
        line = f"  {label}  {c.name:<{_NAME_WIDTH}}"
        if c.detail:
            line = f"{line} {c.detail}"
        lines.append(line.rstrip())
        if not c.ok and c.fix:
            lines.append(f"        fix: {c.fix}")
    failed = [c.name for c in report.components if c.required and not c.ok]
    warned = [c.name for c in report.components if not c.required and not c.ok]
    lines.append("")
    if failed:
        lines.append(f"Result: {len(failed)} required check(s) failed: {', '.join(failed)}")
    else:
        suffix = f" ({len(warned)} warning(s): {', '.join(warned)})" if warned else ""
        lines.append(f"Result: ready{suffix}")
    return "\n".join(lines)


def render_json(report: DoctorReport) -> str:
    return json.dumps(
        {
            "ok": report.ok,
            "inference_mode": report.inference_mode,
            "components": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "required": c.required,
                    "detail": c.detail,
                    "fix": c.fix,
                    "missing": list(c.missing),
                }
                for c in report.components
            ],
        },
        indent=2,
    )
