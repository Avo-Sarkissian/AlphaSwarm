"""Invariants for the neo4j-test suites.

Every module under tests/neo4j/ carries the neo4j marker: the offline CI job deselects
``-m neo4j``, and an unmarked module would run there without a database (and without
sockets) and fail or silently skip. No test clears NEO4J_PROTECTED_CYCLES, which would
leave the session-scoped seeded cycles unprotected for the rest of the session.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
NEO4J_DIR = TESTS_DIR / "neo4j"
# Built from two parts so this file does not match its own search.
_CLEAR_CALL = "NEO4J_PROTECTED_CYCLES" + ".clear()"


def _modules() -> list[str]:
    return sorted(path.stem for path in NEO4J_DIR.glob("test_*.py"))


def test_neo4j_directory_has_tests() -> None:
    assert _modules()


@pytest.mark.parametrize("name", _modules())
def test_module_is_marked_neo4j(name: str) -> None:
    module = importlib.import_module(f"tests.neo4j.{name}")
    marks = getattr(module, "pytestmark", [])
    marks = marks if isinstance(marks, list) else [marks]
    assert any(mark.name == "neo4j" for mark in marks), (
        f"tests/neo4j/{name}.py needs `pytestmark = pytest.mark.neo4j`"
    )


def test_no_test_clears_the_protected_cycle_set() -> None:
    offenders = sorted(
        str(path.relative_to(TESTS_DIR))
        for path in TESTS_DIR.rglob("*.py")
        if _CLEAR_CALL in path.read_text(encoding="utf-8")
    )
    assert offenders == [], f"remove only the ids you added, never clear the set: {offenders}"
