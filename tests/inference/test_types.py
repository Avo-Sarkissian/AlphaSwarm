"""Unit tests for alphaswarm.inference.types."""

from __future__ import annotations

import dataclasses

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole


def test_inference_result_defaults() -> None:
    r = InferenceResult(content='{"signal":"buy"}', model="m")
    assert r.input_tokens is None and r.output_tokens is None
    assert r.content == '{"signal":"buy"}'


def test_provider_role_values() -> None:
    assert ProviderRole.WORKER.value == "worker"


def test_provider_role_orchestrator() -> None:
    assert ProviderRole.ORCHESTRATOR.value == "orchestrator"


def test_inference_result_frozen() -> None:
    """InferenceResult must be immutable (frozen dataclass)."""
    r = InferenceResult(content="x", model="y", input_tokens=10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.content = "z"  # type: ignore[misc]


def test_inference_result_all_fields() -> None:
    r = InferenceResult(
        content="hello",
        model="qwen3:8b",
        input_tokens=100,
        output_tokens=50,
        prefill_ms=40.0,
        decode_ms=900.0,
    )
    assert (r.input_tokens, r.output_tokens, r.prefill_ms, r.decode_ms) == (100, 50, 40.0, 900.0)
