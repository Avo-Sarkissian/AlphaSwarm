"""Tests for inference config models, file persistence, and key masking.

TDD: these tests were written before the implementation (RED → GREEN).
Persistence format: JSON (not TOML — robust Decimal round-trip via pydantic v2
model_dump_json/model_validate_json, no extra dependency).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from alphaswarm.config import (
    AppSettings,
    ModelPrice,
    ProviderLimits,
    ProviderType,
    default_inference_config,
    load_inference_config,
    masked_config,
    save_inference_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_settings() -> AppSettings:
    """Return an AppSettings with no ALPHASWARM_ env overrides."""
    # Avoid polluting the clean env: use a fresh instance with defaults.
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# default_inference_config
# ---------------------------------------------------------------------------


def test_default_inference_config_both_ollama() -> None:
    """Both roles default to OLLAMA provider type."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    assert cfg.orchestrator.provider == ProviderType.OLLAMA
    assert cfg.worker.provider == ProviderType.OLLAMA


def test_default_inference_config_model_aliases() -> None:
    """Model fields use the alias names from OllamaSettings."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    assert cfg.orchestrator.model == settings.ollama.orchestrator_model_alias
    assert cfg.worker.model == settings.ollama.worker_model_alias


def test_default_inference_config_base_url() -> None:
    """Both roles carry the Ollama base_url."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    assert cfg.orchestrator.base_url == settings.ollama.base_url
    assert cfg.worker.base_url == settings.ollama.base_url


def test_default_inference_config_no_api_keys() -> None:
    """Local default has no API keys."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    assert cfg.orchestrator.api_key is None
    assert cfg.worker.api_key is None


def test_default_inference_config_empty_limits_and_cap() -> None:
    """Default config has empty limits dict and no spend cap."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    assert cfg.limits == {}
    assert cfg.spend_cap_usd is None
    assert cfg.pricing_overrides == {}


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------


def test_save_load_round_trip_basic(tmp_path: Path) -> None:
    """Save then load returns an identical InferenceConfig."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "inference.json"

    save_inference_config(cfg, dest)
    loaded = load_inference_config(settings, dest)

    assert loaded.orchestrator == cfg.orchestrator
    assert loaded.worker == cfg.worker
    assert loaded.limits == cfg.limits
    assert loaded.spend_cap_usd == cfg.spend_cap_usd
    assert loaded.pricing_overrides == cfg.pricing_overrides


def test_save_load_round_trip_decimal_precision(tmp_path: Path) -> None:
    """Decimal spend_cap_usd survives the JSON round-trip with exact equality."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    cfg = cfg.model_copy(update={"spend_cap_usd": Decimal("12.345678")})
    dest = tmp_path / "inference.json"

    save_inference_config(cfg, dest)
    loaded = load_inference_config(settings, dest)

    assert loaded.spend_cap_usd == Decimal("12.345678")


def test_save_load_round_trip_pricing_overrides(tmp_path: Path) -> None:
    """Decimal values inside pricing_overrides survive the JSON round-trip."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    price = ModelPrice(
        input_per_mtok=Decimal("0.15"),
        output_per_mtok=Decimal("0.60"),
    )
    cfg = cfg.model_copy(update={"pricing_overrides": {"gpt-4o": price}})
    dest = tmp_path / "inference.json"

    save_inference_config(cfg, dest)
    loaded = load_inference_config(settings, dest)

    assert loaded.pricing_overrides["gpt-4o"].input_per_mtok == Decimal("0.15")
    assert loaded.pricing_overrides["gpt-4o"].output_per_mtok == Decimal("0.60")


def test_save_load_round_trip_api_key(tmp_path: Path) -> None:
    """API key survives the round-trip (raw key stored in the file)."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    orch = cfg.orchestrator.model_copy(update={"api_key": "sk-secret-1234"})
    cfg = cfg.model_copy(update={"orchestrator": orch})
    dest = tmp_path / "inference.json"

    save_inference_config(cfg, dest)
    loaded = load_inference_config(settings, dest)

    assert loaded.orchestrator.api_key == "sk-secret-1234"


def test_save_load_round_trip_limits(tmp_path: Path) -> None:
    """ProviderLimits dict round-trips through JSON correctly."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    limits = {ProviderType.OPENAI_COMPATIBLE: ProviderLimits(requests_per_min=60, max_in_flight=8)}
    cfg = cfg.model_copy(update={"limits": limits})
    dest = tmp_path / "inference.json"

    save_inference_config(cfg, dest)
    loaded = load_inference_config(settings, dest)

    assert ProviderType.OPENAI_COMPATIBLE in loaded.limits
    assert loaded.limits[ProviderType.OPENAI_COMPATIBLE].requests_per_min == 60
    assert loaded.limits[ProviderType.OPENAI_COMPATIBLE].max_in_flight == 8


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    """save_inference_config creates intermediate directories if needed."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "nested" / "dir" / "inference.json"

    save_inference_config(cfg, dest)

    assert dest.exists()


# ---------------------------------------------------------------------------
# Missing file → default
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_default(tmp_path: Path) -> None:
    """Loading from a non-existent path returns the default local config."""
    settings = _clean_settings()
    missing = tmp_path / "does_not_exist.json"

    loaded = load_inference_config(settings, missing)

    assert loaded.orchestrator.provider == ProviderType.OLLAMA
    assert loaded.worker.provider == ProviderType.OLLAMA


# ---------------------------------------------------------------------------
# Malformed JSON → ValueError
# ---------------------------------------------------------------------------


def test_load_malformed_json_raises_value_error(tmp_path: Path) -> None:
    """A corrupt JSON file raises ValueError — not a silent fallback."""
    settings = _clean_settings()
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{this is not valid json!!!")

    with pytest.raises(ValueError):
        load_inference_config(settings, bad_file)


def test_load_invalid_schema_raises_value_error(tmp_path: Path) -> None:
    """Valid JSON that doesn't match InferenceConfig schema raises ValueError."""
    settings = _clean_settings()
    bad_file = tmp_path / "bad_schema.json"
    bad_file.write_text('{"orchestrator": "not_a_role_config"}')

    with pytest.raises(ValueError):
        load_inference_config(settings, bad_file)


# ---------------------------------------------------------------------------
# masked_config — key masking
# ---------------------------------------------------------------------------


def test_masked_config_no_raw_key_in_output() -> None:
    """The raw API key must never appear anywhere in the masked output."""
    secret = "sk-super-secret-key-abcd1234"
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    orch = cfg.orchestrator.model_copy(
        update={"api_key": secret, "provider": ProviderType.OPENAI_COMPATIBLE}
    )
    cfg = cfg.model_copy(update={"orchestrator": orch})

    result = masked_config(cfg)
    serialized = json.dumps(result)

    assert secret not in serialized, "Raw API key leaked into masked output"


def test_masked_config_key_present_reports_set_true_and_last4() -> None:
    """When a key is set, masked output reports set=True and last4."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    orch = cfg.orchestrator.model_copy(update={"api_key": "sk-abcd"})
    cfg = cfg.model_copy(update={"orchestrator": orch})

    result = masked_config(cfg)

    orch_out = result["orchestrator"]
    assert orch_out["api_key"]["set"] is True
    assert orch_out["api_key"]["last4"] == "abcd"


def test_masked_config_key_absent_reports_set_false_and_null() -> None:
    """When no key is set, masked output reports set=False and last4=None."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    result = masked_config(cfg)

    orch_out = result["orchestrator"]
    assert orch_out["api_key"]["set"] is False
    assert orch_out["api_key"]["last4"] is None


def test_masked_config_worker_key_also_masked() -> None:
    """Worker role key is also masked, not leaked."""
    secret = "bearer-worker-xyz9"
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    worker = cfg.worker.model_copy(update={"api_key": secret})
    cfg = cfg.model_copy(update={"worker": worker})

    result = masked_config(cfg)
    serialized = json.dumps(result)

    assert secret not in serialized
    assert result["worker"]["api_key"]["set"] is True
    assert result["worker"]["api_key"]["last4"] == "xyz9"


def test_masked_config_preserves_non_key_fields() -> None:
    """Non-key fields (provider, model, base_url, limits) pass through unchanged."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)

    result = masked_config(cfg)

    assert result["orchestrator"]["provider"] == ProviderType.OLLAMA.value
    assert result["orchestrator"]["model"] == settings.ollama.orchestrator_model_alias
    assert result["orchestrator"]["base_url"] == settings.ollama.base_url


def test_masked_config_spend_cap_included() -> None:
    """spend_cap_usd appears in the masked output (as string, not Decimal)."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    cfg = cfg.model_copy(update={"spend_cap_usd": Decimal("50.00")})

    result = masked_config(cfg)

    # Decimals serialized as strings in JSON-safe dict
    assert str(result["spend_cap_usd"]) == "50.00"
