"""Strict persisted inference config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphaswarm.inference.config import (
    InferenceConfig,
    ModelPrice,
    ProviderLimits,
    ProviderType,
    RoleConfig,
    default_inference_config,
    load_inference_config,
)
from alphaswarm.settings import AppSettings


def _settings(tmp_path: Path, **overrides: object) -> AppSettings:
    return AppSettings(_env_file=None, inference_config_path=tmp_path / "inference.json", **overrides)  # type: ignore[call-arg]


def _role() -> dict[str, object]:
    return {"provider": "ollama", "model": "alphaswarm-worker"}


def test_typo_in_the_stored_file_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / "inference.json").write_text(
        json.dumps({"orchestrator": _role(), "worker": _role(), "spend_cap": "5"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="spend_cap"):
        load_inference_config(_settings(tmp_path))


def test_load_error_names_keys_but_never_values(tmp_path: Path) -> None:
    """A key stored under a misspelled name must not be echoed by the error or its chain."""
    secret = "sk-misplaced-secret-4321"
    (tmp_path / "inference.json").write_text(
        json.dumps({"orchestrator": {**_role(), "apikey": secret}, "worker": _role()}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc_info:
        load_inference_config(_settings(tmp_path))
    exc = exc_info.value
    assert "orchestrator.apikey extra_forbidden" in str(exc)
    for text in (str(exc), repr(exc.__cause__), repr(exc.__context__)):
        assert secret not in text
    assert exc.__suppress_context__ is True


def test_invalid_json_names_no_content(tmp_path: Path) -> None:
    (tmp_path / "inference.json").write_text('{"api_key": "sk-truncated-secret', encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_inference_config(_settings(tmp_path))
    assert "(root) json_invalid" in str(exc_info.value)
    assert "sk-truncated-secret" not in str(exc_info.value)


@pytest.mark.parametrize("field", ["requests_per_min", "tokens_per_min", "max_in_flight"])
def test_zero_limits_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        ProviderLimits(**{field: 0})  # type: ignore[arg-type]


def test_negative_spend_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InferenceConfig.model_validate({"orchestrator": _role(), "worker": _role(), "spend_cap_usd": "-1"})


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (RoleConfig, {**_role(), "apikey": "x"}),
        (ProviderLimits, {"max_in_flight": 2, "max_inflight": 2}),
        (ModelPrice, {"input_per_mtok": "1", "output_per_mtok": "2", "currency": "usd"}),
        (InferenceConfig, {"orchestrator": _role(), "worker": _role(), "budget": 1}),
    ],
)
def test_unknown_keys_are_rejected(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)  # type: ignore[attr-defined]


def test_defaults_still_round_trip(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    cfg = default_inference_config(s)
    assert InferenceConfig.model_validate_json(cfg.model_dump_json()) == cfg
    assert ProviderLimits().max_in_flight == 24
    assert RoleConfig(provider=ProviderType.OLLAMA, model="m").api_key is None


@pytest.mark.parametrize("value", ["info", "Info", "INFO"])
def test_log_level_is_case_insensitive(tmp_path: Path, value: str) -> None:
    assert _settings(tmp_path, log_level=value).log_level == "INFO"


def test_log_level_from_env_is_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "debug")
    assert _settings(tmp_path).log_level == "DEBUG"


def test_unknown_log_level_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _settings(tmp_path, log_level="verbose")
