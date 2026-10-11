"""Package metadata and license (T12.7).

Task 14 of the Phase 0 plan extends this file with the version source and
console-script checks.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# SPDX id -> first line of the LICENSE file (owner decision G-11).
LICENSE_HEADERS: dict[str, str] = {"MIT": "MIT License"}


def _pyproject() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_project_metadata_is_complete() -> None:
    project = _pyproject()["project"]
    assert project["readme"] == "README.md"
    assert project["license"] in LICENSE_HEADERS
    assert project["license-files"] == ["LICENSE"]
    assert {"name": "Avo Sarkissian"} in project["authors"]
    assert set(project["urls"]) == {"Homepage", "Repository", "Issues", "Changelog"}
    assert project["urls"]["Repository"] == "https://github.com/Avo-Sarkissian/AlphaSwarm"


def test_license_file_matches_declared_license() -> None:
    spdx = _pyproject()["project"]["license"]
    lines = (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == LICENSE_HEADERS[spdx]
    assert any("Avo Sarkissian" in line for line in lines[:5])
