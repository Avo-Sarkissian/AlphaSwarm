"""The layers contract exists and catches an upward import."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"
EXPECTED_LAYERS = [
    "alphaswarm.web",
    "alphaswarm.services",
    "alphaswarm.report : alphaswarm.interview : alphaswarm.simulation : alphaswarm.rounds : alphaswarm.peers",
    "alphaswarm.graph",
]


def _contracts() -> list[dict[str, Any]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["tool"]["importlinter"]["contracts"])


def test_layers_contract_is_declared_without_exceptions() -> None:
    layers = [c for c in _contracts() if c.get("type") == "layers"]
    assert len(layers) == 1, layers
    assert layers[0]["layers"] == EXPECTED_LAYERS
    assert not layers[0].get("ignore_imports")


def test_holdings_contract_stays_first() -> None:
    assert _contracts()[0].get("forbidden_modules") == ["alphaswarm.holdings"]


def test_layers_contract_catches_an_upward_import(tmp_path: Path) -> None:
    pkg = tmp_path / "fake_swarm"
    (pkg / "graph").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "interview.py").write_text("VALUE = 1\n")
    (pkg / "graph" / "__init__.py").write_text("")
    (pkg / "graph" / "manager.py").write_text("from fake_swarm.interview import VALUE\n")
    config = tmp_path / "importlinter.ini"
    config.write_text(
        textwrap.dedent(
            """
            [importlinter]
            root_package = fake_swarm

            [importlinter:contract:layers]
            name = Synthetic layers (must fail)
            type = layers
            layers =
                fake_swarm.interview
                fake_swarm.graph
            """
        ).strip()
        + "\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [str(LINT_IMPORTS), "--config", str(config), "--no-cache"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0, result.stdout
    assert "fake_swarm.graph is not allowed to import fake_swarm.interview" in result.stdout
