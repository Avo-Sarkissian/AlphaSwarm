"""Telemetry carried by InferenceResult and filled by every provider."""

from __future__ import annotations

import dataclasses
from typing import get_args

from alphaswarm.inference.types import FinishReason, InferenceResult, count_or_none


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
