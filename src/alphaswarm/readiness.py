"""Readiness probes shared by /api/health and the future `alphaswarm doctor`.

Each check is bounded by a timeout and returns a ComponentStatus; none raises
(CancelledError still propagates). A missing model alias or a stopped Neo4j or
Ollama then shows up before a run starts, with the command that fixes it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog
from neo4j.exceptions import AuthError as Neo4jAuthError

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient

log = structlog.get_logger(component="readiness")

# Shared with the web lifespan's startup warning and the 503 graph_unavailable
# message. Once the database answers, the next /api/health probe applies the
# schema, so starting it needs no server restart (docs/DECISIONS.md#p4-d-05). A
# password change does: the driver keeps the credential it was built with.
NEO4J_FIX: Final = (
    "Start Neo4j (docker compose up -d neo4j, or docker start <name> for a container "
    "you created yourself)"
)
NEO4J_AUTH_FIX: Final = (
    "Set ALPHASWARM_NEO4J__PASSWORD in .env to the database's password, then restart the server"
)
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
        return ComponentStatus(
            "neo4j", ok=False, required=True, detail="not configured", fix=NEO4J_FIX
        )
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
        exc_type = exc.__class__.__name__
        log.warning("readiness_neo4j_failed", exc_type=exc_type)
        if isinstance(exc, Neo4jAuthError):
            return ComponentStatus(
                "neo4j",
                ok=False,
                required=True,
                detail=f"credentials rejected ({exc_type})",
                fix=NEO4J_AUTH_FIX,
            )
        return ComponentStatus(
            "neo4j", ok=False, required=True, detail=f"unreachable ({exc_type})", fix=NEO4J_FIX
        )
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
            ComponentStatus(
                "ollama", ok=False, required=required, detail="not configured", fix=OLLAMA_FIX
            ),
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
