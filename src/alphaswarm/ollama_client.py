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

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        request_timeout_seconds: float | None = 600.0,
    ) -> None:
        # request_timeout_seconds caps EVERY inference call. Without it the
        # underlying httpx client waits forever, so a wedged Ollama server
        # (e.g. after macOS sleep/wake) blocks the entire dispatch_wave
        # TaskGroup with no recovery path — the governor's crisis timeout
        # only covers memory pressure, not stuck inference. A timed-out
        # agent surfaces as PARSE_ERROR via _safe_agent_inference instead
        # of hanging the simulation. None disables the cap (tests only).
        self._client = AsyncClient(host=base_url, timeout=request_timeout_seconds)
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
        except httpx.TimeoutException as exc:
            # Deliberately NOT retried: a request that exhausted the full
            # timeout budget indicates a wedged/overloaded server — retrying
            # would multiply the stall, not fix it.
            raise OllamaInferenceError(
                message=f"Ollama chat timed out: {exc}",
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
        result: ChatResponse = await self._client.chat(**kwargs)
        return result

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        format: str | dict[str, Any] | None = None,
        keep_alive: float | str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        """Send a generate request with contract enforcement.

        Args:
            model: Ollama model tag (e.g., "alphaswarm-worker" or base tag).
            prompt: User prompt text.
            system: Optional system prompt forwarded to the underlying ollama
                client. Symmetric with `chat()` which already supports system
                messages — keeps the readable "system + prompt" call style at
                callers like `_generate_decision_narratives` (D-03, 41.2-03).
            format: Output format. Use "json" for JSON mode.
            keep_alive: Model keep-alive duration. Use 0 to unload.
            options: Additional model options. num_ctx is STRIPPED if present.

        Raises:
            OllamaInferenceError: On transient errors after retries exhausted,
                or immediately on non-retryable RequestError.
        """
        safe_options = _strip_num_ctx(options)
        try:
            return await self._generate_with_backoff(
                model=model,
                prompt=prompt,
                system=system,
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
        except httpx.TimeoutException as exc:
            # NOT retried — same rationale as chat().
            raise OllamaInferenceError(
                message=f"Ollama generate timed out: {exc}",
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
