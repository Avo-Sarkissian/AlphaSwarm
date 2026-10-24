"""OpenAICompatProvider — httpx-based adapter for OpenAI-compatible endpoints.

Supports any API that speaks the OpenAI chat-completions protocol:
OpenAI, OpenRouter, Together AI, Groq, vLLM, etc.

Conforms to the ``InferenceProvider`` protocol without subclassing it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

import httpx
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
from alphaswarm.inference.schema import to_openai_json_object, to_openai_response_format
from alphaswarm.inference.types import (
    FinishReason,
    InferenceMessage,
    InferenceResult,
    ProviderRole,
    count_or_none,
)

log = structlog.get_logger(component="inference.openai")

# Sentinel: body text indicating the endpoint doesn't support strict JSON schema
_STRICT_UNSUPPORTED_MARKERS = ("json_schema", "response_format", "strict")
_PROVIDER: Final = "openai_compatible"
_PREFLIGHT_TIMEOUT_S: Final = 10.0
_PREFLIGHT_MAX_RETRIES: Final = 2

# OpenAI finish_reason → normalized finish reason (docs/DECISIONS.md#adr-inference-telemetry).
_FINISH_REASONS: Final[Mapping[str, FinishReason]] = {
    "stop": "stop",
    "length": "length",
    "content_filter": "content_filter",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
}


def _finish_reason(value: object) -> FinishReason | None:
    if not isinstance(value, str):
        return None
    return _FINISH_REASONS.get(value, "other")


def _body_mentions_strict_unsupported(body: str) -> bool:
    """Return True if the 400 error body suggests strict JSON schema is unsupported."""
    lower = body.lower()
    return any(marker in lower for marker in _STRICT_UNSUPPORTED_MARKERS)


def _billed_usage(resp: httpx.Response) -> tuple[int | None, int | None]:
    """Prompt and completion tokens from a 200 body's usage block; never raises."""
    try:
        usage = resp.json().get("usage") or {}
        return count_or_none(usage.get("prompt_tokens")), count_or_none(usage.get("completion_tokens"))
    except (ValueError, AttributeError):
        return None, None


def _listed_model_ids(payload: object) -> list[str]:
    """Ids from an OpenAI-style listing: ``{"data": [{"id": ...}]}`` or a bare list."""
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def _listing_matches(model: str, listed: Iterable[str]) -> bool:
    """The exact id, or the same id behind a namespace prefix (``models/gemini-2.5-flash``)."""
    return any(item == model or item.endswith("/" + model) or model.endswith("/" + item) for item in listed)


def _excerpt(text: str, limit: int = 200) -> str:
    """Whitespace-collapsed prefix of a provider error body, for one log line."""
    return " ".join(text.split())[:limit]


class OpenAICompatProvider:
    """HTTP adapter for any OpenAI-compatible chat-completions endpoint.

    Lifecycle:
        ``prepare()`` runs a preflight once per instance (see ``prepare``);
        ``teardown()`` is a no-op.  Call ``await provider.aclose()`` (or use ``async with``)
        to close the underlying ``httpx.AsyncClient`` when this instance created
        it; an injected client is left open.

    Args:
        role: Whether this instance acts as ORCHESTRATOR or WORKER.
        model: The model identifier to pass in every request body.
        base_url: Root URL of the API (e.g. ``"https://api.openai.com/v1"``).
        api_key: Bearer token sent in the ``Authorization`` header.
        request_timeout_s: Per-request timeout in seconds (default 120).
        max_retries: How often a retryable failure (408/409/429/5xx, connection
            errors) is retried (default 3). Timeouts and 4xx are never retried.
        retry_policy: Backoff shape and an injectable sleep (tests).
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
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> None:
        self.role: ProviderRole = role
        self.model: str = model
        self._max_retries: int = max_retries
        self._no_strict: bool = False  # set True when endpoint 400s on json_schema
        self._retry_policy: RetryPolicy = retry_policy
        # Shared cooldown and RPM pacing in cloud mode; set by factory.attach_retry_gate
        # (docs/DECISIONS.md#adr-cloud-retry).
        self.retry_gate: RetryGate | None = None
        self._preflighted = False

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
        """Preflight once per instance: does this endpoint serve the model?

        The model listing is only a fast positive (ids may carry a namespace
        prefix, and some gateways refuse /models); a miss falls back to a
        1-token completion whose answer is definitive. A wrong model id or base
        URL raises ProviderConfigError, a bad key AuthError; a transient failure
        is logged and does not block the run (docs/DECISIONS.md#adr-cloud-retry).
        """
        if self._preflighted:
            return
        if not await self._listing_includes_model():
            await self._preflight_completion()
        self._preflighted = True

    async def _listing_includes_model(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self._base_url}/models", headers=self._headers, timeout=_PREFLIGHT_TIMEOUT_S
            )
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        try:
            listed = _listed_model_ids(resp.json())
        except ValueError:
            return False
        return _listing_matches(self.model, listed)

    async def _preflight_completion(self) -> None:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        try:
            await self._post_with_retry(body, max_retries=min(self._max_retries, _PREFLIGHT_MAX_RETRIES))
        except (AuthError, ProviderConfigError):
            raise
        except InferenceError as exc:
            log.warning(
                "cloud_preflight_inconclusive",
                provider=_PROVIDER,
                model=self.model,
                error=str(exc)[:200],
            )

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
        seed: int | None = None,
    ) -> InferenceResult:
        """POST to ``/chat/completions`` and return a normalised result.

        Mapping rules:
        - ``response_schema`` (and not ``_no_strict``) → ``response_format``
          built by ``to_openai_response_format``.
        - ``json_mode=True`` (or schema with ``_no_strict``) → ``response_format``
          built by ``to_openai_json_object``.
        - Neither → ``response_format`` key omitted entirely.
        - ``temperature`` / ``max_tokens`` / ``seed`` included only when not None.

        Retry policy: see ``_post_with_retry`` (docs/DECISIONS.md#adr-cloud-retry).

        Returns:
            ``InferenceResult`` with content, model, input_tokens, output_tokens.
            Cached prompt tokens and the finish reason are reported; timings are not (cloud).
        """
        body = self._build_body(messages, response_schema, json_mode, temperature, max_tokens)
        if seed is not None:
            body["seed"] = seed
        return await logged_call(self.role, self.model, self._post_with_retry(body, response_schema=response_schema))

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
        max_retries: int | None = None,
    ) -> InferenceResult:
        """POST ``body`` to /chat/completions (docs/DECISIONS.md#adr-cloud-retry).

        - 401/403 -> AuthError. A 400/404/422 that is not about the schema, the
          prompt's size or a content filter -> ProviderConfigError (a hard stop).
        - 408/409/429/5xx/529 and connection errors -> capped full-jitter backoff
          (Retry-After wins), at most ``max_retries`` times (default: the
          provider's). With ``retry_gate`` set, a 429 sets the shared cooldown
          and every retry takes a fresh RPM token.
        - Timeouts are never retried. A 200 whose body cannot be used is an
          InferenceError that keeps the billed token counts.
        - A 400 naming json_schema/response_format downgrades once to
          json_object, outside the retry budget.
        """
        limit = self._max_retries if max_retries is None else max_retries
        url = f"{self._base_url}/chat/completions"
        retries = 0
        while True:
            try:
                resp = await self._client.post(url, json=body, headers=self._headers)
            except httpx.TimeoutException as exc:
                raise InferenceError(
                    f"Request timed out (not retried): {exc}",
                    provider=_PROVIDER,
                    model=self.model,
                    original_error=exc,
                ) from exc
            except httpx.TransportError as exc:
                if retries >= limit:
                    raise InferenceError(
                        f"Transport error after {retries} retries: {exc}",
                        provider=_PROVIDER,
                        model=self.model,
                        original_error=exc,
                    ) from exc
                await self._before_retry(retries, reason=type(exc).__name__)
                retries += 1
                continue

            if resp.status_code == 200:
                return self._parse_ok(resp)

            if resp.status_code == 400 and response_schema is not None and _body_mentions_strict_unsupported(resp.text):
                if not self._no_strict:
                    # Downgrade once to json_object; not counted against the budget.
                    self._no_strict = True
                    log.warning(
                        "openai_strict_schema_downgraded",
                        model=self.model,
                        status=resp.status_code,
                        body_excerpt=_excerpt(resp.text),
                    )
                    body["response_format"] = to_openai_json_object()
                    continue
                raise InferenceError(
                    f"Schema rejected after the json_object downgrade (HTTP 400): {_excerpt(resp.text, 500)}",
                    provider=_PROVIDER,
                    model=self.model,
                )

            verdict = classify_status(resp.status_code, resp.text)
            if verdict is Verdict.AUTH:
                raise AuthError(
                    f"Authentication failed (HTTP {resp.status_code}): {_excerpt(resp.text, 500)}",
                    provider=_PROVIDER,
                    model=self.model,
                )
            if verdict is Verdict.CONFIG:
                raise ProviderConfigError(
                    f"HTTP {resp.status_code} for model {self.model}: {_excerpt(resp.text, 500)}",
                    provider=_PROVIDER,
                    model=self.model,
                    status_code=resp.status_code,
                )
            if verdict in (Verdict.RETRY, Verdict.RATE_LIMITED) and retries < limit:
                await self._before_retry(
                    retries,
                    reason=f"http_{resp.status_code}",
                    rate_limited=verdict is Verdict.RATE_LIMITED,
                    retry_after_s=retry_after_seconds(resp.headers.get("retry-after")),
                )
                retries += 1
                continue
            raise InferenceError(
                f"HTTP {resp.status_code} after {retries} retries: {_excerpt(resp.text, 500)}",
                provider=_PROVIDER,
                model=self.model,
            )

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

    def _parse_ok(self, resp: httpx.Response) -> InferenceResult:
        """Parse a 200; a body that cannot be used is an InferenceError with billed tokens."""
        try:
            return self._parse_response(resp)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            input_tokens, output_tokens = _billed_usage(resp)
            raise InferenceError(
                f"Malformed response body ({type(exc).__name__}): {exc}",
                provider=_PROVIDER,
                model=self.model,
                original_error=exc,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ) from exc

    def _parse_response(self, resp: httpx.Response) -> InferenceResult:
        """Parse a 200 response into an ``InferenceResult``."""
        data = resp.json()
        choices = data.get("choices")
        content: str = (choices[0]["message"]["content"] or "") if choices else ""
        raw_finish = choices[0].get("finish_reason") if choices else None
        usage = data.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        return InferenceResult(
            content=content,
            model=self.model,
            input_tokens=count_or_none(usage.get("prompt_tokens")),
            output_tokens=count_or_none(usage.get("completion_tokens")),
            cached_prompt_tokens=count_or_none(details.get("cached_tokens")),
            finish_reason=_finish_reason(raw_finish),
        )
