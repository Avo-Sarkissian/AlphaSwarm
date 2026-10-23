"""mypy overrides only shrink: the exempt modules are exactly ALLOWED_OVERRIDES."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# Modules that still carry strict-mode errors and have an ignore_errors override in
# pyproject.toml. An entry leaves this set in the change that removes its override, as
# its module is cleaned up; nothing is ever added.
ALLOWED_OVERRIDES = frozenset(
    {
        "alphaswarm.cli",
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


def test_every_allowed_module_is_still_overridden() -> None:
    """A module leaves ALLOWED_OVERRIDES in the change that removes its override."""
    stale = ALLOWED_OVERRIDES - _overridden()
    assert not stale, (
        f"{sorted(stale)} have no ignore_errors override in pyproject.toml any more; "
        "delete them from ALLOWED_OVERRIDES so their exemption cannot come back"
    )


def test_mypy_stays_strict() -> None:
    assert _config()["tool"]["mypy"]["strict"] is True
