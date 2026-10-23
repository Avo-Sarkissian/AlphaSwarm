"""Filesystem helpers.

``atomic_write_text`` makes report and advisory writes all-or-nothing: readers
see the old file or the complete new one, never a truncated file
(docs/DECISIONS.md#adr-background-tasks).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write *text* to *path* atomically with permission bits exactly *mode*.

    Writes a uniquely named temp file in the same directory, fsyncs it and
    ``os.replace``s it over *path*. Creates the parent directory. Synchronous:
    async callers wrap it in ``asyncio.to_thread``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        if os.name == "posix":
            os.fchmod(fd, mode)  # undo the umask so the file has exactly `mode`
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def prune_old_files(directory: Path, pattern: str, *, keep: int) -> list[Path]:
    """Delete all but the *keep* newest regular files in *directory* matching *pattern*.

    "Newest" is by modification time, ties broken by name. Symlinks and
    sub-directories are never touched, so a dangling or hostile link cannot
    redirect a delete; the ``.tmp`` files atomic_write_text uses do not match an
    ``*_advisory.json`` pattern. A missing directory yields []. Returns the
    deleted paths, oldest first. Synchronous: async callers wrap it in
    ``asyncio.to_thread``. Advisory files hold cost-basis exposure, so only the
    newest are kept (docs/DECISIONS.md#adr-holdings-isolation).
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not directory.is_dir():
        return []
    candidates = [p for p in directory.glob(pattern) if p.is_file() and not p.is_symlink()]
    candidates.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
    deleted: list[Path] = []
    for path in candidates[: max(0, len(candidates) - keep)]:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        deleted.append(path)
    return deleted
