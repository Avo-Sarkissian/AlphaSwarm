"""Per-user single-instance lock (docs/DECISIONS.md#adr-instance-lock)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from alphaswarm import instance_lock
from alphaswarm.instance_lock import (
    InstanceLockHeldError,
    acquire,
    default_lock_path,
    describe_holder,
)
from alphaswarm.settings import PROJECT_ROOT

# A child process that takes the lock, reports it, then holds it or dies hard.
_HOLDER = textwrap.dedent(
    """
    import os, signal, sys, time
    from pathlib import Path
    from alphaswarm.instance_lock import acquire
    lock = acquire(sys.argv[2], detail="http://127.0.0.1:8000", path=Path(sys.argv[1]))
    print("locked", flush=True)
    if sys.argv[3] == "crash":
        os.kill(os.getpid(), signal.SIGKILL)
    time.sleep(60)
    """
)


def _spawn_holder(path: Path, command: str, mode: str) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(path), command, mode],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_default_path_is_per_user_and_outside_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHASWARM_INSTANCE_LOCK", raising=False)
    path = default_lock_path()
    assert path == Path.home() / ".alphaswarm" / "instance.lock"
    assert PROJECT_ROOT not in path.parents


def test_the_environment_can_move_the_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALPHASWARM_INSTANCE_LOCK", str(tmp_path / "other.lock"))
    assert default_lock_path() == tmp_path / "other.lock"


def test_tests_never_touch_the_real_lock(isolated_instance_lock: Path) -> None:
    assert isolated_instance_lock == instance_lock.DEFAULT_LOCK_PATH
    assert isolated_instance_lock != Path.home() / ".alphaswarm" / "instance.lock"


def test_a_second_acquire_fails_and_names_the_holder(tmp_path: Path) -> None:
    path = tmp_path / "instance.lock"
    held = acquire("web", detail="http://127.0.0.1:8000", path=path)
    try:
        with pytest.raises(InstanceLockHeldError) as exc_info:
            acquire("report", path=path)
        message = str(exc_info.value)
        assert "`alphaswarm web`" in message
        assert f"pid {os.getpid()}" in message
        assert "http://127.0.0.1:8000" in message
        assert exc_info.value.path == path
    finally:
        held.release()


def test_release_frees_the_lock_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "instance.lock"
    first = acquire("run", path=path)
    first.release()
    first.release()
    acquire("run", path=path).release()


def _reap(proc: subprocess.Popen[str]) -> int:
    """Wait for the child and close its stdout pipe (an unclosed pipe is a
    ResourceWarning, which filterwarnings = error turns into a failure)."""
    try:
        return proc.wait(timeout=10)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()


def test_a_holder_in_another_process_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "instance.lock"
    proc = _spawn_holder(path, "web", "hold")
    try:
        with pytest.raises(InstanceLockHeldError) as exc_info:
            acquire("report", path=path)
        assert exc_info.value.holder is not None
        assert exc_info.value.holder["pid"] == proc.pid
        assert exc_info.value.holder["command"] == "web"
    finally:
        proc.kill()
        _reap(proc)


def test_the_lock_dies_with_a_crashed_holder(tmp_path: Path) -> None:
    """No stale pidfile: the kernel drops the flock when the holder dies, even on SIGKILL."""
    path = tmp_path / "instance.lock"
    proc = _spawn_holder(path, "run", "crash")
    assert _reap(proc) == -9
    acquire("report", path=path).release()


def test_the_lock_file_and_its_directory_are_private(tmp_path: Path) -> None:
    path = tmp_path / "fresh" / "instance.lock"
    lock = acquire("run", path=path)
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert json.loads(path.read_text(encoding="utf-8"))["command"] == "run"
    finally:
        lock.release()


def test_a_holder_without_details_is_still_described() -> None:
    assert "has not recorded its details" in describe_holder(None)
