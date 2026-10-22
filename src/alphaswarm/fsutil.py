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
