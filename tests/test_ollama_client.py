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
from unittest.mock import AsyncMock, MagicMock

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
    return client


@pytest.fixture()
def ollama_client(mock_async_client: AsyncMock) -> Any:
    """Create an OllamaClient with mocked internal client."""
    from alphaswarm.ollama_client import OllamaClient

    client = OllamaClient(base_url="http://localhost:11434")
    client._client = mock_async_client
    return client


async def test_chat_returns_response(ollama_client: Any, mock_async_client: AsyncMock) -> None:
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
    ollama_client: Any,
    mock_async_client: AsyncMock,
    mock_chat_response: MagicMock,
    instant_sleep: list[float],
) -> None:
    """When mocked client raises ResponseError on first call then succeeds, returns success."""
    mock_async_client.chat = AsyncMock(side_effect=[ollama.ResponseError("server error"), mock_chat_response])
    result = await ollama_client.chat(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert mock_async_client.chat.call_count == 2
    assert len(instant_sleep) == 1  # one backoff wait between the two tries
    assert result.message.content == '{"signal": "buy", "confidence": 0.8}'


async def test_max_retries_error(ollama_client: Any, mock_async_client: AsyncMock, instant_sleep: list[float]) -> None:
    """When mocked client raises ResponseError 3 times, raises OllamaInferenceError."""
    mock_async_client.chat = AsyncMock(side_effect=ollama.ResponseError("server error"))
    with pytest.raises(OllamaInferenceError) as exc_info:
        await ollama_client.chat(
            model="qwen3.5:7b",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert exc_info.value.model == "qwen3.5:7b"
    assert isinstance(exc_info.value.original_error, ollama.ResponseError)
    assert mock_async_client.chat.call_count == 3  # backoff max_tries=3
    assert len(instant_sleep) == 2


async def test_no_retry_on_request_error(ollama_client: Any, mock_async_client: AsyncMock) -> None:
    """RequestError is wrapped in OllamaInferenceError immediately (no retries)."""
    mock_async_client.chat = AsyncMock(side_effect=ollama.RequestError("bad request"))
    with pytest.raises(OllamaInferenceError):
        await ollama_client.chat(
            model="test",
            messages=[{"role": "user", "content": "hi"}],
        )
    # RequestError is not retried - called only once
    assert mock_async_client.chat.call_count == 1


async def test_format_json_passed(ollama_client: Any, mock_async_client: AsyncMock) -> None:
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
# The connection stays on the configured host (docs/DECISIONS.md#adr-advisory-pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("proxy_var", ["HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"])
def test_the_http_client_ignores_proxy_env(monkeypatch: pytest.MonkeyPatch, proxy_var: str) -> None:
    """A proxy set in the environment (or macOS system settings) must not receive
    requests meant for the local Ollama server: httpx gives localhost no bypass."""
    import httpx

    from alphaswarm.ollama_client import OllamaClient

    monkeypatch.setenv(proxy_var, "http://proxy.example:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    http = OllamaClient(base_url="http://localhost:11434").raw_client._client

    assert http.trust_env is False
    transport = http._transport_for_url(httpx.URL("http://localhost:11434/api/chat"))
    assert transport is http._transport


def test_the_http_client_does_not_follow_redirects() -> None:
    """A process on the loopback port cannot 307 the request body to another host."""
    from alphaswarm.ollama_client import OllamaClient

    http = OllamaClient(base_url="http://localhost:11434").raw_client._client
    assert http.follow_redirects is False


def test_base_url_is_the_host_the_client_connects_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """base_url reads the resolved httpx host, including the OLLAMA_HOST fallback."""
    import httpx

    from alphaswarm.ollama_client import OllamaClient

    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box.local:11434")

    assert httpx.URL(OllamaClient(base_url="http://127.0.0.1:11434").base_url).host == "127.0.0.1"
    assert httpx.URL(OllamaClient(base_url="").base_url).host == "gpu-box.local"


def _client_answering_show(handler: Any) -> Any:
    import httpx

    from alphaswarm.ollama_client import OllamaClient

    client = OllamaClient(base_url="http://localhost:11434")
    client.raw_client._client = httpx.AsyncClient(
        base_url="http://localhost:11434", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.parametrize(
    ("body", "remote"),
    [
        ({"modelfile": "FROM qwen3", "details": {}}, False),
        ({"modelfile": "x", "remote_host": "https://ollama.com:443"}, True),
        ({"modelfile": "x", "remote_model": "gpt-oss:120b"}, True),
        ({"modelfile": "x", "remote_host": "", "remote_model": None}, False),
    ],
    ids=["local", "remote-host", "remote-model", "empty-fields"],
)
async def test_is_remote_model_reads_the_show_response(body: dict[str, Any], remote: bool) -> None:
    import httpx

    seen: list[Any] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.content))
        return httpx.Response(200, json=body)

    client = _client_answering_show(_handler)

    assert await client.is_remote_model("alphaswarm-orchestrator") is remote
    assert seen[0][0] == "/api/show"
    assert b"alphaswarm-orchestrator" in seen[0][1]


@pytest.mark.parametrize(
    "response",
    [
        {"status_code": 404, "json": {"error": "model not found"}},
        {"status_code": 500, "text": "boom"},
        {"status_code": 200, "text": "not json"},
        {"status_code": 200, "json": ["not", "an", "object"]},
    ],
    ids=["404", "500", "not-json", "not-an-object"],
)
async def test_is_remote_model_raises_when_it_cannot_tell(response: dict[str, Any]) -> None:
    """Callers fail closed on any error, so the method never guesses "local"."""
    import httpx

    client = _client_answering_show(lambda _r: httpx.Response(**response))

    with pytest.raises(Exception):  # noqa: B017 - any failure must propagate
        await client.is_remote_model("alphaswarm-orchestrator")
