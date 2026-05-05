"""Unit tests for OllamaClient wrapper (INFRA-04).

Tests verify:
- Chat delegation to AsyncClient
- num_ctx stripping from options
- Exponential backoff on transient errors (ResponseError, ConnectionError)
- OllamaInferenceError wrapping after max retries
- RequestError wrapped in OllamaInferenceError (not retried)
- format parameter pass-through
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import ollama
import pytest

from alphaswarm.errors import OllamaInferenceError


@pytest.fixture()
def mock_chat_response() -> MagicMock:
    """Create a mock ChatResponse with .message.content."""
    response = MagicMock()
    response.message.content = '{"signal": "buy", "confidence": 0.8}'
    return response


@pytest.fixture()
def mock_async_client(mock_chat_response: MagicMock) -> AsyncMock:
    """Create a mocked ollama.AsyncClient."""
    client = AsyncMock(spec=ollama.AsyncClient)
    client.chat = AsyncMock(return_value=mock_chat_response)
    client.generate = AsyncMock(return_value=mock_chat_response)
    return client


@pytest.fixture()
def ollama_client(mock_async_client: AsyncMock) -> Any:
    """Create an OllamaClient with mocked internal client."""
    from alphaswarm.ollama_client import OllamaClient

    client = OllamaClient(base_url="http://localhost:11434")
    client._client = mock_async_client
    return client


async def test_chat_returns_response(
    ollama_client: Any, mock_async_client: AsyncMock
) -> None:
    """OllamaClient.chat() delegates to mocked AsyncClient.chat() and returns ChatResponse."""
    result = await ollama_client.chat(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
    )
    mock_async_client.chat.assert_called()
    assert result.message.content == '{"signal": "buy", "confidence": 0.8}'


async def test_no_num_ctx(ollama_client: Any, mock_async_client: AsyncMock) -> None:
    """OllamaClient.chat() strips num_ctx from options dict, keeps other keys."""
    await ollama_client.chat(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
        options={"num_ctx": 4096, "temperature": 0.5},
    )
    call_kwargs = mock_async_client.chat.call_args
    # Options passed to the underlying client should NOT contain num_ctx
    passed_options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
    assert "num_ctx" not in (passed_options or {})
    assert passed_options is not None
    assert passed_options.get("temperature") == 0.5


async def test_backoff_retry(
    ollama_client: Any, mock_async_client: AsyncMock, mock_chat_response: MagicMock
) -> None:
    """When mocked client raises ResponseError on first call then succeeds, returns success."""
    mock_async_client.chat = AsyncMock(
        side_effect=[ollama.ResponseError("server error"), mock_chat_response]
    )
    result = await ollama_client.chat(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert mock_async_client.chat.call_count == 2
    assert result.message.content == '{"signal": "buy", "confidence": 0.8}'


async def test_max_retries_error(
    ollama_client: Any, mock_async_client: AsyncMock
) -> None:
    """When mocked client raises ResponseError 3 times, raises OllamaInferenceError."""
    mock_async_client.chat = AsyncMock(
        side_effect=ollama.ResponseError("server error")
    )
    with pytest.raises(OllamaInferenceError) as exc_info:
        await ollama_client.chat(
            model="qwen3.5:7b",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert exc_info.value.model == "qwen3.5:7b"
    assert isinstance(exc_info.value.original_error, ollama.ResponseError)


async def test_no_retry_on_request_error(
    ollama_client: Any, mock_async_client: AsyncMock
) -> None:
    """RequestError is wrapped in OllamaInferenceError immediately (no retries)."""
    mock_async_client.chat = AsyncMock(
        side_effect=ollama.RequestError("bad request")
    )
    with pytest.raises(OllamaInferenceError):
        await ollama_client.chat(
            model="test",
            messages=[{"role": "user", "content": "hi"}],
        )
    # RequestError is not retried - called only once
    assert mock_async_client.chat.call_count == 1


async def test_format_json_passed(
    ollama_client: Any, mock_async_client: AsyncMock
) -> None:
    """OllamaClient.chat() passes format='json' to underlying client."""
    await ollama_client.chat(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
        format="json",
    )
    call_kwargs = mock_async_client.chat.call_args
    passed_format = call_kwargs.kwargs.get("format") or call_kwargs[1].get("format")
    assert passed_format == "json"


# ---------------------------------------------------------------------------
# Phase 41.2-03: D-03 — generate() must accept and forward `system` kwarg
# ---------------------------------------------------------------------------


async def test_generate_forwards_system_kwarg(
    ollama_client: Any, mock_async_client: AsyncMock
) -> None:
    """OllamaClient.generate() must forward `system=...` to the underlying client.

    Regression for D-03: simulation.py:1316 calls
    `client.generate(model=..., prompt=..., system=...)` but the wrapper signature
    omits `system`, so every call raises TypeError and is swallowed by the bare
    `except Exception` in `_generate_decision_narratives` — producing zero
    narratives. Symmetric with `chat()` which already supports system messages.
    """
    await ollama_client.generate(
        model="m",
        prompt="p",
        system="you are X",
    )
    assert mock_async_client.generate.call_args is not None
    kwargs = mock_async_client.generate.call_args.kwargs
    assert kwargs.get("system") == "you are X", (
        f"system kwarg not forwarded to underlying client: {kwargs}"
    )
