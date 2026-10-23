"""Telemetry carried by InferenceResult and filled by every provider."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, get_args

import httpx
import pytest

from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.types import FinishReason, InferenceResult, ProviderRole, count_or_none


def test_inference_result_carries_normalized_telemetry() -> None:
    r = InferenceResult(
        content="{}",
        model="alphaswarm-worker",
        input_tokens=1400,
        output_tokens=150,
        cached_prompt_tokens=0,
        prefill_ms=600.0,
        decode_ms=2700.0,
        load_ms=12.5,
        finish_reason="stop",
    )
    assert (r.input_tokens, r.output_tokens, r.cached_prompt_tokens) == (1400, 150, 0)
    assert (r.prefill_ms, r.decode_ms, r.load_ms, r.finish_reason) == (600.0, 2700.0, 12.5, "stop")


def test_new_fields_default_to_none() -> None:
    r = InferenceResult(content="{}", model="m")
    assert (r.cached_prompt_tokens, r.prefill_ms, r.decode_ms, r.load_ms, r.finish_reason) == (
        None,
        None,
        None,
        None,
        None,
    )


def test_ollama_only_fields_are_gone() -> None:
    names = {f.name for f in dataclasses.fields(InferenceResult)}
    assert {"eval_count", "eval_duration_ns"}.isdisjoint(names)


def test_finish_reason_values() -> None:
    assert set(get_args(FinishReason)) == {
        "stop",
        "length",
        "content_filter",
        "tool_use",
        "error",
        "other",
    }


def test_count_or_none_accepts_only_real_integers() -> None:
    assert count_or_none(12) == 12
    assert count_or_none(0) == 0
    assert count_or_none(None) is None
    assert count_or_none(True) is None
    assert count_or_none("12") is None
    assert count_or_none(1.5) is None


def _ollama_response(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "message": SimpleNamespace(content='{"signal": "buy"}'),
        "prompt_eval_count": 1400,
        "prompt_eval_duration": 600_000_000,
        "eval_count": 150,
        "eval_duration": 2_700_000_000,
        "load_duration": 12_500_000,
        "done_reason": "stop",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class _FakeOllamaClient:
    """Stand-in for OllamaClient.chat that records kwargs and returns a canned response."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def chat(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


async def _ollama_result(response: Any) -> InferenceResult:
    client: Any = _FakeOllamaClient(response)
    provider = OllamaProvider(ProviderRole.WORKER, "alphaswarm-worker", client)
    return await provider.chat([{"role": "user", "content": "ZZZT Holdings"}])


async def test_ollama_fills_tokens_timings_and_finish_reason() -> None:
    r = await _ollama_result(_ollama_response())
    assert (r.input_tokens, r.output_tokens, r.cached_prompt_tokens) == (1400, 150, None)
    assert (r.prefill_ms, r.decode_ms, r.load_ms) == (600.0, 2700.0, 12.5)
    assert r.finish_reason == "stop"


@pytest.mark.parametrize(
    ("done_reason", "expected"),
    [("stop", "stop"), ("length", "length"), ("load", "other"), ("unload", "other"), (None, None)],
)
async def test_ollama_done_reason_mapping(done_reason: str | None, expected: str | None) -> None:
    r = await _ollama_result(_ollama_response(done_reason=done_reason))
    assert r.finish_reason == expected


async def test_ollama_missing_fields_become_none() -> None:
    r = await _ollama_result(SimpleNamespace(message=SimpleNamespace(content="{}")))
    assert (r.input_tokens, r.output_tokens, r.prefill_ms, r.decode_ms, r.load_ms, r.finish_reason) == (
        None,
        None,
        None,
        None,
        None,
        None,
    )


def _openai_result_provider(body: dict[str, Any]) -> OpenAICompatProvider:
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, json=body))
    return OpenAICompatProvider(
        ProviderRole.WORKER,
        "gpt-test",
        base_url="https://api.example.com/v1",
        api_key="test-key",
        client=httpx.AsyncClient(transport=transport),
    )


async def test_openai_reports_cached_tokens_and_finish_reason() -> None:
    provider = _openai_result_provider(
        {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}],
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 400,
                "prompt_tokens_details": {"cached_tokens": 1024},
            },
        }
    )
    r = await provider.chat([{"role": "user", "content": "ZZZT"}])
    assert (r.input_tokens, r.output_tokens, r.cached_prompt_tokens, r.finish_reason) == (
        1500,
        400,
        1024,
        "length",
    )
    assert (r.prefill_ms, r.decode_ms, r.load_ms) == (None, None, None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "content_filter"),
        ("tool_calls", "tool_use"),
        ("function_call", "tool_use"),
        ("brand_new", "other"),
        (None, None),
    ],
)
async def test_openai_finish_reason_mapping(raw: str | None, expected: str | None) -> None:
    choice: dict[str, Any] = {"message": {"content": "{}"}}
    if raw is not None:
        choice["finish_reason"] = raw
    provider = _openai_result_provider({"choices": [choice], "usage": {"prompt_tokens": 1}})
    assert (await provider.chat([{"role": "user", "content": "x"}])).finish_reason == expected


async def test_openai_without_token_details_has_no_cached_tokens() -> None:
    provider = _openai_result_provider(
        {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 9, "completion_tokens": 1}}
    )
    assert (await provider.chat([{"role": "user", "content": "x"}])).cached_prompt_tokens is None


@dataclass
class _CacheUsage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


@dataclass
class _PlainUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _AnthropicResponse:
    content: list[Any]
    usage: Any
    stop_reason: str | None = "end_turn"


class _Messages:
    def __init__(self, response: _AnthropicResponse) -> None:
        self.response = response
        self.last_kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> _AnthropicResponse:
        self.last_kwargs = kwargs
        return self.response


@dataclass
class _AnthropicClient:
    response: _AnthropicResponse
    messages: _Messages = field(init=False)

    def __post_init__(self) -> None:
        self.messages = _Messages(self.response)


async def _anthropic_result(response: _AnthropicResponse) -> InferenceResult:
    client: Any = _AnthropicClient(response)
    provider = AnthropicProvider(ProviderRole.WORKER, "claude-test", api_key="test-key", client=client)
    return await provider.chat([{"role": "user", "content": "ZZZT"}])


async def test_anthropic_prompt_tokens_include_cache() -> None:
    usage = _CacheUsage(100, 20, cache_read_input_tokens=900, cache_creation_input_tokens=50)
    r = await _anthropic_result(_AnthropicResponse([_Text("ok")], usage, "end_turn"))
    assert (r.input_tokens, r.cached_prompt_tokens, r.output_tokens, r.finish_reason) == (
        1050,
        900,
        20,
        "stop",
    )


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
        ("tool_use", "tool_use"),
        ("refusal", "content_filter"),
        ("pause_turn", "other"),
        (None, None),
    ],
)
async def test_anthropic_stop_reason_mapping(stop_reason: str | None, expected: str | None) -> None:
    r = await _anthropic_result(_AnthropicResponse([_Text("ok")], _PlainUsage(5, 2), stop_reason))
    assert r.finish_reason == expected


async def test_anthropic_usage_without_cache_fields() -> None:
    r = await _anthropic_result(_AnthropicResponse([_Text("ok")], _PlainUsage(20, 8)))
    assert (r.input_tokens, r.cached_prompt_tokens, r.output_tokens) == (20, None, 8)
