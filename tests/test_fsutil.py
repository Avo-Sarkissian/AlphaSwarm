"""atomic_write_text: temp file in the same directory, fsync, os.replace.

See docs/DECISIONS.md#adr-background-tasks.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from alphaswarm.fsutil import atomic_write_text, prune_old_files


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


def _touch(path: Path, mtime_s: int) -> None:
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (mtime_s, mtime_s))


def test_prune_keeps_the_newest_matching_files(tmp_path: Path) -> None:
    for index in range(5):
        _touch(tmp_path / f"c{index}_advisory.json", 1_000 + index)
    _touch(tmp_path / "notes.txt", 1)
    deleted = prune_old_files(tmp_path, "*_advisory.json", keep=2)
    assert [p.name for p in deleted] == [
        "c0_advisory.json",
        "c1_advisory.json",
        "c2_advisory.json",
    ]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "c3_advisory.json",
        "c4_advisory.json",
        "notes.txt",
    ]


def test_prune_ignores_temp_files_symlinks_and_missing_dirs(tmp_path: Path) -> None:
    _touch(tmp_path / "a_advisory.json", 1)
    (tmp_path / ".b_advisory.json.123.abcd.tmp").write_text("x", encoding="utf-8")
    (tmp_path / "link_advisory.json").symlink_to(tmp_path / "a_advisory.json")
    assert prune_old_files(tmp_path, "*_advisory.json", keep=1) == []
    assert prune_old_files(tmp_path / "missing", "*_advisory.json", keep=1) == []


def test_prune_rejects_keep_below_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        prune_old_files(tmp_path, "*", keep=0)
