"""Shared fixtures for AlphaSwarm tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs

if TYPE_CHECKING:
    from alphaswarm.types import AgentPersona, BracketConfig


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all ALPHASWARM_ environment variables."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def default_settings(monkeypatch: pytest.MonkeyPatch) -> AppSettings:
    """Return AppSettings with a clean environment (no .env influence)."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture()
def all_brackets() -> list[BracketConfig]:
    """Return default bracket configurations."""
    return load_bracket_configs()


@pytest.fixture()
def all_personas() -> list[AgentPersona]:
    """Return all 100 generated personas."""
    return generate_personas(load_bracket_configs())
