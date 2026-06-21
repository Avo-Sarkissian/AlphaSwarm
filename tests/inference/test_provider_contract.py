"""Unit tests for InferenceProvider protocol + error hierarchy (Task 2 — TDD RED → GREEN)."""

from __future__ import annotations

import pytest

from alphaswarm.errors import AuthError, BudgetExceededError, InferenceError, OllamaInferenceError
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

# ---------------------------------------------------------------------------
# FakeInferenceProvider: protocol conformance + call recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_provider_satisfies_protocol_and_records() -> None:
    fake = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake",
        scripted=[InferenceResult(content='{"signal":"hold"}', model="fake")],
    )
    assert isinstance(fake, InferenceProvider)
    out = await fake.chat(
        [{"role": "user", "content": "hi"}],
        response_schema={"type": "object"},
    )
    assert out.content == '{"signal":"hold"}'
    assert fake.calls[0]["response_schema"] == {"type": "object"}


@pytest.mark.asyncio
async def test_fake_provider_records_all_kwargs() -> None:
    fake = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "fake-orch",
        scripted=[InferenceResult(content="ok", model="fake-orch")],
    )
    await fake.chat(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        json_mode=True,
        temperature=0.7,
        max_tokens=256,
    )
    call = fake.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    assert call["json_mode"] is True
    assert call["temperature"] == 0.7
    assert call["max_tokens"] == 256
    assert call["response_schema"] is None


@pytest.mark.asyncio
async def test_fake_provider_exhausted_raises_assertion() -> None:
    fake = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake",
        scripted=[],  # empty — immediate exhaustion
    )
    with pytest.raises(AssertionError):
        await fake.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_fake_provider_callable_scripted() -> None:
    def make_result(**_: object) -> InferenceResult:
        return InferenceResult(content="dynamic", model="fake")

    fake = FakeInferenceProvider(ProviderRole.WORKER, "fake", scripted=make_result)
    out = await fake.chat([{"role": "user", "content": "hi"}])
    assert out.content == "dynamic"


@pytest.mark.asyncio
async def test_fake_provider_noop_lifecycle() -> None:
    fake = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake",
        scripted=[InferenceResult(content="x", model="fake")],
    )
    await fake.prepare()
    await fake.teardown()
    await fake.aclose()


def test_fake_provider_is_local_default() -> None:
    fake = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake",
        scripted=[],
    )
    assert fake.is_local() is True


def test_fake_provider_is_local_false() -> None:
    fake = FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake",
        scripted=[],
        is_local=False,
    )
    assert fake.is_local() is False


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_inference_error_attributes() -> None:
    err = InferenceError("something broke", provider="openai", model="gpt-4o")
    assert str(err) == "something broke"
    assert err.provider == "openai"
    assert err.model == "gpt-4o"
    assert err.original_error is None


def test_inference_error_with_original() -> None:
    orig = ValueError("raw")
    err = InferenceError("wrapped", provider="anthropic", model="claude-3", original_error=orig)
    assert err.original_error is orig


def test_ollama_inference_error_is_inference_error() -> None:
    """OllamaInferenceError must be a subclass of InferenceError."""
    err = OllamaInferenceError("timeout", model="qwen3:8b")
    assert isinstance(err, InferenceError)
    assert err.provider == "ollama"
    assert err.model == "qwen3:8b"
    assert err.original_error is None


def test_ollama_inference_error_with_original() -> None:
    orig = ConnectionError("connect")
    err = OllamaInferenceError("conn fail", model="llama3", original_error=orig)
    assert err.original_error is orig
    assert isinstance(err, InferenceError)


def test_auth_error_is_inference_error() -> None:
    err = AuthError("401", provider="openai", model="gpt-4o")
    assert isinstance(err, InferenceError)
    assert err.provider == "openai"


def test_budget_exceeded_error_attributes() -> None:
    err = BudgetExceededError(spent_usd=5.50, cap_usd=5.00)
    assert err.spent_usd == 5.50
    assert err.cap_usd == 5.00
    assert not isinstance(err, InferenceError)  # standalone, per spec


def test_budget_exceeded_error_is_exception() -> None:
    err = BudgetExceededError(spent_usd=1.0, cap_usd=0.5)
    assert isinstance(err, Exception)
    assert "1.0" in str(err) or "0.5" in str(err)
