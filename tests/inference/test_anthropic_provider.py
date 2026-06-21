"""Tests for AnthropicProvider — native Anthropic SDK adapter.

TDD: tests written BEFORE implementation.  Run to confirm RED, then GREEN
after the implementation lands.

No real network connections are made — all HTTP is handled by a fake client
injected via the ``client`` constructor parameter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from alphaswarm.errors import AuthError, InferenceError
from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.types import ProviderRole

# ---------------------------------------------------------------------------
# Fake SDK types — lightweight stubs; avoid importing real anthropic SDK
# ---------------------------------------------------------------------------


@dataclass
class _FakeTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeToolUseBlock:
    type: str = "tool_use"
    name: str = "emit_decision"
    input: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.input is None:
            self.input = {}


@dataclass
class _FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 5


@dataclass
class _FakeResponse:
    content: list[Any]
    usage: _FakeUsage = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = _FakeUsage()


class _FakeMessages:
    """Fake messages namespace; stores kwargs for inspection."""

    def __init__(self, response: _FakeResponse | Exception) -> None:
        self._response = response
        self.last_kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> _FakeResponse:
        self.last_kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeClient:
    """Fake AsyncAnthropic client."""

    def __init__(self, response: _FakeResponse | Exception) -> None:
        self.messages = _FakeMessages(response)
        self._closed = False

    async def close(self) -> None:
        self._closed = True


def _make_provider(
    response: _FakeResponse | Exception,
    *,
    model: str = "claude-3-5-sonnet-20241022",
    max_tokens_default: int = 1024,
    max_retries: int = 3,
) -> tuple[AnthropicProvider, _FakeClient]:
    fake_client = _FakeClient(response)
    provider = AnthropicProvider(
        ProviderRole.ORCHESTRATOR,
        model,
        api_key="test-key",
        max_tokens_default=max_tokens_default,
        max_retries=max_retries,
        client=fake_client,  # type: ignore[arg-type]
    )
    return provider, fake_client


_MSG = [{"role": "user", "content": "hello"}]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"signal": {"type": "string"}},
}

# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------


def test_is_local_returns_false() -> None:
    p, _ = _make_provider(_FakeResponse(content=[_FakeTextBlock(text="hi")]))
    assert p.is_local() is False


def test_role_attribute() -> None:
    p, _ = _make_provider(_FakeResponse(content=[_FakeTextBlock(text="hi")]))
    assert p.role is ProviderRole.ORCHESTRATOR


def test_model_attribute() -> None:
    p, _ = _make_provider(
        _FakeResponse(content=[_FakeTextBlock(text="hi")]),
        model="claude-opus-4-5",
    )
    assert p.model == "claude-opus-4-5"


@pytest.mark.asyncio
async def test_prepare_noop() -> None:
    p, _ = _make_provider(_FakeResponse(content=[_FakeTextBlock(text="hi")]))
    await p.prepare()  # must not raise


@pytest.mark.asyncio
async def test_teardown_noop() -> None:
    p, _ = _make_provider(_FakeResponse(content=[_FakeTextBlock(text="hi")]))
    await p.teardown()  # must not raise


@pytest.mark.asyncio
async def test_aclose_does_not_close_injected_client() -> None:
    """aclose() must NOT close an injected client — lifecycle stays with caller."""
    p, fake_client = _make_provider(_FakeResponse(content=[_FakeTextBlock(text="hi")]))
    await p.aclose()
    assert not fake_client._closed, "injected client must not be closed by aclose()"


# ---------------------------------------------------------------------------
# Happy path: schema path → tools + tool_choice; returns tool_use input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_path_sends_tools_and_tool_choice() -> None:
    """response_schema → tools=[emit_decision tool], tool_choice pinned to emit_decision."""
    tool_input = {"signal": "buy"}
    resp = _FakeResponse(
        content=[_FakeToolUseBlock(name="emit_decision", input=tool_input)],
        usage=_FakeUsage(input_tokens=20, output_tokens=8),
    )
    p, fake_client = _make_provider(resp)
    result = await p.chat(_MSG, response_schema=_SCHEMA)

    kwargs = fake_client.messages.last_kwargs
    assert "tools" in kwargs, "tools must be present for schema path"
    assert len(kwargs["tools"]) == 1
    assert kwargs["tools"][0]["name"] == "emit_decision"
    assert kwargs.get("tool_choice") == {"type": "tool", "name": "emit_decision"}
    assert result.content == json.dumps(tool_input)
    assert result.input_tokens == 20
    assert result.output_tokens == 8
    assert result.model == "claude-3-5-sonnet-20241022"


@pytest.mark.asyncio
async def test_schema_path_no_tools_in_plain_chat() -> None:
    """Plain chat (no schema, no json_mode) → tools must NOT appear in kwargs."""
    resp = _FakeResponse(
        content=[_FakeTextBlock(text="hello world")],
        usage=_FakeUsage(input_tokens=5, output_tokens=2),
    )
    p, fake_client = _make_provider(resp)
    result = await p.chat(_MSG)

    kwargs = fake_client.messages.last_kwargs
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    assert result.content == "hello world"
    assert result.input_tokens == 5
    assert result.output_tokens == 2


@pytest.mark.asyncio
async def test_plain_chat_multiple_text_blocks_concatenated() -> None:
    """Multiple text blocks → content is their texts joined."""
    resp = _FakeResponse(
        content=[
            _FakeTextBlock(text="Hello"),
            _FakeTextBlock(text=" World"),
        ],
    )
    p, _ = _make_provider(resp)
    result = await p.chat(_MSG)
    assert result.content == "Hello World"


# ---------------------------------------------------------------------------
# System message hoisting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_message_hoisted_to_system_kwarg() -> None:
    """System messages must be extracted from messages and passed as system=."""
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp)

    messages = [
        {"role": "system", "content": "You are a trading analyst."},
        {"role": "user", "content": "What is the signal?"},
    ]
    await p.chat(messages)

    kwargs = fake_client.messages.last_kwargs
    # system= kwarg must equal the system message content
    assert kwargs.get("system") == "You are a trading analyst."
    # messages list must NOT contain the system message
    for msg in kwargs.get("messages", []):
        assert msg.get("role") != "system", "system role must not appear in messages list"
    # user message must still be present
    assert any(m.get("role") == "user" for m in kwargs.get("messages", []))


@pytest.mark.asyncio
async def test_multiple_system_messages_joined_with_newline() -> None:
    """Multiple system messages → joined with newline as top-level system=."""
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp)

    messages = [
        {"role": "system", "content": "Rule 1."},
        {"role": "system", "content": "Rule 2."},
        {"role": "user", "content": "Go."},
    ]
    await p.chat(messages)

    kwargs = fake_client.messages.last_kwargs
    assert kwargs.get("system") == "Rule 1.\nRule 2."


@pytest.mark.asyncio
async def test_no_system_message_no_system_kwarg() -> None:
    """No system messages → system= must NOT appear in kwargs at all."""
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp)

    await p.chat([{"role": "user", "content": "hi"}])

    kwargs = fake_client.messages.last_kwargs
    assert "system" not in kwargs


# ---------------------------------------------------------------------------
# temperature / max_tokens conditional passing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temperature_passed_when_provided() -> None:
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp)
    await p.chat(_MSG, temperature=0.7)
    assert fake_client.messages.last_kwargs.get("temperature") == 0.7


@pytest.mark.asyncio
async def test_temperature_absent_when_not_provided() -> None:
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp)
    await p.chat(_MSG)
    assert "temperature" not in fake_client.messages.last_kwargs


@pytest.mark.asyncio
async def test_max_tokens_defaults_to_constructor_value() -> None:
    """When max_tokens not passed to chat(), use max_tokens_default from constructor."""
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp, max_tokens_default=512)
    await p.chat(_MSG)
    assert fake_client.messages.last_kwargs.get("max_tokens") == 512


@pytest.mark.asyncio
async def test_max_tokens_caller_overrides_default() -> None:
    """Explicit max_tokens in chat() overrides the constructor default."""
    resp = _FakeResponse(content=[_FakeTextBlock(text="ok")])
    p, fake_client = _make_provider(resp, max_tokens_default=512)
    await p.chat(_MSG, max_tokens=2048)
    assert fake_client.messages.last_kwargs.get("max_tokens") == 2048


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _make_httpx_response(status_code: int, headers: dict[str, str] | None = None) -> Any:
    """Build a real httpx.Response with request attached (required by Anthropic SDK)."""
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(
        status_code,
        headers=headers or {},
        content=b"{}",
        request=req,
    )


@pytest.mark.asyncio
async def test_auth_error_on_authentication_error() -> None:
    """anthropic.AuthenticationError → AuthError raised at public boundary."""
    import anthropic

    exc = anthropic.AuthenticationError(
        message="Invalid API key",
        response=_make_httpx_response(401),
        body=None,
    )
    p, _ = _make_provider(exc)
    with pytest.raises(AuthError) as exc_info:
        await p.chat(_MSG)
    assert exc_info.value.provider == "anthropic"


@pytest.mark.asyncio
async def test_auth_error_on_permission_denied() -> None:
    """anthropic.PermissionDeniedError → AuthError raised at public boundary."""
    import anthropic

    exc = anthropic.PermissionDeniedError(
        message="Permission denied",
        response=_make_httpx_response(403),
        body=None,
    )
    p, _ = _make_provider(exc)
    with pytest.raises(AuthError) as exc_info:
        await p.chat(_MSG)
    assert exc_info.value.provider == "anthropic"


@pytest.mark.asyncio
async def test_rate_limit_retries_then_raises_inference_error() -> None:
    """RateLimitError retried up to max_retries then raises InferenceError."""
    import anthropic

    call_count = 0

    # Build the exception once — reuse across calls
    _rate_exc = anthropic.RateLimitError(
        message="Too many requests",
        response=_make_httpx_response(429, {"retry-after": "0"}),
        body=None,
    )

    class _MultiRaiseMessages:
        last_kwargs: dict[str, Any] = {}

        async def create(self, **kwargs: Any) -> _FakeResponse:
            nonlocal call_count
            call_count += 1
            raise _rate_exc

    class _AlwaysRateLimitClient:
        messages = _MultiRaiseMessages()
        _closed = False

        async def close(self) -> None:
            self._closed = True

    provider = AnthropicProvider(
        ProviderRole.WORKER,
        "claude-3-5-sonnet-20241022",
        api_key="test-key",
        max_retries=2,
        client=_AlwaysRateLimitClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(InferenceError) as exc_info:
        await provider.chat(_MSG)

    assert exc_info.value.provider == "anthropic"
    assert call_count == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_api_connection_error_retries_then_raises_inference_error() -> None:
    """APIConnectionError → retried with backoff, then InferenceError."""
    import anthropic
    import httpx

    call_count = 0

    _conn_exc = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )

    class _ConnectionErrMessages:
        last_kwargs: dict[str, Any] = {}

        async def create(self, **kwargs: Any) -> _FakeResponse:
            nonlocal call_count
            call_count += 1
            raise _conn_exc

    class _ConnectionErrClient:
        messages = _ConnectionErrMessages()
        _closed = False

        async def close(self) -> None:
            self._closed = True

    provider = AnthropicProvider(
        ProviderRole.WORKER,
        "claude-3-5-sonnet-20241022",
        api_key="test-key",
        max_retries=1,
        client=_ConnectionErrClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(InferenceError) as exc_info:
        await provider.chat(_MSG)

    assert exc_info.value.provider == "anthropic"
    assert call_count == 2  # initial + 1 retry
