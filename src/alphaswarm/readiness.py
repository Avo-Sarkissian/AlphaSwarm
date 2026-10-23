"""Readiness probes shared by /api/health and the future `alphaswarm doctor`.

Each check is bounded by a timeout and returns a ComponentStatus; none raises
(CancelledError still propagates). A missing model alias or a stopped Neo4j or
Ollama then shows up before a run starts, with the command that fixes it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import structlog
from neo4j.exceptions import AuthError as Neo4jAuthError

from alphaswarm.inference.config import ProviderType

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.inference.config import InferenceConfig
    from alphaswarm.memory_monitor import MemoryMonitor
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.settings import OllamaSettings

log = structlog.get_logger(component="readiness")

# Shared with the web lifespan's startup warning and the 503 graph_unavailable
# message. Once the database answers, the next /api/health probe applies the
# schema, so starting it needs no server restart (docs/DECISIONS.md#p4-d-05). A
# password change does: the driver keeps the credential it was built with.
NEO4J_FIX: Final = (
    "Start Neo4j (docker compose up -d neo4j, or docker start <name> for a container you created yourself)"
)
NEO4J_AUTH_FIX: Final = "Set ALPHASWARM_NEO4J__PASSWORD in .env to the database's password, then restart the server"
OLLAMA_FIX: Final = "Start Ollama with OLLAMA_USE_MLX=1 (docs/RUNBOOK.md section 1)"
_MODELFILES: Final[dict[str, str]] = {
    "alphaswarm-orchestrator": "modelfiles/Modelfile.orchestrator",
    "alphaswarm-worker": "modelfiles/Modelfile.worker",
}


@dataclass(frozen=True)
class ComponentStatus:
    """Outcome of one readiness probe."""

    name: str
    ok: bool
    required: bool
    detail: str | None = None
    fix: str | None = None
    missing: tuple[str, ...] = ()


async def check_neo4j(gm: GraphStateManager | None, *, timeout_s: float = 1.0) -> ComponentStatus:
    """Probe Neo4j with verify_connectivity(), bounded by *timeout_s*."""
    if gm is None:
        return ComponentStatus("neo4j", ok=False, required=True, detail="not configured", fix=NEO4J_FIX)
    try:
        async with asyncio.timeout(timeout_s):
            await gm.verify_connectivity()
    except TimeoutError:
        return ComponentStatus(
            "neo4j",
            ok=False,
            required=True,
            detail=f"no answer within {timeout_s:g} s",
            fix=NEO4J_FIX,
        )
    except Exception as exc:
        # GraphStateManager wraps the driver error (docs/DECISIONS.md#p4-d-07);
        # classify on that cause so a rejected password keeps its own fix.
        cause = getattr(exc, "original_error", None) or exc
        exc_type = cause.__class__.__name__
        log.warning("readiness_neo4j_failed", exc_type=exc_type)
        if isinstance(cause, Neo4jAuthError):
            return ComponentStatus(
                "neo4j",
                ok=False,
                required=True,
                detail=f"credentials rejected ({exc_type})",
                fix=NEO4J_AUTH_FIX,
            )
        return ComponentStatus("neo4j", ok=False, required=True, detail=f"unreachable ({exc_type})", fix=NEO4J_FIX)
    return ComponentStatus("neo4j", ok=True, required=True)


def _model_names(listing: object) -> set[str]:
    names: set[str] = set()
    for model in getattr(listing, "models", None) or []:
        name = getattr(model, "model", None) or getattr(model, "name", None)
        if name:
            names.add(str(name).removesuffix(":latest"))
    return names


def _create_command(alias: str) -> str:
    # Matching ignores ':latest' (see check_ollama), so the lookup does too: a
    # locally built alias is created from its Modelfile, never pulled.
    name = alias.removesuffix(":latest")
    modelfile = _MODELFILES.get(name)
    return f"ollama create {name} -f {modelfile}" if modelfile else f"ollama pull {alias}"


def _join(commands: Iterable[str]) -> str:
    return " && ".join(commands)


async def check_ollama(
    client: OllamaClient | None,
    aliases: Collection[str],
    *,
    required: bool,
    timeout_s: float = 1.0,
) -> tuple[ComponentStatus, ComponentStatus]:
    """Probe the Ollama server and the model aliases the local roles call.

    ``required`` is False when no role uses Ollama (cloud-only config).
    """
    not_checked = ComponentStatus(
        "aliases",
        ok=False,
        required=required,
        detail="not checked: Ollama is not reachable",
    )
    if client is None:
        return (
            ComponentStatus("ollama", ok=False, required=required, detail="not configured", fix=OLLAMA_FIX),
            not_checked,
        )
    try:
        async with asyncio.timeout(timeout_s):
            listing = await client.raw_client.list()
    except TimeoutError:
        return (
            ComponentStatus(
                "ollama",
                ok=False,
                required=required,
                detail=f"no answer within {timeout_s:g} s",
                fix=OLLAMA_FIX,
            ),
            not_checked,
        )
    except Exception as exc:
        log.warning("readiness_ollama_failed", exc_type=exc.__class__.__name__)
        return (
            ComponentStatus(
                "ollama",
                ok=False,
                required=required,
                detail=f"unreachable ({exc.__class__.__name__})",
                fix=OLLAMA_FIX,
            ),
            not_checked,
        )
    available = _model_names(listing)
    missing = tuple(a for a in aliases if a.removesuffix(":latest") not in available)
    ollama = ComponentStatus("ollama", ok=True, required=required)
    if missing:
        return ollama, ComponentStatus(
            "aliases",
            ok=False,
            required=required,
            detail="missing: " + ", ".join(missing),
            fix=_join(_create_command(a) for a in missing),
            missing=missing,
        )
    return ollama, ComponentStatus("aliases", ok=True, required=required)


# ---------------------------------------------------------------------------
# Host probes for `alphaswarm doctor`. Commands are short, read-only and
# bounded; only OLLAMA_* names are kept from a process environment.
# ---------------------------------------------------------------------------

EXPECTED_OLLAMA_ENV: Final[Mapping[str, str]] = MappingProxyType(
    {
        "OLLAMA_NUM_PARALLEL": "4",
        "OLLAMA_MAX_LOADED_MODELS": "2",
        "OLLAMA_KEEP_ALIVE": "5m",
        "OLLAMA_USE_MLX": "1",
    }
)
MLX_LOG_MARKER: Final = "MLX engine initialized"
MLX_FIX: Final = (
    "Ollama.app: ./scripts/configure_ollama_app_env.sh, then quit and reopen Ollama; "
    "terminal: ./scripts/start_ollama.sh (docs/RUNBOOK.md section 1)"
)
LAUNCHCTL_FIX: Final = "./scripts/configure_ollama_app_env.sh"
LAUNCH_AGENT_LABEL: Final = "com.alphaswarm.ollama-env"
#: Container names tried in order: the Compose service's, then the plain name a
#: hand-made ``docker run --name neo4j`` container usually has.
NEO4J_CONTAINERS: Final[tuple[str, ...]] = ("alphaswarm-neo4j", "neo4j")
_LOG_TAIL_BYTES: Final = 4_000_000


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


CommandRunner = Callable[[Sequence[str]], Awaitable[CommandResult]]


async def run_command(argv: Sequence[str], *, timeout_s: float = 5.0) -> CommandResult:
    """Run a short read-only command. 127 = not installed, 124 = timed out; never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
    except OSError:
        return CommandResult(127, "")
    try:
        async with asyncio.timeout(timeout_s):
            out, _ = await proc.communicate()
    except TimeoutError:
        return CommandResult(124, "")
    finally:
        if proc.returncode is None:
            proc.kill()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()
    code = proc.returncode if proc.returncode is not None else 1
    return CommandResult(code, out.decode("utf-8", errors="replace"))


def default_server_log() -> Path:
    return Path.home() / ".ollama" / "logs" / "server.log"


def default_launch_agent() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


async def ollama_server_env(*, run: CommandRunner = run_command) -> dict[str, str] | None:
    """OLLAMA_* variables of the running ``ollama serve`` process, or None if unknown.

    Same view as the RUNBOOK's ``ps eww $(pgrep -f "ollama serve")``; every
    non-OLLAMA_ variable is dropped because a process environment can hold
    unrelated secrets.
    """
    found = await run(("pgrep", "-f", "ollama serve"))
    pids = found.stdout.split()
    if found.returncode != 0 or not pids:
        return None
    shown = await run(("ps", "eww", pids[0]))
    if shown.returncode != 0:
        return None
    env: dict[str, str] = {}
    for token in shown.stdout.split():
        name, sep, value = token.partition("=")
        if sep and name.startswith("OLLAMA_"):
            env[name] = value
    return env


def _log_mentions(path: Path, marker: str) -> bool:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - _LOG_TAIL_BYTES))
            return marker.encode() in fh.read()
    except OSError:
        return False


async def check_mlx(
    *, required: bool, run: CommandRunner = run_command, server_log: Path | None = None
) -> ComponentStatus:
    """Is the Ollama server on the MLX backend? Without it nvfp4 silently uses llama.cpp."""
    env = await ollama_server_env(run=run)
    log_path = server_log if server_log is not None else default_server_log()
    seen = await asyncio.to_thread(_log_mentions, log_path, MLX_LOG_MARKER)
    if env is not None:
        value = env.get("OLLAMA_USE_MLX")
        if value is not None and value.strip().lower() in {"1", "true", "yes"}:
            note = "MLX engine initialized" if seen else "no model has loaded on MLX yet"
            return ComponentStatus(
                "mlx",
                ok=True,
                required=required,
                detail=f"OLLAMA_USE_MLX={value} on the running server; {note}",
            )
        shown = "unset" if value is None else repr(value)
        return ComponentStatus(
            "mlx",
            ok=False,
            required=required,
            detail=(
                f"OLLAMA_USE_MLX is {shown} on the running Ollama server, so the nvfp4 "
                "models fall back to llama.cpp (much slower prefill)"
            ),
            fix=MLX_FIX,
        )
    if seen:
        return ComponentStatus("mlx", ok=True, required=required, detail=f"'{MLX_LOG_MARKER}' found in {log_path}")
    return ComponentStatus(
        "mlx",
        ok=False,
        required=required,
        detail="cannot read the Ollama server's environment and its log shows no MLX engine",
        fix=MLX_FIX,
    )


async def check_launchctl_env(
    *,
    run: CommandRunner = run_command,
    expected: Mapping[str, str] = EXPECTED_OLLAMA_ENV,
    launch_agent: Path | None = None,
    platform: str | None = None,
) -> ComponentStatus:
    """Ollama.app's launchctl environment plus the LaunchAgent that restores it at login."""
    if (platform or sys.platform) != "darwin":
        return ComponentStatus("launchctl", ok=True, required=False, detail="not macOS: skipped")
    problems: list[str] = []
    for name, want in expected.items():
        got = (await run(("launchctl", "getenv", name))).stdout.strip()
        if got != want:
            problems.append(f"{name} {'unset' if not got else repr(got)} (expected {want})")
    agent = launch_agent if launch_agent is not None else default_launch_agent()
    if not await asyncio.to_thread(agent.is_file):
        problems.append(f"LaunchAgent {agent.name} missing, so the values are lost on reboot")
    if problems:
        return ComponentStatus("launchctl", ok=False, required=False, detail="; ".join(problems), fix=LAUNCHCTL_FIX)
    return ComponentStatus("launchctl", ok=True, required=False)


async def check_docker(
    *, run: CommandRunner = run_command, containers: Sequence[str] = NEO4J_CONTAINERS
) -> ComponentStatus:
    """Docker health of the Neo4j container (informational; Neo4j may run elsewhere)."""
    for container in containers:
        result = await run(
            (
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container,
            )
        )
        if result.returncode == 127:
            return ComponentStatus(
                "docker",
                ok=False,
                required=False,
                detail="docker CLI not found",
                fix="Install or start Docker Desktop",
            )
        if result.returncode == 124:
            return ComponentStatus(
                "docker",
                ok=False,
                required=False,
                detail="docker did not answer within 5 s",
                fix="Start Docker Desktop",
            )
        if result.returncode != 0:
            continue
        status = result.stdout.strip()
        # A container without a healthcheck reports its plain state.
        if status in {"healthy", "running"}:
            return ComponentStatus("docker", ok=True, required=False, detail=f"{container} {status}")
        return ComponentStatus(
            "docker",
            ok=False,
            required=False,
            detail=f"{container} is {status or 'unknown'}",
            fix=NEO4J_FIX,
        )
    names = " or ".join(containers)
    return ComponentStatus(
        "docker",
        ok=False,
        required=False,
        detail=f"container {names} not found (or the Docker daemon is not running)",
        fix=NEO4J_FIX,
    )


DIST_FIX: Final = "cd frontend && npm ci && npm run build"


def local_model_aliases(cfg: InferenceConfig | None, ollama: OllamaSettings) -> tuple[str, ...]:
    """Model names the Ollama-backed roles call (empty when both roles are cloud)."""
    if cfg is None:
        return (ollama.orchestrator_model_alias, ollama.worker_model_alias)
    roles = (cfg.orchestrator, cfg.worker)
    return tuple(dict.fromkeys(r.model for r in roles if r.provider == ProviderType.OLLAMA))


async def check_foreign_models(
    client: OllamaClient | None, aliases: Collection[str], *, timeout_s: float = 3.0
) -> ComponentStatus:
    """Models loaded besides AlphaSwarm's own: they take memory the swarm needs."""
    if client is None:
        return ComponentStatus("foreign_models", ok=True, required=False, detail="not checked: no Ollama client")
    try:
        async with asyncio.timeout(timeout_s):
            listing = await client.raw_client.ps()
    except Exception as exc:  # readiness probes never raise
        log.warning("readiness_ollama_ps_failed", exc_type=exc.__class__.__name__)
        return ComponentStatus("foreign_models", ok=True, required=False, detail="not checked: Ollama is not reachable")
    ours = {a.removesuffix(":latest") for a in aliases}
    names: list[str] = []
    shown: list[str] = []
    for model in getattr(listing, "models", None) or []:
        name = str(getattr(model, "model", None) or getattr(model, "name", "")).removesuffix(":latest")
        if not name or name in ours:
            continue
        size = getattr(model, "size", None)
        names.append(name)
        shown.append(f"{name} ({size / 2**30:.1f} GiB)" if isinstance(size, int) else name)
    if not names:
        return ComponentStatus("foreign_models", ok=True, required=False)
    return ComponentStatus(
        "foreign_models",
        ok=False,
        required=False,
        detail="loaded besides AlphaSwarm's models: " + ", ".join(shown),
        fix=_join(f"ollama stop {n}" for n in names),
    )


async def check_frontend_dist(dist_dir: Path) -> ComponentStatus:
    """Without frontend/dist the web server has no UI at / (it serves a hint page)."""
    index = dist_dir / "index.html"
    if await asyncio.to_thread(index.is_file):
        return ComponentStatus("frontend_dist", ok=True, required=False)
    return ComponentStatus("frontend_dist", ok=False, required=False, detail=f"{index} not found", fix=DIST_FIX)


async def check_memory(monitor: MemoryMonitor) -> ComponentStatus:
    """The governor's memory view right now (docs/DECISIONS.md#p3-d-12)."""
    reading = await monitor.read_combined()
    detail = (
        f"{monitor.signal_source} signal: {reading.used_percent:.1f}% used, "
        f"kernel pressure {reading.pressure_level.value}"
    )
    if reading.is_crisis or reading.is_pause_zone:
        return ComponentStatus(
            "memory",
            ok=False,
            required=False,
            detail=detail,
            fix="Close memory-heavy apps or unload foreign models before a run",
        )
    return ComponentStatus("memory", ok=True, required=False, detail=detail)
