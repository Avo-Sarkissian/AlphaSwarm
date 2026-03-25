"""Tests for AppSettings and bracket definitions."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from alphaswarm.config import AppSettings
from alphaswarm.types import BracketType

if TYPE_CHECKING:
    from alphaswarm.types import BracketConfig


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default settings match expected values with clean env."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.app_name == "AlphaSwarm"
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.ollama.orchestrator_model == "qwen3.5:32b"
    assert settings.ollama.worker_model == "qwen3.5:7b"
    assert settings.ollama.num_parallel == 16
    assert settings.neo4j.uri == "bolt://localhost:7687"
    assert settings.governor.baseline_parallel == 8
    assert settings.governor.memory_throttle_percent == 80.0
    assert settings.governor.memory_pause_percent == 90.0


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override default settings."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALPHASWARM_DEBUG", "true")
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ALPHASWARM_OLLAMA__NUM_PARALLEL", "4")
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.debug is True
    assert settings.log_level == "DEBUG"
    assert settings.ollama.num_parallel == 4


def test_settings_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid log level raises ValidationError."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "INVALID")
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None)  # type: ignore[call-arg]


def test_settings_invalid_governor_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out-of-range governor percent raises ValidationError."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALPHASWARM_GOVERNOR__MEMORY_PAUSE_PERCENT", "150")
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None)  # type: ignore[call-arg]


def test_bracket_definitions(all_brackets: list[BracketConfig]) -> None:
    """All 10 brackets are defined with valid, unique attributes."""
    assert len(all_brackets) == 10

    bracket_types = [b.bracket_type for b in all_brackets]
    assert len(set(bracket_types)) == 10

    display_names = [b.display_name for b in all_brackets]
    assert len(set(display_names)) == 10

    assert sum(b.count for b in all_brackets) == 100

    for b in all_brackets:
        assert 0.0 <= b.risk_profile <= 1.0
        assert 0.0 <= b.temperature <= 2.0
        assert len(b.system_prompt_template) > 0


def test_bracket_specific_counts(all_brackets: list[BracketConfig]) -> None:
    """Each bracket has the exact expected agent count."""
    counts = {b.bracket_type: b.count for b in all_brackets}
    assert counts[BracketType.QUANTS] == 10
    assert counts[BracketType.DEGENS] == 20
    assert counts[BracketType.SOVEREIGNS] == 10
    assert counts[BracketType.MACRO] == 10
    assert counts[BracketType.SUITS] == 10
    assert counts[BracketType.INSIDERS] == 10
    assert counts[BracketType.AGENTS] == 15
    assert counts[BracketType.DOOM_POSTERS] == 5
    assert counts[BracketType.POLICY_WONKS] == 5
    assert counts[BracketType.WHALES] == 5


def test_bracket_distinct_risk_profiles(all_brackets: list[BracketConfig]) -> None:
    """All 10 brackets have distinct risk profiles."""
    profiles = [b.risk_profile for b in all_brackets]
    assert len(set(profiles)) == 10


# --- Phase 5: Enriched prompt template tests ---


def test_bracket_template_word_counts(all_brackets: list[BracketConfig]) -> None:
    """Each bracket system_prompt_template is between 100 and 250 words."""
    for b in all_brackets:
        word_count = len(b.system_prompt_template.split())
        assert 100 <= word_count <= 250, (
            f"{b.bracket_type.value} template has {word_count} words, expected 100-250"
        )


def test_bracket_templates_no_todo(all_brackets: list[BracketConfig]) -> None:
    """No system_prompt_template contains TODO markers."""
    for b in all_brackets:
        assert "TODO" not in b.system_prompt_template, (
            f"{b.bracket_type.value} template still contains TODO"
        )


def test_json_output_instructions_fields() -> None:
    """JSON_OUTPUT_INSTRUCTIONS contains all 5 required field names."""
    from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS

    for field in ("signal", "confidence", "sentiment", "rationale", "cited_agents"):
        assert field in JSON_OUTPUT_INSTRUCTIONS, (
            f"JSON_OUTPUT_INSTRUCTIONS missing field: {field}"
        )
