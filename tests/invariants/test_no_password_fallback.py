"""No test guesses the Neo4j password (docs/DECISIONS.md#adr-tests-scoped-cleanup).

A missing ALPHASWARM_NEO4J__PASSWORD must skip with a clear message, never fall
back to a literal; the neo4j-test credential is a separate, documented constant.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# A literal default in an env lookup: os.environ.get("…NEO4J__PASSWORD", "<literal>") or
# os.getenv(…). monkeypatch.setenv("…NEO4J__PASSWORD", "fictional") is not a fallback.
_FALLBACK = re.compile(r"""(?:environ\.get|getenv)\(\s*["'][A-Z0-9_]*NEO4J__PASSWORD["']\s*,\s*["']""")


def test_no_test_falls_back_to_a_literal_neo4j_password() -> None:
    hits = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in sorted((ROOT / "tests").rglob("*.py"))
        if not re.search(r" [2-9]\.py$", path.name)
        # This module's positive control spells out the old fallback on purpose.
        if path != Path(__file__).resolve()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _FALLBACK.search(line)
    ]
    assert hits == [], f"literal password fallback at {hits}; skip with a clear message instead"


def test_the_pattern_recognises_the_old_fallback() -> None:
    """Positive control: the scan above is not vacuous."""
    old = 'auth=("neo4j", os.environ.get("ALPHASWARM_NEO4J__PASSWORD", "x"))'
    assert _FALLBACK.search(old)
    assert not _FALLBACK.search('monkeypatch.setenv("ALPHASWARM_NEO4J__PASSWORD", "x")')
