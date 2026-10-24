"""Per-user single-instance lock (docs/DECISIONS.md#adr-instance-lock).

``alphaswarm web`` and the CLI's ``run``, ``inject`` and ``report`` share the two
Ollama aliases, and each process unloads them at its own idle gaps, so two of
them evict each other's models. Each takes one ``fcntl.flock`` on a per-user
file outside the repo without blocking; a second process exits (code 75)
naming the first. The kernel drops the lock when the holder exits, even on a
crash, so there is no stale-pidfile cleanup.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from pathlib import Path
from typing import Final

ENV_OVERRIDE: Final = "ALPHASWARM_INSTANCE_LOCK"
_HOLDER_MAX_BYTES: Final = 4096


def default_lock_path() -> Path:
    """``~/.alphaswarm/instance.lock``, or ``$ALPHASWARM_INSTANCE_LOCK`` when set."""
    override = os.environ.get(ENV_OVERRIDE)
    return Path(override) if override else Path.home() / ".alphaswarm" / "instance.lock"


#: Resolved at import; tests point it at a temporary file (tests/conftest.py).
DEFAULT_LOCK_PATH: Path = default_lock_path()


def describe_holder(holder: dict[str, object] | None) -> str:
    """One sentence naming the process that holds the lock."""
    if not holder:
        return "Another AlphaSwarm process is starting or running (it has not recorded its details yet). Stop it first."
    parts = [f"pid {holder.get('pid', '?')}", f"since {holder.get('started_at', '?')}"]
    if holder.get("detail"):
        parts.append(str(holder["detail"]))
    return (
        f"AlphaSwarm is already running: `alphaswarm {holder.get('command', '?')}` "
        f"({', '.join(parts)}). Only one AlphaSwarm process may use the models at a "
        "time: use that one (the web UI runs simulations and reports) or stop it first."
    )


class InstanceLockHeldError(RuntimeError):
    """Another AlphaSwarm process holds the lock; ``str()`` describes it."""

    def __init__(self, holder: dict[str, object] | None, path: Path) -> None:
        super().__init__(describe_holder(holder))
        self.holder = holder
        self.path = path


class InstanceLock:
    """A held lock. ``release()`` drops it and may be called more than once."""

    def __init__(self, path: Path, fd: int) -> None:
        self.path = path
        self._fd: int | None = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)  # no stale details for the next reader
        os.close(fd)  # closing the descriptor drops the flock


def acquire(command: str, *, detail: str | None = None, path: Path | None = None) -> InstanceLock:
    """Take the lock without blocking, or raise InstanceLockHeldError naming the holder."""
    target = path if path is not None else DEFAULT_LOCK_PATH
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = _read_holder(fd)
        os.close(fd)
        raise InstanceLockHeldError(holder, target) from None
    except BaseException:
        os.close(fd)
        raise
    info = {
        "pid": os.getpid(),
        "command": command,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "detail": detail,
    }
    os.ftruncate(fd, 0)
    os.pwrite(fd, json.dumps(info).encode("utf-8"), 0)
    return InstanceLock(target, fd)


def _read_holder(fd: int) -> dict[str, object] | None:
    try:
        raw = os.pread(fd, _HOLDER_MAX_BYTES, 0)
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
