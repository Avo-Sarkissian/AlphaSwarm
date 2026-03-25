"""Tests for AppState container and entry point."""

from __future__ import annotations

import os

import pytest
import structlog

from alphaswarm.app import create_app_state
from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
from alphaswarm.governor import ResourceGovernor


@pytest.fixture(autouse=True)
def reset_structlog() -> None:  # noqa: PT004
    """Reset structlog state after each test."""
    yield  # type: ignore[misc]
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_create_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppState factory creates a properly initialized container."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    settings = AppSettings()
    personas = generate_personas(load_bracket_configs())
    app_state = create_app_state(settings, personas)

    assert app_state.settings.app_name == "AlphaSwarm"
    assert len(app_state.personas) == 100
    assert app_state.governor.current_limit == 8
    assert app_state.state_store.snapshot().agent_count == 100


def test_main_entry_point(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entry point prints startup banner with correct values when no subcommand given."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    # Set sys.argv to simulate no-args invocation (banner mode)
    monkeypatch.setattr("sys.argv", ["alphaswarm"])

    from alphaswarm.__main__ import main

    main()
    captured = capsys.readouterr()

    assert "AlphaSwarm v0.1.0" in captured.out
    assert "Agents: 100 across 10 brackets" in captured.out
    assert "Orchestrator: qwen3.5:32b" in captured.out
    assert "Workers: qwen3.5:7b" in captured.out


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
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager

    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    personas = generate_personas(load_bracket_configs())
    app = create_app_state(settings, personas, with_ollama=True)

    assert isinstance(app.ollama_client, OllamaClient)
    assert isinstance(app.model_manager, OllamaModelManager)


def test_create_app_state_without_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_app_state default (with_ollama=False) has None for ollama fields."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    personas = generate_personas(load_bracket_configs())
    app = create_app_state(settings, personas)

    assert app.ollama_client is None
    assert app.model_manager is None
