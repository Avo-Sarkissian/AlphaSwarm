"""Telemetry carried by InferenceResult and filled by every provider."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from alphaswarm.inference.ollama_provider import OllamaProvider
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
