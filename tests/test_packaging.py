"""Package metadata, license, version single source and console scripts (T12.7).

The version lives in exactly one place, pyproject.toml; alphaswarm.__version__
reads it back through importlib.metadata, and the frontend package mirrors it.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

import alphaswarm

ROOT = Path(__file__).resolve().parent.parent

# SPDX id -> first line of the LICENSE file. Gate G-11 branch B adds its entry here.
LICENSE_HEADERS: dict[str, str] = {"MIT": "MIT License"}


def _pyproject() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _reload_package() -> None:
    importlib.reload(alphaswarm)


def test_version_comes_from_installed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9")
    try:
        _reload_package()
        assert alphaswarm.__version__ == "9.9.9"
    finally:
        monkeypatch.undo()
        _reload_package()


def test_version_falls_back_when_metadata_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _missing)
    try:
        _reload_package()
        assert alphaswarm.__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        _reload_package()


def test_installed_metadata_matches_pyproject_version() -> None:
    """Fails after a version bump until `uv sync` re-installs the editable package."""
    assert importlib.metadata.version("alphaswarm") == _pyproject()["project"]["version"]
    assert alphaswarm.__version__ == _pyproject()["project"]["version"]


def test_version_is_plain_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _pyproject()["project"]["version"])


def test_package_is_imported_from_this_checkout() -> None:
    """A stale .venv after a repo move would import an old copy of the source."""
    package_file = Path(alphaswarm.__file__).resolve()
    assert package_file.is_relative_to((ROOT / "src").resolve())


def test_console_scripts_are_declared() -> None:
    assert _pyproject()["project"]["scripts"] == {
        "alphaswarm": "alphaswarm.cli:main",
        "start": "alphaswarm.cli:main_web",
    }


def test_console_scripts_are_installed() -> None:
    installed = {
        ep.name: ep.value
        for ep in importlib.metadata.entry_points(group="console_scripts")
        if ep.dist is not None and ep.dist.name == "alphaswarm"
    }
    assert installed.get("alphaswarm") == "alphaswarm.cli:main"
    assert installed.get("start") == "alphaswarm.cli:main_web"


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


def test_frontend_package_version_mirrors_backend() -> None:
    version = _pyproject()["project"]["version"]
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version
