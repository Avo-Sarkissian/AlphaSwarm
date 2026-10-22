"""Run provenance helpers (docs/DECISIONS.md#adr-cycle-metrics).

``git_revision`` reports the commit and dirty state of the work tree the app
runs from; ``current_git_revision`` caches that answer for the process. Both
block on a git subprocess, so async callers use ``asyncio.to_thread``.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
from pathlib import Path
from typing import Final

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
            text=True,
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

    The running code was loaded when the process started, so later edits do
    not change what runs; caching also keeps the subprocess out of every run.
    """
    return git_revision(Path(__file__).resolve().parent)
