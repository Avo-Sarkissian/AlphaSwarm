"""The dead Ollama parallelism settings are gone; old .env files still load."""

from __future__ import annotations

import pytest

from alphaswarm.settings import PROJECT_ROOT, AppSettings, OllamaSettings


def test_retired_fields_are_gone() -> None:
    assert "num_parallel" not in OllamaSettings.model_fields
    assert "max_loaded_models" not in OllamaSettings.model_fields


def test_existing_env_with_retired_keys_still_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every install copied ALPHASWARM_OLLAMA__NUM_PARALLEL=16 from .env.example."""
    monkeypatch.setenv("ALPHASWARM_OLLAMA__NUM_PARALLEL", "16")
    monkeypatch.setenv("ALPHASWARM_OLLAMA__MAX_LOADED_MODELS", "2")
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    assert getattr(settings.ollama, "num_parallel", None) is None
    assert settings.ollama.worker_model_alias == "alphaswarm-worker"


def test_retired_keys_are_dropped_with_one_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class _RecordingLog:
        def warning(self, event: str, **context: object) -> None:
            events.append((event, context))

    monkeypatch.setattr("alphaswarm.settings.log", _RecordingLog())
    OllamaSettings.model_validate({"num_parallel": 16, "max_loaded_models": 2})
    assert [e for e, _ in events] == ["ollama_retired_settings_ignored"]
    assert events[0][1]["keys"] == ["max_loaded_models", "num_parallel"]


def test_env_example_no_longer_sets_retired_keys() -> None:
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ALPHASWARM_OLLAMA__NUM_PARALLEL" not in text
    assert "ALPHASWARM_OLLAMA__MAX_LOADED_MODELS" not in text
    assert "OLLAMA_NUM_PARALLEL=4" in text
