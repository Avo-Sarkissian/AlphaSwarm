"""Every relative link and anchor in the project's Markdown resolves."""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Final
from urllib.parse import unquote

import pytest

from tests.support.markdown import anchors, links

ROOT: Final = Path(__file__).resolve().parents[1]
_SCHEME: Final = re.compile(r"^[a-z][a-z0-9+.-]*:")
# Private planning documents describe the baseline on purpose and may stay unpublished.
EXCLUDED: Final = frozenset({"docs/IMPROVEMENT_PLAN.md"})


def _documents() -> list[Path]:
    candidates = [
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "CLAUDE.md",
        ROOT / "frontend" / "TESTING.md",
        *sorted((ROOT / "docs").glob("*.md")),
    ]
    return [p for p in candidates if p.is_file() and p.relative_to(ROOT).as_posix() not in EXCLUDED]


@functools.cache
def _anchors(path: Path) -> frozenset[str]:
    return frozenset(anchors(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("doc", _documents(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_resolve(doc: Path) -> None:
    problems: list[str] = []
    for line, target in links(doc.read_text(encoding="utf-8")):
        if _SCHEME.match(target):
            continue
        path_part, _, fragment = target.partition("#")
        dest = doc if not path_part else (doc.parent / unquote(path_part)).resolve()
        if not dest.exists():
            problems.append(f"line {line}: {target} (no such file)")
        elif fragment and dest.suffix == ".md" and fragment not in _anchors(dest):
            problems.append(f"line {line}: {target} (no such anchor)")
    assert problems == []
