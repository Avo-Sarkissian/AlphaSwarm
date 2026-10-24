"""Swarm-side modules never import the portfolio-derived advisory code (docs/DECISIONS.md#adr-ticker-resolution)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "alphaswarm"
SWARM_SIDE = ("ingestion/tickers.py", "seed.py", "market_context.py", "prompts/decision.py", "prompts/modifiers.py")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("rel", SWARM_SIDE)
def test_swarm_side_module_never_imports_the_advisory(rel: str) -> None:
    path = SRC / rel
    assert path.exists(), f"{rel} is listed as swarm-side but does not exist"
    offenders = {
        m for m in _imported_modules(path) if m == "alphaswarm.advisory" or m.startswith("alphaswarm.advisory.")
    }
    assert offenders == set(), f"{rel} imports {sorted(offenders)}"
