"""ISOL-03 (D-03): programmatic lint-imports invocation against synthetic violations.

This test is the self-documenting regression guard — if someone loosens the
contract in pyproject.toml (removes a source_modules entry, or accidentally
deletes the contract), this test fails because a synthetic violation stops
being detected.

Strategy (REVIEW HIGH — Codex reliability): write a tiny violating module
into a tmp path AND a tiny importlinter config pointing at it, then
subprocess.run lint-imports with explicit PYTHONPATH={tmp_path} and assert
return code != 0.

We use subprocess rather than import_linter.api to avoid pinning to a
specific internal API across import-linter versions.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import tomllib
from pathlib import Path


def test_lint_imports_passes_on_clean_tree() -> None:
    """Baseline: the real tree must pass with the Phase 37 contract in place."""
    result = subprocess.run(["uv", "run", "lint-imports"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, (
        f"lint-imports failed on clean tree.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_lint_imports_detects_synthetic_violation(tmp_path: Path) -> None:
    """Create a fake package tree + config where a source_module imports holdings.

    lint-imports must exit non-zero, proving the contract catches violations.
    REVIEW HIGH (Codex) — uses subprocess with explicit PYTHONPATH for reproducibility.
    """
    # Fake package tree
    pkg_root = tmp_path / "fake_alphaswarm"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("")
    (pkg_root / "holdings").mkdir()
    (pkg_root / "holdings" / "__init__.py").write_text("SECRET = 'x'\n")
    # Violator: simulation module that imports holdings
    (pkg_root / "simulation.py").write_text(
        textwrap.dedent(
            """
            from fake_alphaswarm.holdings import SECRET  # THIS IS THE VIOLATION
            """
        ).strip()
        + "\n"
    )

    # Synthetic import-linter config pointing at the fake tree
    config = tmp_path / "importlinter.ini"
    config.write_text(
        textwrap.dedent(
            """
            [importlinter]
            root_package = fake_alphaswarm

            [importlinter:contract:holdings_isolation_synthetic]
            name = Synthetic holdings isolation (must fail)
            type = forbidden
            source_modules =
                fake_alphaswarm.simulation
            forbidden_modules =
                fake_alphaswarm.holdings
            """
        ).strip()
        + "\n"
    )

    # REVIEW HIGH (Codex) — explicit PYTHONPATH prepended so fake pkg is importable
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        ["uv", "run", "lint-imports", "--config", str(config)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0, (
        "lint-imports did NOT detect the synthetic violation — the contract machinery is "
        f"broken or the config was malformed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_pyproject_toml_contains_forbidden_contract_for_holdings() -> None:
    """Meta-test: the pyproject.toml must continue to carry the contract block.

    Catches the case where someone deletes the [tool.importlinter] section.
    """
    pyproject = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
    assert "[tool.importlinter]" in pyproject
    assert 'root_package = "alphaswarm"' in pyproject
    assert 'type = "forbidden"' in pyproject
    assert 'forbidden_modules = ["alphaswarm.holdings"]' in pyproject
    # Whitelist invariant: advisory and web.routes.holdings must NOT appear in source_modules
    # (they are the two allowed importers).
    contract_block = pyproject.split("[[tool.importlinter.contracts]]", 1)[1]
    assert '"alphaswarm.advisory"' not in contract_block, (
        "alphaswarm.advisory must NOT appear in forbidden source_modules (D-04 whitelist)"
    )
    assert '"alphaswarm.web.routes.holdings"' not in contract_block, (
        "alphaswarm.web.routes.holdings must NOT appear in forbidden source_modules (D-04 whitelist)"
    )


def _contracts() -> list[dict[str, object]]:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return list(data["tool"]["importlinter"]["contracts"])


def test_pyproject_declares_the_acyclic_siblings_contract() -> None:
    acyclic = [c for c in _contracts() if c.get("type") == "acyclic_siblings"]
    assert len(acyclic) == 1
    assert acyclic[0]["ancestors"] == ["alphaswarm"]
    assert "ignore_imports" not in acyclic[0]


def test_lint_imports_detects_a_synthetic_cycle(tmp_path: Path) -> None:
    """The acyclic machinery fails on a two-module cycle (guards the contract type).

    A config or usage error (an unknown contract type, a missing field) also exits
    non-zero, so the test asserts the contract's BROKEN verdict, not only the exit code.
    """
    pkg = tmp_path / "fake_cycle"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "alpha.py").write_text("from fake_cycle import beta  # noqa: F401\n")
    (pkg / "beta.py").write_text("from fake_cycle import alpha  # noqa: F401\n")
    config = tmp_path / "importlinter.ini"
    config.write_text(
        textwrap.dedent(
            """
            [importlinter]
            root_package = fake_cycle

            [importlinter:contract:acyclic_synthetic]
            name = Synthetic acyclic siblings (must fail)
            type = acyclic_siblings
            ancestors =
                fake_cycle
            """
        ).strip()
        + "\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        ["uv", "run", "lint-imports", "--config", str(config)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Synthetic acyclic siblings (must fail) BROKEN" in result.stdout, output
    assert "Contracts: 0 kept, 1 broken." in result.stdout, output


def test_pyproject_declares_the_engine_contract() -> None:
    engine = [
        c
        for c in _contracts()
        if c.get("type") == "forbidden" and "alphaswarm.ollama_client" in c.get("forbidden_modules", [])  # type: ignore[operator]
    ]
    assert len(engine) == 1
    assert set(engine[0]["source_modules"]) == {  # type: ignore[arg-type]
        "alphaswarm.simulation",
        "alphaswarm.rounds",
        "alphaswarm.peers",
    }
    assert set(engine[0]["forbidden_modules"]) == {  # type: ignore[arg-type]
        "alphaswarm.inference.ollama_provider",
        "alphaswarm.ollama_client",
        "alphaswarm.ollama_models",
    }
