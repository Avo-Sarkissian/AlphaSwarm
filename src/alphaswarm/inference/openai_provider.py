"""OpenAICompatProvider — httpx-based adapter for OpenAI-compatible endpoints.

Supports any API that speaks the OpenAI chat-completions protocol:
OpenAI, OpenRouter, Together AI, Groq, vLLM, etc.

Conforms to the ``InferenceProvider`` protocol without subclassing it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from alphaswarm.errors import AuthError, InferenceError
from alphaswarm.inference.schema import to_openai_json_object, to_openai_response_format
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

logger = logging.getLogger(__name__)

# Sentinel: body text indicating the endpoint doesn't support strict JSON schema
_STRICT_UNSUPPORTED_MARKERS = ("json_schema", "response_format", "strict")


def _body_mentions_strict_unsupported(body: str) -> bool:
    """Return True if the 400 error body suggests strict JSON schema is unsupported."""
    lower = body.lower()
    return any(marker in lower for marker in _STRICT_UNSUPPORTED_MARKERS)


class OpenAICompatProvider:
    """HTTP adapter for any OpenAI-compatible chat-completions endpoint.

    Lifecycle:
        ``prepare()`` and ``teardown()`` are no-ops — cloud providers need no
        model loading.  Call ``await provider.aclose()`` (or use ``async with``)
        to close the underlying ``httpx.AsyncClient`` when this instance created
        it; an injected client is left open.

    Args:
        role: Whether this instance acts as ORCHESTRATOR or WORKER.
        model: The model identifier to pass in every request body.
        base_url: Root URL of the API (e.g. ``"https://api.openai.com/v1"``).
        api_key: Bearer token sent in the ``Authorization`` header.
        request_timeout_s: Per-request timeout in seconds (default 120).
        max_retries: Maximum number of retries for 429/5xx (default 3).
        extra_headers: Additional headers merged into every request.
        client: Optional pre-built ``httpx.AsyncClient`` (useful for testing
            with ``httpx.MockTransport``).  When provided, ``aclose()`` will
            NOT close it — lifecycle ownership stays with the caller.

    Satisfies:
        ``InferenceProvider`` (structural Protocol — no inheritance required).
    """

    def __init__(
        self,
        role: ProviderRole,
        model: str,
        *,
        base_url: str,
        api_key: str,
        request_timeout_s: float = 120.0,
        max_retries: int = 3,
        extra_headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.role: ProviderRole = role
        self.model: str = model
        self._max_retries: int = max_retries
        self._no_strict: bool = False  # set True when endpoint 400s on json_schema

        # Track whether we own the client (so aclose knows whether to close it)
        self._client_owned: bool = client is None

        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        if client is not None:
            self._client: httpx.AsyncClient = client
        else:
            self._client = httpx.AsyncClient(
                base_url=base_url,
                timeout=request_timeout_s,
                headers=headers,
            )

        # When an external client is injected we still need the headers applied
        # and the base_url used for request building.  Store them for use in chat().
        self._base_url: str = base_url.rstrip("/")
        self._headers: dict[str, str] = headers

    # ------------------------------------------------------------------
    # InferenceProvider — protocol surface
    # ------------------------------------------------------------------

    def is_local(self) -> bool:
        """Return False — this provider routes to a remote cloud endpoint."""
        return False

    async def prepare(self) -> None:
        """No-op — cloud providers need no model warm-up."""

    async def teardown(self) -> None:
        """No-op — cloud providers need no model teardown."""

    async def aclose(self) -> None:
        """Close the underlying HTTP client only if this instance created it."""
        if self._client_owned:
            await self._client.aclose()

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
        """POST to ``/chat/completions`` and return a normalised result.

        Mapping rules:
        - ``response_schema`` (and not ``_no_strict``) → ``response_format``
          built by ``to_openai_response_format``.
        - ``json_mode=True`` (or schema with ``_no_strict``) → ``response_format``
          built by ``to_openai_json_object``.
        - Neither → ``response_format`` key omitted entirely.
        - ``temperature`` / ``max_tokens`` included only when not None.

        Retry policy:
        - 400 indicating strict JSON schema unsupported: retry once with
          ``json_object`` fallback, set ``_no_strict=True``.
        - 401/403: raise ``AuthError`` immediately (no retry).
        - 429: honour ``Retry-After`` header, retry up to ``max_retries``.
        - 5xx / transport errors: exponential backoff up to ``max_retries``.

        Returns:
            ``InferenceResult`` with content, model, input_tokens, output_tokens.
            ``eval_count`` and ``eval_duration_ns`` are always ``None`` (cloud).
        """
        body = self._build_body(messages, response_schema, json_mode, temperature, max_tokens)
        return await self._post_with_retry(body, response_schema=response_schema)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_body(
        self,
        messages: list[InferenceMessage],
        response_schema: dict[str, Any] | None,
        json_mode: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        # Determine response_format
        if response_schema is not None and not self._no_strict:
            body["response_format"] = to_openai_response_format(response_schema)
        elif json_mode or (response_schema is not None and self._no_strict):
            body["response_format"] = to_openai_json_object()
        # else: omit response_format key entirely

        return body

    async def _post_with_retry(
        self,
        body: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> InferenceResult:
        """POST body to /chat/completions with retry logic."""
        url = f"{self._base_url}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(url, json=body, headers=self._headers)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise InferenceError(
                    f"Transport error after {self._max_retries} retries: {exc}",
                    provider="openai_compatible",
                    model=self.model,
                    original_error=exc,
                ) from exc

            if resp.status_code == 200:
                return self._parse_response(resp)

            if resp.status_code in (401, 403):
                raise AuthError(
                    f"Authentication failed (HTTP {resp.status_code}): {resp.text}",
                    provider="openai_compatible",
                    model=self.model,
                )

            if resp.status_code == 400:
                # Check if the 400 is about strict JSON schema being unsupported.
                # Only meaningful when a schema was requested.
                if (
                    response_schema is not None
                    and _body_mentions_strict_unsupported(resp.text)
                    and not self._no_strict
                ):
                    # First time: downgrade to json_object and retry once.
                    self._no_strict = True
                    body["response_format"] = to_openai_json_object()
                    # Single immediate retry (not counted against max_retries).
                    try:
                        retry_resp = await self._client.post(
                            url, json=body, headers=self._headers
                        )
                    except (httpx.TransportError, httpx.TimeoutException) as exc:
                        raise InferenceError(
                            f"Transport error on strict-downgrade retry: {exc}",
                            provider="openai_compatible",
                            model=self.model,
                            original_error=exc,
                        ) from exc

                    if retry_resp.status_code == 200:
                        return self._parse_response(retry_resp)
                    raise InferenceError(
                        f"Strict-downgrade retry also failed (HTTP {retry_resp.status_code}): "
                        f"{retry_resp.text}",
                        provider="openai_compatible",
                        model=self.model,
                    )
                # Non-schema-related 400 or already in no_strict mode
                raise InferenceError(
                    f"Bad request (HTTP 400): {resp.text}",
                    provider="openai_compatible",
                    model=self.model,
                )

            if resp.status_code == 429:
                retry_after = self._parse_retry_after(resp, default=1.0)
                if attempt < self._max_retries:
                    await asyncio.sleep(retry_after)
                    continue
                raise InferenceError(
                    f"Rate limited after {self._max_retries} retries",
                    provider="openai_compatible",
                    model=self.model,
                )

            if resp.status_code >= 500:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                raise InferenceError(
                    f"Server error (HTTP {resp.status_code}) after {self._max_retries} retries: "
                    f"{resp.text}",
                    provider="openai_compatible",
                    model=self.model,
                )

            # Unexpected status code — treat as fatal
            raise InferenceError(
                f"Unexpected HTTP {resp.status_code}: {resp.text}",
                provider="openai_compatible",
                model=self.model,
            )

        # Should be unreachable, but satisfy mypy
        raise InferenceError(
            "Exhausted retries without a conclusive error",
            provider="openai_compatible",
            model=self.model,
            original_error=last_error,
        )

    def _parse_response(self, resp: httpx.Response) -> InferenceResult:
        """Parse a 200 response into an ``InferenceResult``."""
        data = resp.json()
        content: str = (
            (data["choices"][0]["message"]["content"] or "") if data.get("choices") else ""
        )
        usage = data.get("usage", {})
        return InferenceResult(
            content=content,
            model=self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    @staticmethod
    def _parse_retry_after(resp: httpx.Response, *, default: float) -> float:
        """Read ``Retry-After`` header as seconds; fall back to *default*."""
        raw = resp.headers.get("retry-after", "")
        try:
            return float(raw)
        except (ValueError, TypeError):
            return default
