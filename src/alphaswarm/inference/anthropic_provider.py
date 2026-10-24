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
- Failures follow docs/DECISIONS.md#adr-cloud-retry: 401/403 -> ``AuthError``;
  400/404/422 about the model or request -> ``ProviderConfigError``;
  408/409/429/5xx/529 and connection errors retry with capped full jitter;
  timeouts are never retried.
- An injected client (for tests) is never closed by ``aclose()``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

import anthropic
import structlog

from alphaswarm.errors import AuthError, InferenceError, ProviderConfigError
from alphaswarm.inference.call_log import logged_call
from alphaswarm.inference.retry import (
    DEFAULT_RETRY_POLICY,
    RetryGate,
    RetryPolicy,
    Verdict,
    classify_status,
    retry_after_seconds,
    wait_before_retry,
)
from alphaswarm.inference.schema import extract_anthropic_tool_json, to_anthropic_tool
from alphaswarm.inference.types import (
    FinishReason,
    InferenceMessage,
    InferenceResult,
    ProviderRole,
    count_or_none,
)

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

log = structlog.get_logger(component="inference.anthropic")
_PROVIDER: Final = "anthropic"

# Messages API stop_reason → normalized finish reason (docs/DECISIONS.md#adr-inference-telemetry).
_STOP_REASONS: Final[Mapping[str, FinishReason]] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_use",
    "refusal": "content_filter",
    "pause_turn": "other",
}


def _finish_reason(value: object) -> FinishReason | None:
    if not isinstance(value, str):
        return None
    return _STOP_REASONS.get(value, "other")


def _error_text(exc: anthropic.APIStatusError) -> str:
    """The SDK's message plus the raw error body, for classification and messages."""
    body = "" if exc.body is None else json.dumps(exc.body, default=str)
    return f"{exc.message} {body}".strip()


def _retry_after_header(exc: anthropic.APIStatusError) -> str | None:
    try:
        return exc.response.headers.get("retry-after")
    except AttributeError:
        return None


def _system_blocks(parts: list[str]) -> list[dict[str, Any]]:
    """System text as content blocks with a cache breakpoint after the shared prefix.

    The texts concatenate to the newline-joined string a single block would carry.
    Every system message but the last is treated as shared; the worker sends the
    guards and the persona's bracket block before the agent's own text
    (docs/DECISIONS.md#adr-prefix-reuse).
    """
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": part + ("\n" if i < len(parts) - 1 else "")} for i, part in enumerate(parts)
    ]
    blocks[-2]["cache_control"] = {"type": "ephemeral"}
    return blocks


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
        max_retries: How often a retryable failure (408/409/429/5xx/529,
            connection errors) is retried. Timeouts and 4xx are never retried.
        retry_policy: Backoff shape and an injectable sleep (tests).
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
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> None:
        self.role: ProviderRole = role
        self.model: str = model
        self._max_tokens_default: int = max_tokens_default
        self._max_retries: int = max_retries
        self._retry_policy: RetryPolicy = retry_policy
        # Shared cooldown and RPM pacing in cloud mode; set by factory.attach_retry_gate
        # (docs/DECISIONS.md#adr-cloud-retry).
        self.retry_gate: RetryGate | None = None

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
        - System-role messages are hoisted to the top-level ``system=`` kwarg: one as
          a string, several as text blocks with a cache breakpoint after all but the
          last; they are removed from ``messages``.
        - ``response_schema`` → ``tools=[emit_decision]`` + forced ``tool_choice``;
          response JSON extracted from tool_use block.
        - No schema → concatenate all text blocks from response.
        - ``temperature`` omitted when None; ``max_tokens`` falls back to
          ``max_tokens_default`` when caller omits it.

        Retry policy: see ``_call_with_retry`` (docs/DECISIONS.md#adr-cloud-retry).

        Returns:
            ``InferenceResult`` with content, model, input_tokens, output_tokens.
        """
        # Split system messages out
        system_parts: list[str] = []
        remaining: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                if msg["content"]:
                    system_parts.append(msg["content"])
            else:
                remaining.append({"role": msg["role"], "content": msg["content"]})

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens_default,
            "messages": remaining,
        }
        if len(system_parts) == 1:
            kwargs["system"] = system_parts[0]
        elif system_parts:
            kwargs["system"] = _system_blocks(system_parts)
        if temperature is not None:
            kwargs["temperature"] = temperature

        if response_schema is not None:
            kwargs["tools"] = [to_anthropic_tool(response_schema)]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit_decision"}

        return await logged_call(
            self.role,
            self.model,
            self._call_with_retry(kwargs, use_tool=response_schema is not None),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        kwargs: dict[str, Any],
        *,
        use_tool: bool,
        max_retries: int | None = None,
    ) -> InferenceResult:
        """messages.create with classified retries (docs/DECISIONS.md#adr-cloud-retry)."""
        limit = self._max_retries if max_retries is None else max_retries
        retries = 0
        while True:
            try:
                resp = await self._client.messages.create(**kwargs)
            except anthropic.APITimeoutError as exc:
                raise InferenceError(
                    f"Request timed out (not retried): {exc}",
                    provider=_PROVIDER,
                    model=self.model,
                    original_error=exc,
                ) from exc
            except anthropic.APIConnectionError as exc:
                if retries >= limit:
                    raise InferenceError(
                        f"APIConnectionError after {retries} retries: {exc}",
                        provider=_PROVIDER,
                        model=self.model,
                        original_error=exc,
                    ) from exc
                await self._before_retry(retries, reason=type(exc).__name__)
                retries += 1
                continue
            except anthropic.APIStatusError as exc:
                text = _error_text(exc)
                verdict = classify_status(exc.status_code, text)
                if verdict is Verdict.AUTH:
                    raise AuthError(str(exc), provider=_PROVIDER, model=self.model) from exc
                if verdict is Verdict.CONFIG:
                    raise ProviderConfigError(
                        f"HTTP {exc.status_code} for model {self.model}: {text[:500]}",
                        provider=_PROVIDER,
                        model=self.model,
                        status_code=exc.status_code,
                        original_error=exc,
                    ) from exc
                if verdict in (Verdict.RETRY, Verdict.RATE_LIMITED) and retries < limit:
                    await self._before_retry(
                        retries,
                        reason=f"http_{exc.status_code}",
                        rate_limited=verdict is Verdict.RATE_LIMITED,
                        retry_after_s=retry_after_seconds(_retry_after_header(exc)),
                    )
                    retries += 1
                    continue
                raise InferenceError(
                    f"{type(exc).__name__} (HTTP {exc.status_code}) after {retries} retries: {text[:500]}",
                    provider=_PROVIDER,
                    model=self.model,
                    original_error=exc,
                ) from exc
            return self._parse_response(resp, use_tool=use_tool)

    async def _before_retry(
        self,
        attempt: int,
        *,
        reason: str,
        rate_limited: bool = False,
        retry_after_s: float | None = None,
    ) -> None:
        delay = await wait_before_retry(
            self._retry_policy,
            attempt,
            gate=self.retry_gate,
            rate_limited=rate_limited,
            retry_after_s=retry_after_s,
        )
        log.info(
            "inference_retry_waited",
            provider=_PROVIDER,
            model=self.model,
            attempt=attempt + 1,
            delay_s=round(delay, 2),
            reason=reason,
        )

    def _parse_response(self, resp: Any, *, use_tool: bool) -> InferenceResult:
        """Content and token counts; an unusable but billed response keeps its tokens.

        A successful response can still lack the forced tool_use block
        (stop_reason='max_tokens' truncation or a text-only refusal): that is an
        InferenceError carrying the billed counts (docs/DECISIONS.md#adr-cloud-retry).
        """
        usage = getattr(resp, "usage", None)
        uncached = count_or_none(getattr(usage, "input_tokens", None))
        cache_read = count_or_none(getattr(usage, "cache_read_input_tokens", None))
        cache_write = count_or_none(getattr(usage, "cache_creation_input_tokens", None))
        # The API's input_tokens is the uncached remainder; the normalized prompt
        # size adds cache reads and writes (docs/DECISIONS.md#adr-inference-telemetry).
        input_tokens = None if uncached is None else uncached + (cache_read or 0) + (cache_write or 0)
        output_tokens = count_or_none(getattr(usage, "output_tokens", None))
        try:
            if use_tool:
                content = extract_anthropic_tool_json(resp.content, name="emit_decision")
            else:
                content = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        except (ValueError, TypeError, AttributeError) as exc:
            raise InferenceError(
                f"Unusable response, expected forced tool_use 'emit_decision' or text "
                f"(stop_reason={getattr(resp, 'stop_reason', None)!r}): {exc}",
                provider=_PROVIDER,
                model=self.model,
                original_error=exc,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ) from exc
        return InferenceResult(
            content=content,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_prompt_tokens=cache_read,
            finish_reason=_finish_reason(getattr(resp, "stop_reason", None)),
        )
