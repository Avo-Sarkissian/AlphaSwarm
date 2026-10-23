"""Tests for AppState container and entry point."""

from __future__ import annotations

import pytest
import structlog

from alphaswarm.app import create_app_state
from alphaswarm.governor import ResourceGovernor
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.settings import AppSettings
from tests.conftest import clear_alphaswarm_env


@pytest.fixture(autouse=True)
def reset_structlog() -> None:  # noqa: PT004
    """Reset structlog state after each test."""
    yield  # type: ignore[misc]
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_create_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppState factory creates a properly initialized container."""
    clear_alphaswarm_env(monkeypatch)

    settings = AppSettings()
    personas = generate_personas(load_bracket_configs())
    app_state = create_app_state(settings, personas)

    assert app_state.settings.app_name == "AlphaSwarm"
    assert len(app_state.personas) == 100
    assert app_state.governor.current_limit == 8
    # No run has started, so the roster is empty (begin_run installs it at SEEDING).
    assert app_state.state_store.snapshot().agent_count == 0


def test_create_app_state_publishes_the_configured_round_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The idle frame carries ALPHASWARM_NUM_ROUNDS before any run has started."""
    clear_alphaswarm_env(monkeypatch)
    monkeypatch.setenv("ALPHASWARM_NUM_ROUNDS", "2")

    app_state = create_app_state(AppSettings(), generate_personas(load_bracket_configs()))

    assert app_state.state_store.snapshot().num_rounds == 2


def test_main_entry_point_prints_help(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python -m alphaswarm` without a subcommand prints help and exits 0."""
    monkeypatch.setattr("sys.argv", ["alphaswarm"])

    from alphaswarm.__main__ import main

    main()  # returns normally: exit code 0
    captured = capsys.readouterr()
    assert captured.out.startswith("usage: alphaswarm")
    assert captured.err == ""


def test_main_invalid_config_exits_2(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settings validation error inside a subcommand exits 2 with one line."""
    from alphaswarm import cli

    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "INVALID")
    monkeypatch.setattr(cli, "_handle_inject", lambda rumor: AppSettings())
    monkeypatch.setattr(
        "sys.argv",
        ["alphaswarm", "inject", "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."],
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
    assert capsys.readouterr().err.startswith("Configuration error:")


async def test_governor_stub_async() -> None:
    """ResourceGovernor async context manager works without errors."""
    governor = ResourceGovernor()
    async with governor:
        pass
    assert governor.current_limit == 8
    assert governor.active_count == 0


def test_create_app_state_with_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_app_state with with_ollama=True creates OllamaClient and OllamaModelManager."""
    clear_alphaswarm_env(monkeypatch)

    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager

    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    personas = generate_personas(load_bracket_configs())
    app = create_app_state(settings, personas, with_ollama=True)

    assert isinstance(app.ollama_client, OllamaClient)
    assert isinstance(app.model_manager, OllamaModelManager)


def test_create_app_state_without_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_app_state default (with_ollama=False) has None for ollama fields."""
    clear_alphaswarm_env(monkeypatch)

    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    personas = generate_personas(load_bracket_configs())
    app = create_app_state(settings, personas)

    assert app.ollama_client is None
    assert app.model_manager is None


def test_create_app_state_passes_neo4j_timeouts() -> None:
    from unittest.mock import patch

    from alphaswarm.settings import Neo4jSettings

    settings = AppSettings(  # type: ignore[call-arg]
        _env_file=None,
        neo4j=Neo4jSettings(
            password="test-only-not-a-secret",
            query_timeout_s=12.0,
            connection_acquisition_timeout=4.0,
        ),
    )
    with patch("neo4j.AsyncGraphDatabase.driver") as driver_factory:
        app_state = create_app_state(settings, [], with_neo4j=True)

    assert driver_factory.call_args.kwargs["connection_acquisition_timeout"] == 4.0
    assert app_state.graph_manager is not None
    assert app_state.graph_manager._query_timeout_s == 12.0
