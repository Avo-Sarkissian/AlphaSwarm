"""Tests for inference config models, file persistence, and key masking.

TDD: these tests were written before the implementation (RED → GREEN).
Persistence format: JSON (not TOML — robust Decimal round-trip via pydantic v2
model_dump_json/model_validate_json, no extra dependency).
"""

from __future__ import annotations

import json
import os
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from alphaswarm.inference.config import (
    InferenceConfig,
    ModelPrice,
    ProviderLimits,
    ProviderType,
    RoleConfig,
    default_inference_config,
    load_inference_config,
    masked_config,
    save_inference_config,
)
from alphaswarm.settings import AppSettings

# POSIX mode bits are meaningless on Windows (os.chmod there only toggles the
# read-only flag), and save_inference_config skips them on non-POSIX platforms.
posix_only = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX file mode bits; save_inference_config skips chmod elsewhere",
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
# File permissions — the config stores raw API keys (S1 / CWE-276)
# ---------------------------------------------------------------------------


def _mode(path: Path) -> int:
    """Return the permission bits of *path*."""
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_save_writes_owner_only_file(tmp_path: Path) -> None:
    """The saved config file is readable/writable by its owner only."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "secrets" / "inference.json"

    save_inference_config(cfg, dest)

    assert _mode(dest) == 0o600


@posix_only
def test_save_creates_owner_only_parent_dir(tmp_path: Path) -> None:
    """A directory created for the config file is owner-only."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "secrets" / "inference.json"

    save_inference_config(cfg, dest)

    assert _mode(dest.parent) == 0o700


@posix_only
def test_save_tightens_existing_permissive_dir(tmp_path: Path) -> None:
    """An existing world-readable directory is tightened (mkdir(mode=) is a no-op)."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    os.chmod(secrets_dir, 0o755)

    save_inference_config(cfg, secrets_dir / "inference.json")

    assert _mode(secrets_dir) == 0o700


@posix_only
def test_save_does_not_chmod_symlinked_parent_target(tmp_path: Path) -> None:
    """A symlinked config directory must not have its TARGET chmod-ed (CWE-59).

    ``Path.mkdir(exist_ok=True)`` happily accepts a symlink to an existing
    directory, so a path-based chmod here would let whoever can create that
    entry point it at an arbitrary directory the operator owns and have it
    forced to 0700. The directory mode step must skip instead of redirect.
    """
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    victim = tmp_path / "victim"
    victim.mkdir()
    os.chmod(victim, 0o755)
    link = tmp_path / "secrets"
    link.symlink_to(victim, target_is_directory=True)

    save_inference_config(cfg, link / "inference.json")

    # The unrelated directory keeps its own permissions...
    assert _mode(victim) == 0o755
    # ...and the secret file itself is still written owner-only.
    assert _mode(victim / "inference.json") == 0o600


@posix_only
def test_save_repairs_existing_permissive_file(tmp_path: Path) -> None:
    """An already-written 0644 config file is repaired on the next save."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "inference.json"
    dest.write_text("{}", encoding="utf-8")
    os.chmod(dest, 0o644)

    save_inference_config(cfg, dest)

    assert _mode(dest) == 0o600


@posix_only
def test_save_temp_file_owner_only_at_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The temp file carries 0600 from creation — never a world-readable window.

    The spy runs while the temp file exists but before the serialized config
    (which contains the raw API key) has been written into it.
    """
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "secrets" / "inference.json"
    tmp_file = dest.with_name(f"{dest.name}.tmp")
    observed: list[int] = []
    original = InferenceConfig.model_dump_json

    def _spy(self: InferenceConfig, *args: Any, **kwargs: Any) -> str:
        observed.append(_mode(tmp_file))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(InferenceConfig, "model_dump_json", _spy)

    save_inference_config(cfg, dest)

    assert observed == [0o600]


@posix_only
def test_save_tightens_stale_permissive_temp_file(tmp_path: Path) -> None:
    """A stale 0644 temp file from an interrupted save does not leak the mode.

    O_CREAT only applies the mode when it creates the file, so the mode is
    re-applied to the open descriptor before anything is written.
    """
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    dest = tmp_path / "inference.json"
    stale = dest.with_name(f"{dest.name}.tmp")
    stale.write_text("stale", encoding="utf-8")
    os.chmod(stale, 0o644)

    save_inference_config(cfg, dest)

    assert _mode(dest) == 0o600
    assert not stale.exists()


def test_save_keeps_api_key_readable_by_owner(tmp_path: Path) -> None:
    """Hardened permissions do not break the owner's own read-back."""
    settings = _clean_settings()
    cfg = default_inference_config(settings)
    orch = cfg.orchestrator.model_copy(update={"api_key": "sk-secret-1234"})
    cfg = cfg.model_copy(update={"orchestrator": orch})
    dest = tmp_path / "secrets" / "inference.json"

    save_inference_config(cfg, dest)

    assert load_inference_config(settings, dest).orchestrator.api_key == "sk-secret-1234"


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
    orch = cfg.orchestrator.model_copy(update={"api_key": secret, "provider": ProviderType.OPENAI_COMPATIBLE})
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


# ---------------------------------------------------------------------------
# Injectable config path: tests never read the real file
# (docs/DECISIONS.md#adr-tests-scoped-cleanup)
# ---------------------------------------------------------------------------


def _cloud_cfg() -> InferenceConfig:
    """A cloud-only config with a fictional key."""
    role = RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-fictional", api_key="sk-fictional-0000")
    return InferenceConfig(orchestrator=role, worker=role)


def test_inference_config_path_defaults_to_the_secrets_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHASWARM_INFERENCE_CONFIG_PATH", raising=False)
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.inference_config_path == Path(".secrets/inference.json")


def test_inference_config_path_reads_the_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "custom.json"
    monkeypatch.setenv("ALPHASWARM_INFERENCE_CONFIG_PATH", str(target))
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.inference_config_path == target


def test_load_reads_the_settings_path_when_no_path_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # a CWD-relative default can never reach the real file
    target = tmp_path / "inference.json"
    save_inference_config(_cloud_cfg(), target)
    settings = AppSettings(_env_file=None, inference_config_path=target)  # type: ignore[call-arg]
    assert load_inference_config(settings).orchestrator.provider == ProviderType.ANTHROPIC


def test_save_writes_the_settings_path_when_no_path_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "nested" / "inference.json"
    settings = AppSettings(_env_file=None, inference_config_path=target)  # type: ignore[call-arg]
    save_inference_config(_cloud_cfg(), settings=settings)
    assert target.is_file()
    assert load_inference_config(settings).worker.provider == ProviderType.ANTHROPIC


def test_an_explicit_path_wins_over_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from_settings = tmp_path / "from_settings.json"
    explicit = tmp_path / "explicit.json"
    settings = AppSettings(  # type: ignore[call-arg]
        _env_file=None, inference_config_path=from_settings
    )
    save_inference_config(_cloud_cfg(), explicit, settings=settings)
    assert explicit.is_file()
    assert not from_settings.exists()
    assert load_inference_config(settings, explicit).orchestrator.provider == ProviderType.ANTHROPIC
    assert load_inference_config(settings).orchestrator.provider == ProviderType.OLLAMA


def test_allow_cloud_advisory_defaults_off_and_round_trips(tmp_path: Path) -> None:
    dest = tmp_path / "inference.json"
    assert _cloud_cfg().allow_cloud_advisory is False
    save_inference_config(_cloud_cfg().model_copy(update={"allow_cloud_advisory": True}), dest)
    assert load_inference_config(AppSettings(_env_file=None), dest).allow_cloud_advisory is True  # type: ignore[call-arg]


def test_a_config_file_written_before_the_flag_existed_loads_with_the_flag_off(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "inference.json"
    dest.write_text(
        '{"orchestrator": {"provider": "anthropic", "model": "claude-fictional", '
        '"api_key": "sk-fictional-2222"}, '
        '"worker": {"provider": "ollama", "model": "alphaswarm-worker"}}',
        encoding="utf-8",
    )
    assert load_inference_config(AppSettings(_env_file=None), dest).allow_cloud_advisory is False  # type: ignore[call-arg]


def test_avg_tokens_per_call_defaults_to_1500_and_must_be_positive() -> None:
    from pydantic import ValidationError

    assert ProviderLimits().avg_tokens_per_call == 1500
    assert ProviderLimits(avg_tokens_per_call=900).avg_tokens_per_call == 900
    with pytest.raises(ValidationError):
        ProviderLimits(avg_tokens_per_call=0)


def test_saved_configs_without_the_field_still_load() -> None:
    raw = (
        '{"orchestrator": {"provider": "ollama", "model": "alphaswarm-orchestrator"},'
        ' "worker": {"provider": "ollama", "model": "alphaswarm-worker"},'
        ' "limits": {"openai_compatible": {"requests_per_min": 40, "max_in_flight": 1, "max_retries": 8}}}'
    )
    cfg = InferenceConfig.model_validate_json(raw)
    assert cfg.limits[ProviderType.OPENAI_COMPATIBLE].avg_tokens_per_call == 1500
