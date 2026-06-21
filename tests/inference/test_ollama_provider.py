"""Tests for OllamaProvider — pass-through adapter over OllamaClient.

TDD: these tests are written BEFORE the implementation.  They must be run
to confirm RED (import failure / assertion failures), then GREEN after the
implementation is in place.

Sockets are not required — all Ollama I/O is replaced by in-process fakes.
"""

from __future__ import annotations

from typing import Any

import pytest

from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.types import ProviderRole


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeOllama:
    """Records the kwargs passed to chat() and returns a canned response."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    async def chat(self, **kw: Any) -> Any:
        self.kwargs = kw

        class _Msg:
            content = '{"signal":"buy"}'

        class _Resp:
            message = _Msg()
            eval_count = 12
            eval_duration = 1_000_000

        return _Resp()


class _NoopManager:
    """No-op stand-in for OllamaModelManager — records load/unload calls."""

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.unloaded: list[str] = []

    async def load_model(self, model: str) -> None:
        self.loaded.append(model)

    async def unload_model(self, model: str) -> None:
        self.unloaded.append(model)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_provider(
    fake_client: _FakeOllama | None = None,
    manager: _NoopManager | None = None,
    model: str = "alphaswarm-worker",
    keep_alive: str = "5m",
) -> tuple[OllamaProvider, _FakeOllama, _NoopManager]:
    fc = fake_client or _FakeOllama()
    mgr = manager or _NoopManager()
    p = OllamaProvider(
        ProviderRole.WORKER,
        model,
        fc,  # type: ignore[arg-type]  # fake satisfies duck-type
        mgr,  # type: ignore[arg-type]
        keep_alive=keep_alive,
    )
    return p, fc, mgr


# ---------------------------------------------------------------------------
# Attribute / protocol surface tests
# ---------------------------------------------------------------------------


def test_is_local_returns_true() -> None:
    p, _, _ = _make_provider()
    assert p.is_local() is True


def test_role_attribute() -> None:
    p, _, _ = _make_provider()
    assert p.role is ProviderRole.WORKER


def test_model_attribute() -> None:
    p, _, _ = _make_provider(model="my-model")
    assert p.model == "my-model"


# ---------------------------------------------------------------------------
# format mapping: response_schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_provider_maps_schema_to_format() -> None:
    """response_schema is forwarded to OllamaClient as format=<schema>."""
    p, fc, _ = _make_provider()
    out = await p.chat(
        [{"role": "user", "content": "x"}],
        response_schema={"a": 1},
        temperature=0.4,
    )
    assert fc.kwargs is not None
    assert fc.kwargs["format"] == {"a": 1}
    assert fc.kwargs["think"] is False
    assert fc.kwargs["options"]["temperature"] == 0.4
    assert out.eval_count == 12
    assert out.input_tokens is None


# ---------------------------------------------------------------------------
# format mapping: json_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_mode_maps_to_format_json() -> None:
    """json_mode=True with no schema → format="json"."""
    p, fc, _ = _make_provider()
    await p.chat([{"role": "user", "content": "x"}], json_mode=True)
    assert fc.kwargs is not None
    assert fc.kwargs["format"] == "json"


# ---------------------------------------------------------------------------
# format mapping: no schema, no json_mode → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_schema_no_json_mode_format_is_none() -> None:
    """No schema and no json_mode → format=None."""
    p, fc, _ = _make_provider()
    await p.chat([{"role": "user", "content": "x"}])
    assert fc.kwargs is not None
    assert fc.kwargs["format"] is None


# ---------------------------------------------------------------------------
# schema takes precedence over json_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_takes_precedence_over_json_mode() -> None:
    """response_schema wins even when json_mode=True."""
    schema = {"type": "object", "properties": {"signal": {"type": "string"}}}
    p, fc, _ = _make_provider()
    await p.chat(
        [{"role": "user", "content": "x"}],
        response_schema=schema,
        json_mode=True,
    )
    assert fc.kwargs is not None
    assert fc.kwargs["format"] == schema


# ---------------------------------------------------------------------------
# think is always False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_think_is_always_false() -> None:
    p, fc, _ = _make_provider()
    await p.chat([{"role": "user", "content": "x"}])
    assert fc.kwargs is not None
    assert fc.kwargs["think"] is False


# ---------------------------------------------------------------------------
# keep_alive forwarded correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keep_alive_forwarded() -> None:
    p, fc, _ = _make_provider(keep_alive="10m")
    await p.chat([{"role": "user", "content": "x"}])
    assert fc.kwargs is not None
    assert fc.kwargs["keep_alive"] == "10m"


# ---------------------------------------------------------------------------
# temperature → options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temperature_in_options() -> None:
    p, fc, _ = _make_provider()
    await p.chat([{"role": "user", "content": "x"}], temperature=0.7)
    assert fc.kwargs is not None
    assert fc.kwargs["options"] == {"temperature": 0.7}


@pytest.mark.asyncio
async def test_no_temperature_options_is_none() -> None:
    """When temperature is None, options must be None (not an empty dict)."""
    p, fc, _ = _make_provider()
    await p.chat([{"role": "user", "content": "x"}])
    assert fc.kwargs is not None
    assert fc.kwargs["options"] is None


# ---------------------------------------------------------------------------
# max_tokens is accepted but ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_tokens_accepted_but_ignored() -> None:
    """max_tokens kwarg must be accepted without error; it does not flow to Ollama."""
    p, fc, _ = _make_provider()
    await p.chat([{"role": "user", "content": "x"}], max_tokens=512)
    assert fc.kwargs is not None
    # num_predict should NOT appear in options
    assert fc.kwargs.get("options") is None or "num_predict" not in (
        fc.kwargs.get("options") or {}
    )


# ---------------------------------------------------------------------------
# InferenceResult token fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eval_count_and_duration_forwarded() -> None:
    p, _, _ = _make_provider()
    out = await p.chat([{"role": "user", "content": "x"}])
    assert out.eval_count == 12
    assert out.eval_duration_ns == 1_000_000


@pytest.mark.asyncio
async def test_input_output_tokens_are_none() -> None:
    """Local inference is free; input_tokens/output_tokens stay None."""
    p, _, _ = _make_provider()
    out = await p.chat([{"role": "user", "content": "x"}])
    assert out.input_tokens is None
    assert out.output_tokens is None


@pytest.mark.asyncio
async def test_content_forwarded() -> None:
    p, _, _ = _make_provider()
    out = await p.chat([{"role": "user", "content": "x"}])
    assert out.content == '{"signal":"buy"}'


@pytest.mark.asyncio
async def test_model_in_result() -> None:
    p, _, _ = _make_provider(model="alphaswarm-worker")
    out = await p.chat([{"role": "user", "content": "x"}])
    assert out.model == "alphaswarm-worker"


# ---------------------------------------------------------------------------
# None content fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_content_becomes_empty_string() -> None:
    """OllamaClient may return None for content; provider must coerce to ''."""

    class _NoneContentOllama:
        kwargs: dict[str, Any] | None = None

        async def chat(self, **kw: Any) -> Any:
            self.kwargs = kw

            class _Msg:
                content = None

            class _Resp:
                message = _Msg()
                eval_count = 0
                eval_duration = 0

            return _Resp()

    fc = _NoneContentOllama()
    p = OllamaProvider(ProviderRole.WORKER, "m", fc, _NoopManager())  # type: ignore[arg-type]
    out = await p.chat([{"role": "user", "content": "x"}])
    assert out.content == ""


# ---------------------------------------------------------------------------
# prepare / teardown delegate to model manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_calls_load_model() -> None:
    p, _, mgr = _make_provider(model="alphaswarm-worker")
    await p.prepare()
    assert mgr.loaded == ["alphaswarm-worker"]
    assert mgr.unloaded == []


@pytest.mark.asyncio
async def test_teardown_calls_unload_model() -> None:
    p, _, mgr = _make_provider(model="alphaswarm-worker")
    await p.teardown()
    assert mgr.unloaded == ["alphaswarm-worker"]
    assert mgr.loaded == []


@pytest.mark.asyncio
async def test_aclose_is_noop() -> None:
    """aclose() must not raise and must not touch the model manager."""
    p, _, mgr = _make_provider()
    await p.aclose()
    assert mgr.loaded == []
    assert mgr.unloaded == []


# ---------------------------------------------------------------------------
# model kwarg forwarded to OllamaClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_kwarg_forwarded_to_client() -> None:
    p, fc, _ = _make_provider(model="alphaswarm-worker")
    await p.chat([{"role": "user", "content": "x"}])
    assert fc.kwargs is not None
    assert fc.kwargs["model"] == "alphaswarm-worker"
