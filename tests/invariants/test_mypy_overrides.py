"""mypy overrides only shrink: no module outside the original list may be exempted."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# Modules that carried strict-mode errors when mypy was first gated in CI. Entries leave
# this set (and pyproject.toml) as each module is cleaned up; nothing is ever added.
ALLOWED_OVERRIDES = frozenset(
    {
        "alphaswarm.cli",
        "alphaswarm.graph",
        "alphaswarm.report",
        "alphaswarm.simulation",
        "alphaswarm.web.broadcaster",
        "alphaswarm.web.routes.advisory",
        "alphaswarm.web.routes.health",
        "alphaswarm.web.routes.interview",
        "alphaswarm.web.simulation_manager",
    }
)


def _config() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _overridden() -> set[str]:
    mypy = _config()["tool"]["mypy"]
    modules: set[str] = set()
    for override in mypy.get("overrides", []):
        if override.get("ignore_errors"):
            names = override["module"]
            modules.update([names] if isinstance(names, str) else names)
    return modules


def test_mypy_overrides_only_shrink() -> None:
    assert _overridden() <= ALLOWED_OVERRIDES


def test_mypy_stays_strict() -> None:
    assert _config()["tool"]["mypy"]["strict"] is True
