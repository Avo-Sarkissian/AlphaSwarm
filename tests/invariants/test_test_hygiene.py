"""Test-suite hygiene invariants."""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
_REDUNDANT_ASYNCIO_MARKER = re.compile(r"\s*@pytest\.mark\.asyncio(\(\))?\s*")
# Files whose bare marker sits inside a pytester source string, not on a real test:
# test_marker_policy.py uses one to prove the session-loop marker wins over it.
_PYTESTER_SOURCES = frozenset({"test_marker_policy.py"})


def test_no_redundant_asyncio_markers() -> None:
    """asyncio_mode = "auto" makes a bare asyncio marker redundant.

    Markers with arguments (for example loop_scope="session") are allowed.
    """
    offenders = [
        f"{path.relative_to(TESTS_ROOT)}:{lineno}"
        for path in sorted(TESTS_ROOT.rglob("*.py"))
        if path.relative_to(TESTS_ROOT).as_posix() not in _PYTESTER_SOURCES
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _REDUNDANT_ASYNCIO_MARKER.fullmatch(line)
    ]
    assert offenders == [], f"remove redundant markers: {offenders}"
