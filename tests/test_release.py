"""Release metadata agrees: one version source and a well-formed changelog."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Final

from tests.support.scripts import load_script

ROOT: Final = Path(__file__).resolve().parents[1]
CHANGELOG: Final = ROOT / "CHANGELOG.md"
OLDER_ENTRY: Final = re.compile(r"^## v\d+\.\d+ — (\d{4}-\d{2}-\d{2})$")


def _project() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project: dict[str, object] = tomllib.load(handle)["project"]
    return project


def test_changelog_top_entry_matches_the_package_version() -> None:
    entry = load_script("docs_sync").changelog_top_entry(CHANGELOG.read_text(encoding="utf-8"))
    assert entry.version == _project()["version"]


def test_changelog_entries_are_well_formed_and_newest_first() -> None:
    headings = [ln for ln in CHANGELOG.read_text(encoding="utf-8").splitlines() if ln.startswith("## ")]
    top = load_script("docs_sync").changelog_top_entry(headings[0])
    older = [OLDER_ENTRY.match(heading) for heading in headings[1:]]
    assert all(older), [h for h, m in zip(headings[1:], older, strict=True) if m is None]
    dates = [m.group(1) for m in older if m is not None]
    assert dates == sorted(dates, reverse=True)
    assert top.date is None or top.date >= dates[0]


def test_release_notes_for_the_top_entry_have_absolute_links() -> None:
    docs_sync = load_script("docs_sync")
    text = CHANGELOG.read_text(encoding="utf-8")
    notes = docs_sync.release_notes(text, docs_sync.changelog_top_entry(text).tag)
    relative = [t for t in re.findall(r"\]\(([^)\s]+)\)", notes) if not re.match(r"^(https://|#)", t)]
    assert relative == []
    assert "<!--" not in notes


def test_version_literal_is_not_hard_coded() -> None:
    version = str(_project()["version"])
    offenders = [
        path.relative_to(ROOT).as_posix()
        for base in (ROOT / "src", ROOT / "frontend" / "src")
        for path in base.rglob("*")
        if path.suffix in {".py", ".ts", ".tsx"}
        and "__tests__" not in path.parts
        and version in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_package_metadata_points_at_the_changelog() -> None:
    urls = _project()["urls"]
    assert isinstance(urls, dict)
    assert urls["Changelog"] == "https://github.com/Avo-Sarkissian/AlphaSwarm/blob/master/CHANGELOG.md"
