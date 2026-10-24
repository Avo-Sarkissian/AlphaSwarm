"""Run provenance (docs/DECISIONS.md#adr-run-manifest).

``git_revision`` reports the commit and dirty state of the work tree the app
runs from; ``current_git_revision`` caches that answer for the process. Both
block on a git subprocess, so async callers use ``asyncio.to_thread``.

The rest of the module is pure: blake2b-derived run and call seeds, the
provider/model/digest of each role, and the RunManifest stored as JSON on the
Cycle right after seeding.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.settings import AppSettings
    from alphaswarm.types import BracketConfig, BracketType

GIT_TIMEOUT_SECONDS: Final = 5.0
_SHA_RE: Final = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _run_git(repo_root: Path, *args: str) -> str | None:
    """Run one read-only git command. Returns stdout, or None on any failure."""
    # GIT_OPTIONAL_LOCKS=0: `git status` must not take index.lock while the
    # owner is committing in the same checkout during a web run.
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            # Paths are raw bytes under core.quotePath=false; a non-UTF-8 name
            # must not raise UnicodeDecodeError past the "never raises" contract.
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_revision(repo_root: Path) -> tuple[str | None, bool | None]:
    """Return ``(sha, dirty)`` for the work tree that contains ``repo_root``.

    ``repo_root`` may be any directory inside the work tree (git walks up).
    ``sha`` is the hex HEAD commit, or None outside a repository, without a
    git binary, before the first commit, or on timeout. ``dirty`` is True when
    tracked files differ from HEAD (untracked files do not count) and None
    when unknown. Never raises.
    """
    head = _run_git(repo_root, "rev-parse", "--verify", "HEAD")
    sha = head.strip() if head is not None else ""
    if not _SHA_RE.match(sha):
        return None, None
    status = _run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
    if status is None:
        return sha, None
    return sha, bool(status.strip())


@functools.cache
def current_git_revision() -> tuple[str | None, bool | None]:
    """``git_revision`` of the checkout this package was imported from, once per process.

    The first call fills the cache. A process runs the code it imported at
    startup, so a long-lived process must make that call at startup: the web
    lifespan does, and keeps stamping the revision it started from after a
    later commit. The CLI's first call opens its only run, seconds after
    startup. Caching also keeps the subprocess out of every run.
    """
    return git_revision(Path(__file__).resolve().parent)


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

MAX_SEED: Final = 2_147_483_647
"""Largest seed: Ollama and OpenAI-compatible servers take a signed 32-bit seed."""

RETEST_ROUND: Final = 0
"""Round number used to derive the call seeds of the Round 1 retest draw."""


def _seed_from(text: str) -> int:
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % MAX_SEED + 1


def derive_sim_seed(cycle_id: str) -> int:
    """Run seed used when ``SimulationSettings.sim_seed`` is None: stable per cycle id."""
    return _seed_from(f"sim_seed:{cycle_id}")


def derive_call_seed(sim_seed: int, agent_id: str, round_num: int) -> int:
    """Model sampling seed for one agent call (``options.seed``), in ``[1, MAX_SEED]``.

    Ollama's NUM_PARALLEL batching is not bit-exact, so a fixed seed narrows
    but does not remove run-to-run variation; results therefore use several
    seeds and confidence intervals.
    """
    return _seed_from(f"{sim_seed}:{agent_id}:{round_num}")


# ---------------------------------------------------------------------------
# Provenance and the run manifest
# ---------------------------------------------------------------------------

InferenceMode = Literal["local", "cloud", "mixed"]


class ModelRef(BaseModel, frozen=True, extra="forbid"):
    """Provider, model id and (for Ollama) weights digest of one inference role."""

    provider: str
    model: str
    digest: str | None = None


@dataclass(frozen=True)
class RunProvenance:
    """Both roles plus the inference mode, normally resolved by the composition root."""

    orchestrator: ModelRef
    worker: ModelRef
    inference_mode: InferenceMode


def provenance_from_providers(orchestrator: InferenceProvider, worker: InferenceProvider) -> RunProvenance:
    """Fallback provenance from the provider protocol alone.

    The protocol exposes only ``model`` and ``is_local()``, so roles are
    labelled "ollama" or "cloud" and digests are unknown. The composition root
    supplies exact provider types and Ollama digests instead.
    """
    orchestrator_local = orchestrator.is_local()
    worker_local = worker.is_local()
    mode: InferenceMode
    if orchestrator_local and worker_local:
        mode = "local"
    elif not orchestrator_local and not worker_local:
        mode = "cloud"
    else:
        mode = "mixed"
    return RunProvenance(
        orchestrator=ModelRef(provider="ollama" if orchestrator_local else "cloud", model=orchestrator.model),
        worker=ModelRef(provider="ollama" if worker_local else "cloud", model=worker.model),
        inference_mode=mode,
    )


class RunManifest(BaseModel, frozen=True, extra="forbid", populate_by_name=True):
    """Everything needed to describe and re-run one cycle; stored as JSON on the Cycle."""

    schema_id: Literal["alphaswarm.run-manifest/1"] = Field(default="alphaswarm.run-manifest/1", alias="schema")
    cycle_id: str
    created_at: datetime
    alphaswarm_version: str
    git_sha: str | None
    git_dirty: bool | None
    inference_mode: InferenceMode
    orchestrator: ModelRef
    worker: ModelRef
    brackets_hash: str
    prompt_hashes: dict[str, str]
    modifiers: dict[str, str]
    modifier_parse_tier: int | None
    market_context: str | None
    num_rounds: int
    simulation: dict[str, Any]
    sim_seed: int
    experiment_tag: str | None


def sha256_text(text: str) -> str:
    """Hex sha256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def brackets_hash(brackets: Sequence[BracketConfig]) -> str:
    """sha256 of the canonical JSON of the bracket table (counts, weights, templates)."""
    payload = [b.model_dump(mode="json") for b in brackets]
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _package_version() -> str:
    try:
        return version("alphaswarm")
    except PackageNotFoundError:
        return "0+unknown"


def build_run_manifest(
    *,
    cycle_id: str,
    settings: AppSettings,
    brackets: Sequence[BracketConfig],
    provenance: RunProvenance,
    prompt_hashes: Mapping[str, str],
    modifiers: Mapping[BracketType, str] | None,
    modifier_parse_tier: int | None,
    market_context: str | None,
    sim_seed: int,
    git_sha: str | None,
    git_dirty: bool | None,
    created_at: datetime | None = None,
) -> RunManifest:
    """Assemble the manifest. Pure: callers pass git state and hashes in."""
    sim = settings.simulation
    generated = modifiers or {}
    return RunManifest(
        cycle_id=cycle_id,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        alphaswarm_version=_package_version(),
        git_sha=git_sha,
        git_dirty=git_dirty,
        inference_mode=provenance.inference_mode,
        orchestrator=provenance.orchestrator,
        worker=provenance.worker,
        brackets_hash=brackets_hash(brackets),
        prompt_hashes=dict(sorted(prompt_hashes.items())),
        modifiers={b.bracket_type.value: generated.get(b.bracket_type, "") for b in brackets},
        modifier_parse_tier=modifier_parse_tier,
        market_context=market_context,
        num_rounds=settings.num_rounds,
        simulation=sim.model_dump(mode="json"),
        sim_seed=sim_seed,
        experiment_tag=sim.experiment_tag,
    )
