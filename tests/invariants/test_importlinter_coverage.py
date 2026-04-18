"""REVIEW HIGH (Codex): drift-resistant coverage test for the importlinter contract.

Problem: a manually curated `source_modules` list in pyproject.toml drifts the moment
someone adds a new package under src/alphaswarm/. The new package would silently
escape the forbidden-import rule.

Solution: enumerate `src/alphaswarm/` subpackages dynamically, parse pyproject.toml,
and assert that EVERY enumerated package dotted path is either listed in source_modules
OR is one of the three known non-source entries:
  - alphaswarm.advisory         (D-04 whitelist — allowed to import holdings)
  - alphaswarm.web.routes.holdings (D-04 whitelist)
  - alphaswarm.holdings         (the forbidden target itself)
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
SRC = ROOT / "src" / "alphaswarm"
PYPROJECT = ROOT / "pyproject.toml"

# D-04 whitelist + forbidden target — packages that legitimately do NOT appear in source_modules
_KNOWN_NON_SOURCE: frozenset[str] = frozenset(
    {
        "alphaswarm.advisory",
        "alphaswarm.web.routes.holdings",
        "alphaswarm.holdings",
    }
)


def _enumerate_actual_packages() -> set[str]:
    """Walk src/alphaswarm and return every package dotted path.

    A 'package' is any directory containing __init__.py; a 'module' at the top level
    of a package is a .py file (but we do NOT enumerate modules — source_modules in
    importlinter is package-level).

    We include:
      - src/alphaswarm/X/ for every subdir X with __init__.py  → alphaswarm.X
      - src/alphaswarm/web/Y/ for every subdir Y with __init__.py  → alphaswarm.web.Y
      - src/alphaswarm/web/routes/Z/ for every subdir Z with __init__.py  → alphaswarm.web.routes.Z

    Plus top-level .py modules in src/alphaswarm/ (e.g., alphaswarm.logging.py → alphaswarm.logging)
    and in src/alphaswarm/web/ and src/alphaswarm/web/routes/.
    """
    found: set[str] = set()

    def _walk(dir_path: Path, dotted_prefix: str) -> None:
        if not dir_path.is_dir():
            return
        for child in dir_path.iterdir():
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            if child.is_dir() and (child / "__init__.py").exists():
                pkg = f"{dotted_prefix}.{child.name}"
                found.add(pkg)
                _walk(child, pkg)
            elif child.is_file() and child.suffix == ".py":
                mod = f"{dotted_prefix}.{child.stem}"
                found.add(mod)

    _walk(SRC, "alphaswarm")
    return found


def _load_source_modules_from_pyproject() -> set[str]:
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    contracts = data["tool"]["importlinter"]["contracts"]
    for c in contracts:
        if c.get("type") == "forbidden" and "alphaswarm.holdings" in c.get("forbidden_modules", []):
            return set(c["source_modules"])
    raise AssertionError("No forbidden contract for alphaswarm.holdings found in pyproject.toml")


def test_source_modules_covers_every_actual_package() -> None:
    """REVIEW HIGH (Codex): every package under src/alphaswarm/ must be either
    in source_modules or in the explicit allowlist. New packages cannot silently
    escape the forbidden-import rule.
    """
    actual = _enumerate_actual_packages()
    source_modules = _load_source_modules_from_pyproject()

    uncovered: set[str] = set()
    for pkg in actual:
        if pkg in source_modules:
            continue
        if pkg in _KNOWN_NON_SOURCE:
            continue
        # Submodules of whitelisted packages are ALSO implicitly allowlisted
        # (e.g., alphaswarm.advisory.pipeline is under alphaswarm.advisory)
        if any(pkg.startswith(w + ".") for w in _KNOWN_NON_SOURCE):
            continue
        # Submodules of forbidden target are not source_modules themselves
        if pkg.startswith("alphaswarm.holdings."):
            continue
        uncovered.add(pkg)

    assert uncovered == set(), (
        f"Packages under src/alphaswarm/ are NOT listed in pyproject.toml "
        f"[tool.importlinter] source_modules AND not in the D-04 allowlist "
        f"{_KNOWN_NON_SOURCE}:\n  {sorted(uncovered)}\n"
        "Fix: add each uncovered package to source_modules in pyproject.toml, "
        "OR add it to _KNOWN_NON_SOURCE here if it is a new D-04-approved whitelist entry "
        "(requires design review and CONTEXT.md update)."
    )


def test_source_modules_does_not_list_whitelisted_packages() -> None:
    """Inverse check: packages that ARE allowed to import holdings must NOT
    appear in source_modules (D-04)."""
    source_modules = _load_source_modules_from_pyproject()
    for allowed in ("alphaswarm.advisory", "alphaswarm.web.routes.holdings"):
        assert allowed not in source_modules, (
            f"{allowed} is in source_modules but is on the D-04 whitelist — "
            "it is allowed to import alphaswarm.holdings and must be excluded."
        )


def test_forbidden_modules_is_exactly_alphaswarm_holdings() -> None:
    """The contract's forbidden list should be exactly alphaswarm.holdings.
    Additional forbidden targets (e.g. alphaswarm.billing) require a separate contract."""
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    contracts = data["tool"]["importlinter"]["contracts"]
    contract = next(
        c
        for c in contracts
        if c.get("type") == "forbidden"
        and "alphaswarm.holdings" in c.get("forbidden_modules", [])
    )
    assert contract["forbidden_modules"] == ["alphaswarm.holdings"], (
        "Holdings isolation contract must forbid ONLY alphaswarm.holdings. "
        f"Current: {contract['forbidden_modules']}"
    )
