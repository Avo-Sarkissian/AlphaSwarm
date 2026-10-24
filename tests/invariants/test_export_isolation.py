"""The cycle export never reaches holdings or advisory."""

from __future__ import annotations

import os
import subprocess
import textwrap
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _contracts() -> list[dict[str, Any]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["tool"]["importlinter"]["contracts"])


def test_export_contract_is_declared_exactly() -> None:
    matches = [c for c in _contracts() if c.get("source_modules") == ["alphaswarm.export"]]
    assert len(matches) == 1, matches
    contract = matches[0]
    assert contract["type"] == "forbidden"
    assert sorted(contract["forbidden_modules"]) == ["alphaswarm.advisory", "alphaswarm.holdings"]
    assert not contract.get("ignore_imports")


def test_holdings_contract_stays_first() -> None:
    assert _contracts()[0].get("forbidden_modules") == ["alphaswarm.holdings"]


def test_export_contract_catches_an_indirect_import(tmp_path: Path) -> None:
    pkg = tmp_path / "fake_swarm"
    (pkg / "holdings").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "holdings" / "__init__.py").write_text("SECRET = 'x'\n")
    (pkg / "report.py").write_text("from fake_swarm.holdings import SECRET\n")
    (pkg / "export.py").write_text("from fake_swarm.report import SECRET\n")
    config = tmp_path / "importlinter.ini"
    config.write_text(
        textwrap.dedent(
            """
            [importlinter]
            root_package = fake_swarm

            [importlinter:contract:export]
            name = Synthetic export isolation (must fail)
            type = forbidden
            source_modules =
                fake_swarm.export
            forbidden_modules =
                fake_swarm.holdings
            """
        ).strip()
        + "\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        ["uv", "run", "lint-imports", "--config", str(config), "--no-cache"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0, result.stdout
    assert "fake_swarm.export is not allowed to import fake_swarm.holdings" in result.stdout
