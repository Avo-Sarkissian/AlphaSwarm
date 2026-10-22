"""Runtime paths resolve against the repository root, not the working directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaswarm.config import (
    PROJECT_ROOT,
    AppSettings,
    default_inference_config,
    load_inference_config,
    save_inference_config,
)


def _settings(**overrides: object) -> AppSettings:
    return AppSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_project_root_is_the_repository() -> None:
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "src" / "alphaswarm" / "config.py").is_file()


def test_relative_paths_anchor_at_project_root_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert _settings().resolve_path(Path("reports")) == PROJECT_ROOT / "reports"


def test_absolute_and_home_paths_are_kept(tmp_path: Path) -> None:
    s = _settings()
    assert s.resolve_path(tmp_path / "x") == tmp_path / "x"
    assert s.resolve_path(Path("~/alphaswarm-x")) == Path.home() / "alphaswarm-x"


def test_output_dir_defaults_and_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings()
    assert (s.reports_dir, s.advisory_dir) == (Path("reports"), Path("advisory"))
    monkeypatch.setenv("ALPHASWARM_REPORTS_DIR", "/tmp/alphaswarm-reports")
    monkeypatch.setenv("ALPHASWARM_ADVISORY_DIR", "/tmp/alphaswarm-advisory")
    s = _settings()
    assert s.reports_dir == Path("/tmp/alphaswarm-reports")
    assert s.advisory_dir == Path("/tmp/alphaswarm-advisory")


def test_inference_config_round_trips_through_resolved_path(tmp_path: Path) -> None:
    s = _settings(inference_config_path=tmp_path / "inference.json")
    save_inference_config(default_inference_config(s), settings=s)
    assert (tmp_path / "inference.json").is_file()
    assert load_inference_config(s) == default_inference_config(s)


def test_relative_inference_path_ignores_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "rel").mkdir()
    (tmp_path / "rel" / "inference.json").write_text("not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    s = _settings(inference_config_path=Path("rel/inference.json"))
    # Resolves to PROJECT_ROOT/rel/inference.json, which does not exist -> defaults,
    # instead of parsing the garbage file in the working directory.
    assert load_inference_config(s) == default_inference_config(s)
