"""AnthropicProvider — native Anthropic SDK adapter.

Uses the official ``anthropic`` Python SDK (AsyncAnthropic) to call Claude
models.  Conforms to the ``InferenceProvider`` protocol without subclassing it.

Key behaviours:
- System messages are extracted from the message list and passed as the
  top-level ``system=`` argument (Anthropic does not accept ``role=system``
  inside ``messages``).
- ``response_schema`` is mapped to a forced tool call via
  ``to_anthropic_tool`` + ``tool_choice={"type":"tool","name":"emit_decision"}``
  and the result is extracted via ``extract_anthropic_tool_json``.
- Auth failures (401/403) surface as ``AuthError``; rate-limit and network
  errors are retried with back-off and then surface as ``InferenceError``.
- An injected client (for tests) is never closed by ``aclose()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import anthropic

from alphaswarm.errors import AuthError, InferenceError
from alphaswarm.inference.schema import extract_anthropic_tool_json, to_anthropic_tool
from alphaswarm.inference.types import (
    InferenceMessage,
    InferenceResult,
    ProviderRole,
    parse_retry_after,
)

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Anthropic Messages API adapter.

    Lifecycle:
        ``prepare()`` and ``teardown()`` are no-ops.  Call ``await provider.aclose()``
        (or use ``async with``) to close the underlying client when this instance
        created it; an injected client is left open.

    Args:
        role: Whether this instance acts as ORCHESTRATOR or WORKER.
        model: The Claude model identifier (e.g. ``"claude-3-5-sonnet-20241022"``).
        api_key: Anthropic API key.
        max_tokens_default: Default max_tokens for requests when caller omits it.
        max_retries: Maximum retry attempts for rate-limit and connection errors.
        client: Optional pre-built ``AsyncAnthropic`` for tests.  When provided,
            ``aclose()`` will NOT close it — lifecycle ownership stays with caller.

    Satisfies:
        ``InferenceProvider`` (structural Protocol — no inheritance required).
    """

    def __init__(
        self,
        role: ProviderRole,
        model: str,
        *,
        api_key: str,
        max_tokens_default: int = 1024,
        max_retries: int = 3,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self.role: ProviderRole = role
        self.model: str = model
        self._max_tokens_default: int = max_tokens_default
        self._max_retries: int = max_retries

        # Track whether we own the client so aclose knows whether to close it
        self._client_owned: bool = client is None

        if client is not None:
            self._client: Any = client
        else:
            self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    # ------------------------------------------------------------------
    # InferenceProvider — protocol surface
    # ------------------------------------------------------------------

    def is_local(self) -> bool:
        """Return False — Anthropic routes to a remote cloud endpoint."""
        return False

    async def prepare(self) -> None:
        """No-op — cloud providers need no model warm-up."""

    async def teardown(self) -> None:
        """No-op — cloud providers need no model teardown."""

    async def aclose(self) -> None:
        """Close the underlying Anthropic client only if this instance created it."""
        if self._client_owned and hasattr(self._client, "close"):
            await self._client.close()

    # ------------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[InferenceMessage],
        *,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> InferenceResult:
        """Call the Anthropic Messages API and return a normalised result.

        Mapping rules:
        - System-role messages are hoisted to the top-level ``system=`` kwarg
          (joined with newlines when multiple); they are removed from ``messages``.
        - ``response_schema`` → ``tools=[emit_decision]`` + forced ``tool_choice``;
          response JSON extracted from tool_use block.
        - No schema → concatenate all text blocks from response.
        - ``temperature`` omitted when None; ``max_tokens`` falls back to
          ``max_tokens_default`` when caller omits it.

        Retry policy:
        - ``AuthenticationError`` / ``PermissionDeniedError`` → ``AuthError`` (no retry).
        - ``RateLimitError`` → honour ``retry-after`` header, retry up to max_retries,
          then ``InferenceError``.
        - ``APIConnectionError`` / ``APIStatusError`` → exponential back-off,
          retry up to max_retries, then ``InferenceError``.

        Returns:
            ``InferenceResult`` with content, model, input_tokens, output_tokens.
        """
        # Split system messages out
        system_parts: list[str] = []
        remaining: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                remaining.append({"role": msg["role"], "content": msg["content"]})

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens_default,
            "messages": remaining,
        }
        if system_parts:
            kwargs["system"] = "\n".join(system_parts)
        if temperature is not None:
            kwargs["temperature"] = temperature

        if response_schema is not None:
            kwargs["tools"] = [to_anthropic_tool(response_schema)]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit_decision"}

        return await self._call_with_retry(kwargs, use_tool=response_schema is not None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        kwargs: dict[str, Any],
        *,
        use_tool: bool,
    ) -> InferenceResult:
        """Call messages.create with retry logic; translate SDK exceptions."""
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.messages.create(**kwargs)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
                raise AuthError(
                    str(exc),
                    provider="anthropic",
                    model=self.model,
                ) from exc
            except anthropic.RateLimitError as exc:
                last_exc = exc
                retry_after = self._parse_retry_after(exc)
                if attempt < self._max_retries:
                    logger.warning(
                        "Anthropic rate limited; sleeping %.1fs (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        self._max_retries,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                raise InferenceError(
                    f"Rate limited after {self._max_retries} retries: {exc}",
                    provider="anthropic",
                    model=self.model,
                    original_error=exc,
                ) from exc
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    logger.warning(
                        "Anthropic API error %s; retrying in %ds (attempt %d/%d)",
                        type(exc).__name__,
                        backoff,
                        attempt + 1,
                        self._max_retries,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise InferenceError(
                    f"{type(exc).__name__} after {self._max_retries} retries: {exc}",
                    provider="anthropic",
                    model=self.model,
                    original_error=exc,
                ) from exc
            else:
                # Success
                return self._parse_response(resp, use_tool=use_tool)

        # Should be unreachable; satisfy mypy
        raise InferenceError(
            "Exhausted retries without a conclusive error",
            provider="anthropic",
            model=self.model,
            original_error=last_exc,
        )

    def _parse_response(self, resp: Any, *, use_tool: bool) -> InferenceResult:
        """Extract content and token counts from an Anthropic response."""
        if use_tool:
            # A successful response can still lack the forced tool_use block
            # (e.g. stop_reason='max_tokens' truncation or a text-only refusal).
            # extract_anthropic_tool_json raises ValueError there; translate it
            # into the provider's documented error contract so it is not a bare
            # ValueError escaping the retry/translation layer (F-22).
            try:
                content = extract_anthropic_tool_json(resp.content, name="emit_decision")
            except ValueError as exc:
                raise InferenceError(
                    f"Expected forced tool_use 'emit_decision' but none found "
                    f"(stop_reason={getattr(resp, 'stop_reason', None)!r}): {exc}",
                    provider="anthropic",
                    model=self.model,
                    original_error=exc,
                ) from exc
        else:
            # Concatenate all text blocks
            content = "".join(
                block.text
                for block in resp.content
                if getattr(block, "type", None) == "text"
            )

        return InferenceResult(
            content=content,
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    @staticmethod
    def _parse_retry_after(exc: anthropic.RateLimitError) -> float:
        """Extract Retry-After (delta-seconds or HTTP-date) from the exception.

        Uses the shared parser so the Anthropic and OpenAI providers honor the
        same forms and ceiling (F-23 parity); default 1.0 when absent/unparseable.
        """
        try:
            raw = exc.response.headers.get("retry-after")
        except AttributeError:
            return 1.0
        return parse_retry_after(raw, default=1.0)
