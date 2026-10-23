"""Provider protocol, error hierarchy, and one contract suite over every provider."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import create_autospec

import anthropic
import httpx
import ollama
import pytest

from alphaswarm.config import DEFAULT_BRACKETS, generate_personas
from alphaswarm.errors import AuthError, BudgetExceededError, InferenceError, OllamaInferenceError
from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole
from alphaswarm.ollama_client import OllamaClient
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.types import SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA
from tests.inference.fakes import FakeInferenceProvider, ScriptedProvider

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
    assert str(err) == "Budget cap exceeded: spent $1.0000 > cap $0.5000"


# ---------------------------------------------------------------------------
# Parametrized provider contract suite: every provider, one behaviour contract
# ---------------------------------------------------------------------------

_DECISION: dict[str, Any] = {
    "signal": "buy",
    "confidence": 0.8,
    "sentiment": 0.4,
    "rationale": "contract check",
    "cited_agents": [],
}
_PERSONAS = generate_personas(list(DEFAULT_BRACKETS))
_MESSAGES: list[InferenceMessage] = [
    {"role": "system", "content": _PERSONAS[0].system_prompt},
    {"role": "user", "content": "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics."},
]
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@dataclass(frozen=True)
class ProviderCase:
    name: str
    make_ok: Callable[[], InferenceProvider]
    make_transport_failure: Callable[[], InferenceProvider] | None
    make_auth_failure: Callable[[], InferenceProvider] | None
    expect_local: bool


def _ollama(outcome: ollama.ChatResponse | BaseException) -> InferenceProvider:
    client = create_autospec(OllamaClient, instance=True)
    if isinstance(outcome, BaseException):
        client.chat.side_effect = outcome
    else:
        client.chat.return_value = outcome
    return OllamaProvider(ProviderRole.WORKER, "alphaswarm-worker", client)


_OLLAMA_OK = ollama.ChatResponse(
    model="alphaswarm-worker",
    message=ollama.Message(role="assistant", content=json.dumps(_DECISION)),
    eval_count=12,
    eval_duration=1_000_000,
)


def _openai(handler: Callable[[httpx.Request], httpx.Response]) -> InferenceProvider:
    return OpenAICompatProvider(
        ProviderRole.WORKER,
        "contract-model",
        base_url="https://api.example.com/v1",
        api_key="test-key",
        max_retries=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _openai_ok(request: httpx.Request) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": json.dumps(_DECISION)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return httpx.Response(200, json=body)


def _openai_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _openai_unauthorized(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "invalid api key"})


class _AnthropicMessages:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    async def create(self, **kwargs: Any) -> object:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _AnthropicClient:
    def __init__(self, outcome: object) -> None:
        self.messages = _AnthropicMessages(outcome)

    async def close(self) -> None:
        return None


def _anthropic(outcome: object) -> InferenceProvider:
    return AnthropicProvider(
        ProviderRole.WORKER,
        "claude-contract",
        api_key="test-key",
        max_retries=0,
        client=_AnthropicClient(outcome),  # type: ignore[arg-type]
    )


_ANTHROPIC_OK = SimpleNamespace(
    content=[{"type": "tool_use", "name": "emit_decision", "input": _DECISION}],
    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    stop_reason="tool_use",
)
_ANTHROPIC_DOWN = anthropic.APIConnectionError(request=httpx.Request("POST", _ANTHROPIC_URL))
_ANTHROPIC_UNAUTHORIZED = anthropic.AuthenticationError(
    message="invalid api key",
    response=httpx.Response(401, request=httpx.Request("POST", _ANTHROPIC_URL)),
    body=None,
)


def _fake_ok() -> InferenceProvider:
    return FakeInferenceProvider(
        ProviderRole.WORKER,
        "fake",
        scripted=lambda **_: InferenceResult(content=json.dumps(_DECISION), model="fake"),
    )


PROVIDER_CASES = [
    ProviderCase(
        "ollama",
        lambda: _ollama(_OLLAMA_OK),
        lambda: _ollama(OllamaInferenceError("connection refused", model="alphaswarm-worker")),
        None,
        True,
    ),
    ProviderCase(
        "openai_compatible",
        lambda: _openai(_openai_ok),
        lambda: _openai(_openai_down),
        lambda: _openai(_openai_unauthorized),
        False,
    ),
    ProviderCase(
        "anthropic",
        lambda: _anthropic(_ANTHROPIC_OK),
        lambda: _anthropic(_ANTHROPIC_DOWN),
        lambda: _anthropic(_ANTHROPIC_UNAUTHORIZED),
        False,
    ),
    ProviderCase("fake", _fake_ok, None, None, True),
    ProviderCase("scripted", lambda: ScriptedProvider(personas=_PERSONAS), None, None, True),
]
TRANSPORT_CASES = [c for c in PROVIDER_CASES if c.make_transport_failure is not None]
AUTH_CASES = [c for c in PROVIDER_CASES if c.make_auth_failure is not None]


def _case_id(case: ProviderCase) -> str:
    return case.name


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=_case_id)
async def test_contract_conforms_to_the_protocol(case: ProviderCase) -> None:
    provider = case.make_ok()
    assert isinstance(provider, InferenceProvider)
    assert provider.is_local() is case.expect_local


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=_case_id)
async def test_contract_lifecycle_is_idempotent(case: ProviderCase) -> None:
    provider = case.make_ok()
    await provider.prepare()
    await provider.prepare()
    await provider.teardown()
    await provider.teardown()
    await provider.aclose()
    await provider.aclose()


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=_case_id)
async def test_contract_schema_call_returns_a_parseable_decision(case: ProviderCase) -> None:
    provider = case.make_ok()
    result = await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA, temperature=0.3)
    assert isinstance(result, InferenceResult)
    assert result.model == provider.model
    decision = parse_agent_decision(result.content)
    assert decision.signal is not SignalType.PARSE_ERROR
    assert 0.0 <= decision.confidence <= 1.0


@pytest.mark.parametrize("case", TRANSPORT_CASES, ids=_case_id)
async def test_contract_transport_failure_raises_inference_error(case: ProviderCase) -> None:
    assert case.make_transport_failure is not None
    provider = case.make_transport_failure()
    with pytest.raises(InferenceError):
        await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)


@pytest.mark.parametrize("case", AUTH_CASES, ids=_case_id)
async def test_contract_rejected_credentials_raise_auth_error(case: ProviderCase) -> None:
    assert case.make_auth_failure is not None
    provider = case.make_auth_failure()
    with pytest.raises(AuthError):
        await provider.chat(_MESSAGES, response_schema=DECISION_JSON_SCHEMA)
