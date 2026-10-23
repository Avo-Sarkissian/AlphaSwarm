"""alphaswarm.inference stays cheap to import."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import alphaswarm.inference as inference

HEAVY = (
    "anthropic",
    "httpx",
    "ollama",
    "alphaswarm.inference.anthropic_provider",
    "alphaswarm.inference.budget",
    "alphaswarm.inference.factory",
    "alphaswarm.inference.openai_provider",
)
EAGER = {"InferenceMessage", "InferenceProvider", "InferenceResult", "ProviderRole"}


def test_importing_types_loads_no_sdk() -> None:
    code = f"import sys, alphaswarm.inference.types; print(','.join(m for m in {HEAVY!r} if m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("name", sorted(getattr(inference, "_LAZY_EXPORTS", {"<missing>": ""})))
def test_lazy_names_resolve_to_their_submodule_objects(name: str) -> None:
    module = importlib.import_module(inference._LAZY_EXPORTS[name])
    assert getattr(inference, name) is getattr(module, name)


def test_all_lists_the_eager_and_lazy_names_once() -> None:
    assert set(inference.__all__) == EAGER | set(inference._LAZY_EXPORTS)
    assert len(inference.__all__) == len(set(inference.__all__))


def test_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="has no attribute 'NoSuchProvider'"):
        _ = inference.NoSuchProvider
