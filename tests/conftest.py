"""Shared fixtures for AlphaSwarm tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from alphaswarm.config import AppSettings, GovernorSettings, generate_personas, load_bracket_configs
from alphaswarm.governor import ResourceGovernor
from alphaswarm.worker import WorkerPersonaConfig

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


# ---------------------------------------------------------------------------
# Phase 3: Resource governance fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_governor() -> ResourceGovernor:
    """ResourceGovernor with default GovernorSettings for unit testing.

    Uses default settings (baseline_parallel=8) with no state_store wiring.
    """
    return ResourceGovernor(GovernorSettings())


@pytest.fixture()
def sample_personas() -> list[WorkerPersonaConfig]:
    """4 WorkerPersonaConfig dicts for batch dispatch testing."""
    return [
        WorkerPersonaConfig(
            agent_id="quants_01",
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt="test",
            risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="quants_02",
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt="test",
            risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="degens_01",
            bracket="degens",
            influence_weight=0.3,
            temperature=1.2,
            system_prompt="test",
            risk_profile="0.95",
        ),
        WorkerPersonaConfig(
            agent_id="degens_02",
            bracket="degens",
            influence_weight=0.3,
            temperature=1.2,
            system_prompt="test",
            risk_profile="0.95",
        ),
    ]
