"""Unit tests for alphaswarm.inference.types (Task 1 — TDD RED → GREEN)."""

from __future__ import annotations

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
    try:
        r.content = "z"  # type: ignore[misc]
        raise AssertionError("Should have raised FrozenInstanceError")
    except Exception as exc:
        assert "frozen" in type(exc).__name__.lower() or "frozen" in str(exc).lower()


def test_inference_result_all_fields() -> None:
    r = InferenceResult(
        content="hello",
        model="qwen3:8b",
        input_tokens=100,
        output_tokens=50,
        eval_count=50,
        eval_duration_ns=1_000_000,
    )
    assert r.input_tokens == 100
    assert r.output_tokens == 50
    assert r.eval_count == 50
    assert r.eval_duration_ns == 1_000_000
