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

from alphaswarm.errors import AuthError, InferenceError, ProviderConfigError
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.retry import RetryPolicy
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


async def _no_sleep(seconds: float) -> None:
    return None


# Retries in unit tests never sleep for real.
NO_WAIT = RetryPolicy(sleep=_no_sleep)


def _make_provider(
    handler: Any,
    *,
    model: str = "gpt-4o",
    max_retries: int = 3,
    extra_headers: dict[str, str] | None = None,
    retry_policy: RetryPolicy = NO_WAIT,
) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return OpenAICompatProvider(
        ProviderRole.ORCHESTRATOR,
        model,
        **_PROVIDER_KWARGS,
        max_retries=max_retries,
        extra_headers=extra_headers,
        retry_policy=retry_policy,
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


async def test_teardown_noop() -> None:
    p = _make_provider(lambda req: _200("hi"))
    await p.teardown()  # must not raise


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


# ---------------------------------------------------------------------------
# Happy path: json_mode=True (no schema) → json_object
# ---------------------------------------------------------------------------


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


async def test_token_usage_parsed_from_response() -> None:
    p = _make_provider(lambda req: _200("hi", {"prompt_tokens": 42, "completion_tokens": 7}))
    result = await p.chat(_MSG)
    assert result.input_tokens == 42
    assert result.output_tokens == 7


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


async def test_401_raises_auth_error() -> None:
    p = _make_provider(lambda req: _error(401, {"error": "Unauthorized"}))
    with pytest.raises(AuthError):
        await p.chat(_MSG)


async def test_403_raises_auth_error() -> None:
    p = _make_provider(lambda req: _error(403, {"error": "Forbidden"}))
    with pytest.raises(AuthError):
        await p.chat(_MSG)


# ---------------------------------------------------------------------------
# strict-unsupported: 400 on json_schema → retry once with json_object
# ---------------------------------------------------------------------------


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


async def test_400_not_schema_related_raises_inference_error() -> None:
    """400 that doesn't mention json_schema/response_format must raise InferenceError directly."""
    p = _make_provider(
        lambda req: httpx.Response(400, json={"error": {"message": "bad request other reason"}}),
    )
    with pytest.raises(InferenceError):
        await p.chat(_MSG, response_schema=_SCHEMA)


async def test_strict_downgrade_inner_retry_transport_error_raises_inference_error() -> None:
    """A transport error after the strict downgrade is retried like any other.

    Call 1: 400 naming json_schema -> downgrade (outside the retry budget).
    Calls 2-5: ConnectError, retried max_retries=3 times, then InferenceError.
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
        retry_policy=NO_WAIT,
        client=client,
    )

    with pytest.raises(InferenceError):
        await p.chat(_MSG, response_schema=_SCHEMA)

    # The downgrade plus 1 + 3 transport attempts (docs/DECISIONS.md#adr-cloud-retry).
    assert call_count[0] == 5


# ---------------------------------------------------------------------------
# response_format precedence: response_schema + json_mode=True → json_schema wins
# ---------------------------------------------------------------------------


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
    assert rf.get("type") == "json_schema", f"expected json_schema (strict wins), got {rf.get('type')!r}"


# ---------------------------------------------------------------------------
# 429 → Retry-After honor, then InferenceError after max_retries
# ---------------------------------------------------------------------------


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


async def test_500_raises_inference_error_after_retries(instant_sleep: list[float]) -> None:
    p = _make_provider(lambda req: _error(500), max_retries=1, retry_policy=RetryPolicy(rng=lambda: 1.0))
    with pytest.raises(InferenceError):
        await p.chat(_MSG)
    assert instant_sleep == [1.0]  # full-jitter ceiling for the first retry is 1 s


# ---------------------------------------------------------------------------
# Extra headers forwarded
# ---------------------------------------------------------------------------


async def test_extra_headers_forwarded() -> None:
    captured_headers: list[httpx.Headers] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured_headers.append(req.headers)
        return _200("ok")

    p = _make_provider(handler, extra_headers={"X-Custom": "value123"})
    await p.chat(_MSG)

    assert captured_headers[0].get("x-custom") == "value123"
    assert "Bearer test-key" in captured_headers[0].get("authorization", "")


# ---------------------------------------------------------------------------
# Retry classification (docs/DECISIONS.md#adr-cloud-retry)
# ---------------------------------------------------------------------------

_NOT_FOUND = httpx.Response(
    404,
    json={
        "error": {
            "message": "The model `typo-model` does not exist or you do not have access to it.",
            "code": "model_not_found",
        }
    },
)


def _replay(items: list[httpx.Response | Exception]) -> tuple[Any, list[httpx.Request]]:
    """Handler that answers with ``items`` in order (the last one repeats)."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        item = items[min(len(seen), len(items)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def _recording(slept: list[float]) -> RetryPolicy:
    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    return RetryPolicy(sleep=_sleep, rng=lambda: 1.0)


async def test_404_is_a_provider_config_error_and_not_retried() -> None:
    """A wrong model id fails on the first call, with the server's reason."""
    handler, seen = _replay([_NOT_FOUND])
    p = _make_provider(handler, model="typo-model", max_retries=8)
    with pytest.raises(ProviderConfigError) as exc_info:
        await p.chat(_MSG)
    assert len(seen) == 1
    assert exc_info.value.status_code == 404
    assert "does not exist" in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 422])
async def test_non_schema_400_and_422_are_config_errors(status: int) -> None:
    body = {"error": {"message": "Unrecognized request argument supplied: foo"}}
    handler, seen = _replay([httpx.Response(status, json=body)])
    p = _make_provider(handler, max_retries=8)
    with pytest.raises(ProviderConfigError):
        await p.chat(_MSG)
    assert len(seen) == 1


async def test_context_length_400_is_a_per_call_error() -> None:
    """An oversized prompt is one failed call (InferenceError), not a stopped run."""
    body = {
        "error": {
            "code": "context_length_exceeded",
            "message": "This model's maximum context length is 128000 tokens.",
        }
    }
    handler, seen = _replay([httpx.Response(400, json=body)])
    p = _make_provider(handler, max_retries=8)
    with pytest.raises(InferenceError) as exc_info:
        await p.chat(_MSG)
    assert not isinstance(exc_info.value, ProviderConfigError)
    assert len(seen) == 1


async def test_timeouts_are_not_retried() -> None:
    handler, seen = _replay([httpx.ReadTimeout("read timed out")])
    p = _make_provider(handler, max_retries=8)
    with pytest.raises(InferenceError, match="timed out"):
        await p.chat(_MSG)
    assert len(seen) == 1


async def test_connection_errors_retry_with_capped_jittered_backoff() -> None:
    slept: list[float] = []
    handler, seen = _replay([httpx.ConnectError("refused"), httpx.ConnectError("refused"), _200("ok")])
    p = _make_provider(handler, retry_policy=_recording(slept))
    assert (await p.chat(_MSG)).content == "ok"
    assert len(seen) == 3
    assert slept == [1.0, 2.0]


async def test_backoff_stays_capped_at_eight_retries() -> None:
    """The old loop slept 2**attempt: 255 s in total at the NIM setting max_retries=8."""
    slept: list[float] = []
    handler, seen = _replay([_error(503)])
    p = _make_provider(handler, max_retries=8, retry_policy=_recording(slept))
    with pytest.raises(InferenceError):
        await p.chat(_MSG)
    assert len(seen) == 9
    assert slept == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 529])
async def test_transient_statuses_are_retried(status: int) -> None:
    handler, seen = _replay([_error(status), _200("ok")])
    p = _make_provider(handler)
    assert (await p.chat(_MSG)).content == "ok"
    assert len(seen) == 2


async def test_retry_after_is_honoured_on_503() -> None:
    slept: list[float] = []
    handler, _ = _replay([httpx.Response(503, headers={"Retry-After": "7"}, json={}), _200("ok")])
    p = _make_provider(handler, retry_policy=_recording(slept))
    await p.chat(_MSG)
    assert slept == [7.0]


async def test_malformed_200_body_is_an_inference_error() -> None:
    handler, _ = _replay([httpx.Response(200, content=b"<html>gateway hiccup</html>")])
    p = _make_provider(handler)
    with pytest.raises(InferenceError, match="Malformed response body"):
        await p.chat(_MSG)


async def test_malformed_choice_keeps_the_billed_tokens() -> None:
    body = {
        "choices": [{"finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 40},
    }
    handler, _ = _replay([httpx.Response(200, json=body)])
    p = _make_provider(handler)
    with pytest.raises(InferenceError) as exc_info:
        await p.chat(_MSG)
    assert (exc_info.value.input_tokens, exc_info.value.output_tokens) == (1200, 40)


# ---------------------------------------------------------------------------
# Preflight (docs/DECISIONS.md#adr-cloud-retry)
# ---------------------------------------------------------------------------

_LISTING = httpx.Response(200, json={"object": "list", "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})


def _routed(models: httpx.Response | Exception, completion: httpx.Response) -> tuple[Any, list[httpx.Request]]:
    """GET /models answers with ``models``; every POST answers with ``completion``."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "GET" and req.url.path.endswith("/models"):
            if isinstance(models, Exception):
                raise models
            return models
        return completion

    return handler, seen


async def test_prepare_runs_the_preflight_once() -> None:
    handler, seen = _routed(_LISTING, _200("pong"))
    p = _make_provider(handler, model="gpt-4o")
    await p.prepare()
    await p.prepare()
    assert [r.method for r in seen] == ["GET"]
    assert seen[0].url.path == "/v1/models"


async def test_prefixed_listing_counts_as_a_match() -> None:
    """Google's OpenAI-compatible endpoint lists `models/gemini-2.5-flash`."""
    listing = httpx.Response(200, json={"data": [{"id": "models/gemini-2.5-flash"}]})
    handler, seen = _routed(listing, _error(500))
    await _make_provider(handler, model="gemini-2.5-flash").prepare()
    assert [r.method for r in seen] == ["GET"]


async def test_bare_list_listing_is_understood() -> None:
    listing = httpx.Response(200, json=[{"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo"}])
    handler, seen = _routed(listing, _error(500))
    await _make_provider(handler, model="meta-llama/Llama-3.3-70B-Instruct-Turbo").prepare()
    assert [r.method for r in seen] == ["GET"]


async def test_missing_from_listing_falls_back_to_a_completion() -> None:
    """A listing miss is never a verdict; the 1-token completion is."""
    handler, seen = _routed(_LISTING, _200("p"))
    await _make_provider(handler, model="meta/llama-3.1-8b-instruct").prepare()
    assert [r.method for r in seen] == ["GET", "POST"]
    body = json.loads(seen[1].content)
    assert (body["model"], body["max_tokens"]) == ("meta/llama-3.1-8b-instruct", 1)


async def test_models_endpoint_404_falls_back_to_a_completion() -> None:
    """Some gateways do not implement /models at all."""
    handler, seen = _routed(_error(404), _200("p"))
    await _make_provider(handler, model="gpt-4o").prepare()
    assert [r.method for r in seen] == ["GET", "POST"]


async def test_unknown_model_fails_the_preflight() -> None:
    handler, _ = _routed(_LISTING, _NOT_FOUND)
    with pytest.raises(ProviderConfigError):
        await _make_provider(handler, model="typo-model").prepare()


async def test_bad_key_fails_the_preflight_with_auth_error() -> None:
    handler, _ = _routed(_error(401), _error(401))
    with pytest.raises(AuthError):
        await _make_provider(handler).prepare()


async def test_transient_preflight_failure_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    import structlog
    from structlog.testing import capture_logs

    import alphaswarm.inference.openai_provider as openai_module

    monkeypatch.setattr(openai_module, "log", structlog.get_logger(component="inference.openai"))
    handler, seen = _routed(httpx.ConnectError("refused"), _error(503))
    p = _make_provider(handler, model="gpt-4o")
    with capture_logs() as logs:
        await p.prepare()
    assert [e["event"] for e in logs if e["event"] == "cloud_preflight_inconclusive"] == [
        "cloud_preflight_inconclusive"
    ]
    assert len(seen) == 1 + 1 + 2  # listing, completion, two preflight retries


# ---------------------------------------------------------------------------
# seed in the request body (docs/DECISIONS.md#adr-run-manifest)
# ---------------------------------------------------------------------------


async def test_seed_is_sent_in_the_body() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _200('{"signal": "buy"}')

    await _make_provider(handler).chat(_MSG, seed=77)

    assert bodies[0]["seed"] == 77


async def test_no_seed_key_without_a_seed() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _200('{"signal": "buy"}')

    await _make_provider(handler).chat(_MSG)

    assert "seed" not in bodies[0]
