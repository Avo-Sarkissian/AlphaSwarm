"""The autouse hermetic_env fixture isolates tests from the operator's machine.

No ALPHASWARM_* variables, no .env, and an inference config path under the
pytest temp dir, so the real .secrets/inference.json is never read. The holdings
CSV path is redirected too, so no test can load the real portfolio
(docs/DECISIONS.md#adr-tests-scoped-cleanup).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from alphaswarm.config import (
    AppSettings,
    InferenceConfig,
    ProviderType,
    RoleConfig,
    load_inference_config,
    save_inference_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_only_the_hermetic_variables_are_set(hermetic_env: Path) -> None:
    present = sorted(key for key in os.environ if key.startswith("ALPHASWARM_"))
    assert present == ["ALPHASWARM_HOLDINGS_CSV_PATH", "ALPHASWARM_INFERENCE_CONFIG_PATH"]
    assert os.environ["ALPHASWARM_INFERENCE_CONFIG_PATH"] == str(hermetic_env)


def test_the_holdings_csv_path_never_points_at_real_data(hermetic_env: Path) -> None:
    csv_path = AppSettings().holdings_csv_path
    assert csv_path.parent == hermetic_env.parent
    assert not csv_path.exists()


def test_the_inference_config_path_is_outside_the_repo(hermetic_env: Path) -> None:
    configured = AppSettings().inference_config_path
    assert configured == hermetic_env
    assert REPO_ROOT not in configured.resolve().parents


def test_dotenv_files_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "ALPHASWARM_APP_NAME=FromDotEnv\nALPHASWARM_DEBUG=true\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    settings = AppSettings()
    assert settings.app_name == "AlphaSwarm"
    assert settings.debug is False


def test_clean_env_keeps_the_hermetic_paths(clean_env: None, hermetic_env: Path) -> None:
    assert os.environ.get("ALPHASWARM_INFERENCE_CONFIG_PATH") == str(hermetic_env)
    assert "ALPHASWARM_HOLDINGS_CSV_PATH" in os.environ


def test_default_settings_use_the_hermetic_config_path(
    default_settings: AppSettings, hermetic_env: Path
) -> None:
    assert default_settings.inference_config_path == hermetic_env


def test_a_saved_cloud_config_is_visible_inside_the_test(hermetic_env: Path) -> None:
    role = RoleConfig(
        provider=ProviderType.ANTHROPIC, model="claude-fictional", api_key="sk-fictional-1111"
    )
    save_inference_config(InferenceConfig(orchestrator=role, worker=role), settings=AppSettings())
    assert hermetic_env.is_file()
    assert load_inference_config(AppSettings()).orchestrator.provider == ProviderType.ANTHROPIC


def test_the_next_test_starts_from_local_defaults(hermetic_env: Path) -> None:
    """Runs right after the save above: the per-test reset deleted the file."""
    assert not hermetic_env.exists()
    assert load_inference_config(AppSettings()).orchestrator.provider == ProviderType.OLLAMA


def test_an_exported_neo4j_password_never_reaches_a_test() -> None:
    """A developer shell may export ALPHASWARM_NEO4J__PASSWORD (or any other
    ALPHASWARM_* value); hermetic_env must strip it before the first test runs.
    Runs one test of this file in a child pytest with fictional values exported."""
    env = {
        **os.environ,
        "ALPHASWARM_NEO4J__PASSWORD": "fictional-not-a-secret",
        "ALPHASWARM_DEBUG": "true",
    }
    target = f"{Path(__file__).resolve()}::test_only_the_hermetic_variables_are_set"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
