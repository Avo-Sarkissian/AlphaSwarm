"""atomic_write_text: temp file in the same directory, fsync, os.replace.

See docs/DECISIONS.md#adr-background-tasks.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from alphaswarm.fsutil import atomic_write_text


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_writes_text_and_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.md"
    atomic_write_text(target, "# Report\n")
    assert target.read_text(encoding="utf-8") == "# Report\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")
def test_default_mode_is_owner_only_and_custom_mode_is_exact(tmp_path: Path) -> None:
    owner_only = tmp_path / "a.json"
    shared = tmp_path / "b.md"
    atomic_write_text(owner_only, "{}")
    atomic_write_text(shared, "x", mode=0o644)
    assert _mode(owner_only) == 0o600
    assert _mode(shared) == 0o644


def test_replaces_existing_file_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.md"]


def test_failed_replace_keeps_old_content_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "out.md"
    target.write_text("old", encoding="utf-8")

    def _boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("alphaswarm.fsutil.os.replace", _boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.md"]
