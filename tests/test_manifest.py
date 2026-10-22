"""Run provenance: git_revision and current_git_revision (docs/DECISIONS.md#adr-cycle-metrics)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import alphaswarm.manifest as manifest
from alphaswarm.manifest import git_revision

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not installed")

# Isolate the throwaway repositories from the owner's git config (signing,
# hooks, templates) so commits succeed on any machine and in CI.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )


@pytest.fixture()
def committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("v1\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@needs_git
def test_clean_repository_reports_head_and_not_dirty(committed_repo: Path) -> None:
    sha, dirty = git_revision(committed_repo)

    assert sha is not None
    assert len(sha) == 40
    assert dirty is False


@needs_git
def test_any_directory_inside_the_work_tree_works(committed_repo: Path) -> None:
    sub = committed_repo / "pkg" / "mod"
    sub.mkdir(parents=True)

    assert git_revision(sub) == git_revision(committed_repo)


@needs_git
def test_untracked_files_do_not_make_it_dirty(committed_repo: Path) -> None:
    (committed_repo / "scratch.txt").write_text("x\n")

    assert git_revision(committed_repo)[1] is False


@needs_git
def test_modified_tracked_file_makes_it_dirty(committed_repo: Path) -> None:
    (committed_repo / "tracked.txt").write_text("v2\n")

    assert git_revision(committed_repo)[1] is True


@needs_git
def test_repository_without_commits_is_unknown(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")

    assert git_revision(tmp_path) == (None, None)


def test_not_a_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A copy outside any repository records no git state."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert git_revision(tmp_path) == (None, None)


def test_missing_git_binary_returns_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No git installed is not an error."""

    def no_git(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(manifest.subprocess, "run", no_git)

    assert git_revision(tmp_path) == (None, None)


def test_git_timeout_returns_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A hung git (network home, iCloud) is cut off, not waited on."""

    def hung_git(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=manifest.GIT_TIMEOUT_SECONDS)

    monkeypatch.setattr(manifest.subprocess, "run", hung_git)

    assert git_revision(tmp_path) == (None, None)


@needs_git
def test_status_failure_keeps_sha_and_unknown_dirty(
    monkeypatch: pytest.MonkeyPatch, committed_repo: Path
) -> None:
    real_run = subprocess.run

    def flaky_status(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "status" in cmd:
            raise subprocess.TimeoutExpired(cmd="git status", timeout=manifest.GIT_TIMEOUT_SECONDS)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(manifest.subprocess, "run", flaky_status)

    sha, dirty = git_revision(committed_repo)

    assert sha is not None
    assert dirty is None


def test_git_runs_with_timeout_and_without_optional_locks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`git status` must not take index.lock while the owner commits mid-run."""
    seen: list[dict[str, Any]] = []

    def record(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, returncode=128, stdout="", stderr="")

    monkeypatch.setattr(manifest.subprocess, "run", record)

    assert git_revision(tmp_path) == (None, None)
    assert seen[0]["cmd"][:3] == ["git", "-C", str(tmp_path)]
    assert seen[0]["env"]["GIT_OPTIONAL_LOCKS"] == "0"
    assert seen[0]["timeout"] == manifest.GIT_TIMEOUT_SECONDS


def test_undecodable_git_output_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-UTF-8 path from `git status` (core.quotePath=false on Linux) still reads as dirty."""
    sha = "0123456789abcdef0123456789abcdef01234567"
    raw = {"rev-parse": f"{sha}\n".encode(), "status": b" M caf\xe9.txt\n"}

    def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        out: bytes | str = raw["status" if "status" in cmd else "rev-parse"]
        if kwargs.get("text") or kwargs.get("encoding") or kwargs.get("errors"):
            # Decode the way subprocess.run does in text mode.
            out = out.decode(kwargs.get("encoding") or "utf-8", kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(manifest.subprocess, "run", fake_run)

    assert git_revision(tmp_path) == (sha, True)


def test_current_git_revision_is_cached_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def fake(repo_root: Path) -> tuple[str | None, bool | None]:
        calls.append(repo_root)
        return "f" * 40, False

    monkeypatch.setattr(manifest, "git_revision", fake)
    manifest.current_git_revision.cache_clear()
    try:
        assert manifest.current_git_revision() == ("f" * 40, False)
        assert manifest.current_git_revision() == ("f" * 40, False)
    finally:
        manifest.current_git_revision.cache_clear()

    assert calls == [Path(manifest.__file__).resolve().parent]
