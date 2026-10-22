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

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.ollama_client import OllamaClient

log = structlog.get_logger(component="readiness")

NEO4J_FIX: Final = "docker compose up -d neo4j"
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
        log.warning("readiness_neo4j_failed", exc_type=exc.__class__.__name__)
        return ComponentStatus(
            "neo4j",
            ok=False,
            required=True,
            detail=f"unreachable ({exc.__class__.__name__})",
            fix=NEO4J_FIX,
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
    modelfile = _MODELFILES.get(alias)
    return f"ollama create {alias} -f {modelfile}" if modelfile else f"ollama pull {alias}"


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
