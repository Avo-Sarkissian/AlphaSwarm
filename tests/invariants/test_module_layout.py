"""Where each name lives after the config split."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

MOVED: dict[str, tuple[str, ...]] = {
    "alphaswarm.settings": (
        "AppSettings",
        "OllamaSettings",
        "Neo4jSettings",
        "GovernorSettings",
        "SimulationSettings",
        "PROJECT_ROOT",
    ),
    "alphaswarm.inference.config": (
        "ProviderType",
        "RoleConfig",
        "ProviderLimits",
        "ModelPrice",
        "InferenceConfig",
        "INFERENCE_CONFIG_PATH",
        "default_inference_config",
        "load_inference_config",
        "save_inference_config",
        "masked_config",
    ),
    "alphaswarm.personas": (
        "BRACKET_MODIFIERS",
        "DEFAULT_BRACKETS",
        "load_bracket_configs",
        "validate_bracket_counts",
        "generate_personas",
        "persona_to_worker_config",
        "compute_prompt_template_hash",
    ),
    "alphaswarm.peers": (
        "PeerContextsResult",
        "build_peer_contexts",
        "compute_exposure_metrics",
        "format_peer_context",
        "peer_rng",
        "select_diverse_peers",
    ),
    "alphaswarm.prompts.decision": ("JSON_OUTPUT_INSTRUCTIONS",),
    "alphaswarm.prompts.modifiers": (
        "MODIFIER_GENERATION_PROMPT",
        "MODIFIER_CHAR_LIMIT",
        "build_modifier_user_message",
        "truncate_modifier",
    ),
    "alphaswarm.seed": ("generate_modifiers", "inject_seed"),
    "alphaswarm.security.sanitize": (
        "sanitize_entity_name",
        "sanitize_headline",
        "HEADLINE_MAX_LEN",
        "sanitize_rationale",
        "sanitize_peer_rationale",
    ),
}


def test_worker_persona_config_is_a_domain_type() -> None:
    from alphaswarm import types

    assert types.WorkerPersonaConfig.__module__ == "alphaswarm.types"


@pytest.mark.parametrize("module", ["alphaswarm.config", "alphaswarm.utils"])
def test_split_modules_are_gone(module: str) -> None:
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize(("module", "names"), sorted(MOVED.items()))
def test_names_live_in_their_new_module(module: str, names: tuple[str, ...]) -> None:
    mod = importlib.import_module(module)
    assert [name for name in names if not hasattr(mod, name)] == []


def test_project_root_still_resolves_to_the_repository() -> None:
    """.secrets/, reports/ and advisory/ resolve against the repo root."""
    from alphaswarm.settings import PROJECT_ROOT, AppSettings

    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "src" / "alphaswarm" / "settings.py").is_file()
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.resolve_path(Path(".secrets/inference.json")) == (PROJECT_ROOT / ".secrets" / "inference.json")


def test_inference_config_path_default_matches() -> None:
    """settings.py cannot import inference.config (cycle), so the default is a literal."""
    from alphaswarm.inference.config import INFERENCE_CONFIG_PATH
    from alphaswarm.settings import AppSettings

    assert AppSettings.model_fields["inference_config_path"].default == INFERENCE_CONFIG_PATH


def test_peer_helpers_left_simulation() -> None:
    import alphaswarm.simulation as simulation

    for name in ("select_diverse_peers", "peer_rng", "_format_peer_context", "_build_diverse_peer_contexts"):
        assert not hasattr(simulation, name), name
