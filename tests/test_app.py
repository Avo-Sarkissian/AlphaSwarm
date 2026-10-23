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


def test_main_entry_point(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entry point prints startup banner with correct values when no subcommand given."""
    clear_alphaswarm_env(monkeypatch)
    # Set sys.argv to simulate no-args invocation (banner mode)
    monkeypatch.setattr("sys.argv", ["alphaswarm"])

    from alphaswarm.__main__ import main

    main()
    captured = capsys.readouterr()

    from alphaswarm import __version__

    assert f"AlphaSwarm v{__version__}" in captured.out
    assert "Agents: 100 across 10 brackets" in captured.out
    # hermetic_env keeps .env out of AppSettings, so the defaults are exact.
    assert "Orchestrator: qwen3.6:27b-nvfp4" in captured.out
    assert "Workers: qwen3.6:35b-a3b-nvfp4" in captured.out


def test_main_invalid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid config causes sys.exit(1) in banner mode."""
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "INVALID")
    # Set sys.argv to simulate no-args invocation (banner mode)
    monkeypatch.setattr("sys.argv", ["alphaswarm"])

    from alphaswarm.__main__ import main

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


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
