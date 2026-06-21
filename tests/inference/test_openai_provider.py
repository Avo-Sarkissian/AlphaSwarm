"""Tests for OpenAICompatProvider — OpenAI-compatible cloud adapter.

TDD: tests written BEFORE implementation.  Run to confirm RED, then GREEN
after the implementation lands.

No real network connections are made — all HTTP is handled by
``httpx.MockTransport`` injected via the ``client`` constructor parameter.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from alphaswarm.errors import AuthError, InferenceError
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.types import ProviderRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER_KWARGS: dict[str, Any] = dict(
    base_url="https://api.example.com/v1",
    api_key="test-key",
)

_MSG = [{"role": "user", "content": "hello"}]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"signal": {"type": "string"}},
}

_DEFAULT_USAGE = {"prompt_tokens": 10, "completion_tokens": 5}


def _200(content: str, usage: dict[str, int] = _DEFAULT_USAGE) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": usage,
    }
    return httpx.Response(200, json=body)


def _error(status: int, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {})


def _make_provider(
    handler: Any,
    *,
    model: str = "gpt-4o",
    max_retries: int = 3,
    extra_headers: dict[str, str] | None = None,
) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return OpenAICompatProvider(
        ProviderRole.ORCHESTRATOR,
        model,
        **_PROVIDER_KWARGS,
        max_retries=max_retries,
        extra_headers=extra_headers,
        client=client,
    )


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------


def test_is_local_returns_false() -> None:
    p = _make_provider(lambda req: _200("hi"))
    assert p.is_local() is False


def test_role_attribute() -> None:
    p = _make_provider(lambda req: _200("hi"))
    assert p.role is ProviderRole.ORCHESTRATOR


def test_model_attribute() -> None:
    p = _make_provider(lambda req: _200("hi"), model="claude-3")
    assert p.model == "claude-3"


@pytest.mark.asyncio
async def test_prepare_noop() -> None:
    p = _make_provider(lambda req: _200("hi"))
    await p.prepare()  # must not raise


@pytest.mark.asyncio
async def test_teardown_noop() -> None:
    p = _make_provider(lambda req: _200("hi"))
    await p.teardown()  # must not raise


@pytest.mark.asyncio
async def test_aclose_does_not_raise_for_injected_client() -> None:
    """aclose() must not raise or close an injected client.

    Lifecycle ownership stays with the caller — the provider must leave the
    injected httpx.AsyncClient open after aclose().
    """
    injected_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: _200("hi")))
    p = OpenAICompatProvider(
        ProviderRole.ORCHESTRATOR,
        "gpt-4o",
        **_PROVIDER_KWARGS,
        client=injected_client,
    )
    await p.aclose()
    assert not injected_client.is_closed, "injected client must not be closed by aclose()"


# ---------------------------------------------------------------------------
# Happy path: response_schema → json_schema response_format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_request_body_has_json_schema() -> None:
    """response_schema → response_format.type == 'json_schema' in request body."""
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return _200('{"signal":"buy"}')

    p = _make_provider(handler)
    result = await p.chat(_MSG, response_schema=_SCHEMA)

    assert captured, "no request captured"
    body = captured[0]
    assert body["model"] == "gpt-4o"
    assert body["messages"] == _MSG
    rf = body.get("response_format", {})
    assert rf.get("type") == "json_schema"
    assert result.content == '{"signal":"buy"}'
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.eval_count is None
    assert result.eval_duration_ns is None


# ---------------------------------------------------------------------------
# Happy path: json_mode=True (no schema) → json_object
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_mode_body_has_json_object() -> None:
    """json_mode=True and no schema → response_format.type == 'json_object'."""
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return _200("{}")

    p = _make_provider(handler)
    await p.chat(_MSG, json_mode=True)

    body = captured[0]
    assert body.get("response_format", {}).get("type") == "json_object"


# ---------------------------------------------------------------------------
# Happy path: no schema, no json_mode → no response_format key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_schema_no_json_mode_no_response_format() -> None:
    """No schema and no json_mode → response_format must NOT appear in the body."""
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return _200("plain text")

    p = _make_provider(handler)
    await p.chat(_MSG)

    assert "response_format" not in captured[0]


# ---------------------------------------------------------------------------
# temperature / max_tokens included only when provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temperature_and_max_tokens_included_when_provided() -> None:
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return _200("ok")

    p = _make_provider(handler)
    await p.chat(_MSG, temperature=0.5, max_tokens=256)

    body = captured[0]
    assert body.get("temperature") == 0.5
    assert body.get("max_tokens") == 256


@pytest.mark.asyncio
async def test_temperature_and_max_tokens_absent_when_not_provided() -> None:
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return _200("ok")

    p = _make_provider(handler)
    await p.chat(_MSG)

    body = captured[0]
    assert "temperature" not in body
    assert "max_tokens" not in body


# ---------------------------------------------------------------------------
# Token usage parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_parsed_from_response() -> None:
    p = _make_provider(lambda req: _200("hi", {"prompt_tokens": 42, "completion_tokens": 7}))
    result = await p.chat(_MSG)
    assert result.input_tokens == 42
    assert result.output_tokens == 7


@pytest.mark.asyncio
async def test_null_content_becomes_empty_string() -> None:
    """choices[0].message.content = null → content == '' in InferenceResult."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": None}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    p = _make_provider(handler)
    result = await p.chat(_MSG)
    assert result.content == ""


# ---------------------------------------------------------------------------
# 401 → AuthError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_raises_auth_error() -> None:
    p = _make_provider(lambda req: _error(401, {"error": "Unauthorized"}))
    with pytest.raises(AuthError):
        await p.chat(_MSG)


@pytest.mark.asyncio
async def test_403_raises_auth_error() -> None:
    p = _make_provider(lambda req: _error(403, {"error": "Forbidden"}))
    with pytest.raises(AuthError):
        await p.chat(_MSG)


# ---------------------------------------------------------------------------
# strict-unsupported: 400 on json_schema → retry once with json_object
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_unsupported_400_retries_with_json_object() -> None:
    """First POST returns 400 mentioning json_schema; second returns 200.

    After this flow:
    - The 200 content is returned.
    - self._no_strict is True.
    - A subsequent schema call goes straight to json_object (no extra 400).
    """
    # Phase 1: absolute call counter across both chat() invocations
    absolute_call: list[int] = [0]
    request_bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        absolute_call[0] += 1
        body = json.loads(req.content)
        request_bodies.append(body)
        if absolute_call[0] == 1:
            # First ever call: respond with strict-unsupported 400
            return httpx.Response(
                400,
                json={"error": {"message": "response_format json_schema not supported"}},
            )
        # All subsequent calls succeed
        return _200('{"signal":"hold"}')

    p = _make_provider(handler)
    result = await p.chat(_MSG, response_schema=_SCHEMA)

    assert result.content == '{"signal":"hold"}'
    assert absolute_call[0] == 2
    # Second call (downgrade retry) must use json_object fallback
    assert request_bodies[1].get("response_format", {}).get("type") == "json_object"
    # _no_strict must be set
    assert p._no_strict is True

    # Subsequent schema call: goes straight to json_object without a 400
    bodies_before = len(request_bodies)
    result2 = await p.chat(_MSG, response_schema=_SCHEMA)
    assert absolute_call[0] == 3  # only one new request
    assert request_bodies[2].get("response_format", {}).get("type") == "json_object"
    assert result2.content == '{"signal":"hold"}'
    _ = bodies_before  # suppress unused variable warning


@pytest.mark.asyncio
async def test_400_not_schema_related_raises_inference_error() -> None:
    """400 that doesn't mention json_schema/response_format must raise InferenceError directly."""
    p = _make_provider(
        lambda req: httpx.Response(400, json={"error": {"message": "bad request other reason"}}),
    )
    with pytest.raises(InferenceError):
        await p.chat(_MSG, response_schema=_SCHEMA)


@pytest.mark.asyncio
async def test_strict_downgrade_inner_retry_transport_error_raises_inference_error() -> None:
    """Strict-downgrade inner retry hitting a transport error → InferenceError (not raw httpx).

    Scenario:
      - First POST returns 400 indicating json_schema/response_format unsupported.
      - Second POST (json_object fallback) raises httpx.ConnectError (a TransportError).
    Expected: InferenceError is raised — not a bare httpx exception, not an infinite loop.
    """
    call_count: list[int] = [0]

    def handler(req: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        if call_count[0] == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "response_format json_schema not supported"}},
            )
        # Second call — raise a transport-level error instead of returning a response
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    p = OpenAICompatProvider(
        ProviderRole.ORCHESTRATOR,
        "gpt-4o",
        **_PROVIDER_KWARGS,
        max_retries=3,
        client=client,
    )

    with pytest.raises(InferenceError):
        await p.chat(_MSG, response_schema=_SCHEMA)

    # Exactly 2 calls: the 400 and the transport-error retry
    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# response_format precedence: response_schema + json_mode=True → json_schema wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_schema_wins_over_json_mode_when_strict_enabled() -> None:
    """When both response_schema and json_mode=True are passed (and _no_strict=False),
    the strict json_schema response_format takes precedence — json_mode is ignored.
    """
    captured: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(json.loads(req.content))
        return _200('{"signal":"sell"}')

    p = _make_provider(handler)
    # Both flags set; _no_strict is False by default
    await p.chat(_MSG, response_schema=_SCHEMA, json_mode=True)

    assert captured, "no request captured"
    rf = captured[0].get("response_format", {})
    assert rf.get("type") == "json_schema", (
        f"expected json_schema (strict wins), got {rf.get('type')!r}"
    )


# ---------------------------------------------------------------------------
# 429 → Retry-After honor, then InferenceError after max_retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_with_retry_after_0_then_200_succeeds() -> None:
    """429 with Retry-After: 0 then 200 → succeeds after one retry."""
    call_count = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return _200("retry worked")

    p = _make_provider(handler, max_retries=3)
    result = await p.chat(_MSG)
    assert result.content == "retry worked"
    assert call_count == 2


@pytest.mark.asyncio
async def test_persistent_429_raises_inference_error() -> None:
    """Persistent 429 after max_retries → InferenceError."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    p = _make_provider(handler, max_retries=2)
    with pytest.raises(InferenceError):
        await p.chat(_MSG)


# ---------------------------------------------------------------------------
# 5xx → InferenceError after retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_500_raises_inference_error_after_retries() -> None:
    p = _make_provider(lambda req: _error(500), max_retries=1)
    with pytest.raises(InferenceError):
        await p.chat(_MSG)


# ---------------------------------------------------------------------------
# Extra headers forwarded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_headers_forwarded() -> None:
    captured_headers: list[httpx.Headers] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured_headers.append(req.headers)
        return _200("ok")

    p = _make_provider(handler, extra_headers={"X-Custom": "value123"})
    await p.chat(_MSG)

    assert captured_headers[0].get("x-custom") == "value123"
    assert "Bearer test-key" in captured_headers[0].get("authorization", "")
