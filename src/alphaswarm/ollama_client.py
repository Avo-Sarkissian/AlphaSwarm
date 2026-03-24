"""Ollama AsyncClient wrapper enforcing project contracts.

Contracts:
- No per-request num_ctx (causes silent model reloads)
- Exponential backoff on transient errors (ResponseError, ConnectionError, httpx.ConnectError)
- OllamaInferenceError raised after max_tries exhausted
- RequestError wrapped in OllamaInferenceError at public boundary (not retried)
- All inference goes through this wrapper, never raw AsyncClient
"""

from __future__ import annotations

from typing import Any

import backoff
import httpx
import structlog
from ollama import AsyncClient, ChatResponse, RequestError, ResponseError

from alphaswarm.errors import OllamaInferenceError

logger = structlog.get_logger(component="ollama_client")


def _strip_num_ctx(options: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove num_ctx from options dict to prevent silent model reloads."""
    if options is None:
        return None
    filtered = {k: v for k, v in options.items() if k != "num_ctx"}
    return filtered if filtered else None


class OllamaClient:
    """Wrapper around ollama.AsyncClient enforcing project contracts.

    Usage:
        client = OllamaClient(base_url="http://localhost:11434")
        response = await client.chat(model="alphaswarm-worker", messages=[...])
    """

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._client = AsyncClient(host=base_url)
        self._base_url = base_url

    @property
    def raw_client(self) -> AsyncClient:
        """Access underlying AsyncClient for model management (ps, create, etc)."""
        return self._client

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        format: str | dict[str, Any] | None = None,
        think: bool | None = None,
        keep_alive: float | str | None = None,
        options: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Send a chat request with contract enforcement.

        Args:
            model: Ollama model tag (e.g., "alphaswarm-worker" or base tag).
            messages: List of message dicts with "role" and "content" keys.
            format: Output format. Use "json" for JSON mode.
            think: Enable/disable thinking mode for Qwen3 models.
            keep_alive: Model keep-alive duration. Use 0 to unload.
            options: Additional model options. num_ctx is STRIPPED if present.

        Raises:
            OllamaInferenceError: On transient errors after retries exhausted,
                or immediately on non-retryable RequestError.
        """
        safe_options = _strip_num_ctx(options)
        if options and "num_ctx" in options:
            logger.warning(
                "num_ctx stripped from options -- use Modelfiles instead",
                model=model,
            )
        try:
            return await self._chat_with_backoff(
                model=model,
                messages=messages,
                format=format,
                think=think,
                keep_alive=keep_alive,
                options=safe_options,
            )
        except RequestError as exc:
            # Non-retryable: wrap at public boundary per review feedback
            raise OllamaInferenceError(
                message=f"Ollama request validation failed: {exc}",
                model=model,
                original_error=exc,
            ) from exc
        except (ResponseError, ConnectionError, httpx.ConnectError) as exc:
            raise OllamaInferenceError(
                message=f"Ollama chat failed after retries: {exc}",
                model=model,
                original_error=exc,
            ) from exc

    @backoff.on_exception(
        backoff.expo,
        (ResponseError, ConnectionError, httpx.ConnectError),
        max_tries=3,
    )
    async def _chat_with_backoff(self, **kwargs: Any) -> ChatResponse:
        """Internal chat call with exponential backoff on transient errors."""
        return await self._client.chat(**kwargs)

    async def generate(
        self,
        model: str,
        prompt: str,
        format: str | dict[str, Any] | None = None,
        keep_alive: float | str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        """Send a generate request with contract enforcement."""
        safe_options = _strip_num_ctx(options)
        try:
            return await self._generate_with_backoff(
                model=model,
                prompt=prompt,
                format=format,
                keep_alive=keep_alive,
                options=safe_options,
            )
        except RequestError as exc:
            raise OllamaInferenceError(
                message=f"Ollama request validation failed: {exc}",
                model=model,
                original_error=exc,
            ) from exc
        except (ResponseError, ConnectionError, httpx.ConnectError) as exc:
            raise OllamaInferenceError(
                message=f"Ollama generate failed after retries: {exc}",
                model=model,
                original_error=exc,
            ) from exc

    @backoff.on_exception(
        backoff.expo,
        (ResponseError, ConnectionError, httpx.ConnectError),
        max_tries=3,
    )
    async def _generate_with_backoff(self, **kwargs: Any) -> Any:
        """Internal generate call with exponential backoff."""
        return await self._client.generate(**kwargs)
