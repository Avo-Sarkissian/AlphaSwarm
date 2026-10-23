"""Normalized inference types shared across all provider backends.

These types form the provider-agnostic contract so callers never import
Ollama-specific structures directly.  Both the local (Ollama) and future
cloud adapters produce and consume these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Literal, TypedDict

# Cap any honored Retry-After so a misbehaving gateway can't park a worker for
# minutes/hours.
_MAX_RETRY_AFTER_SECONDS = 60.0


def parse_retry_after(raw: str | None, *, default: float) -> float:
    """Parse an HTTP ``Retry-After`` header value into a clamped seconds delay.

    RFC 7231 allows either delta-seconds (``"30"``) or an HTTP-date
    (``"Wed, 21 Oct 2026 07:28:00 GMT"``); proxies/gateways in front of
    OpenAI-compatible and Anthropic endpoints emit either form on 429. Shared by
    both cloud providers so the parsing (and the clamp) stays consistent — a
    bare ``float()`` ignored the date form, and an unclamped numeric value could
    sleep for hours. Returns *default* when the value is absent/unparseable.
    """
    if not raw:
        return default
    raw = raw.strip()
    try:
        return max(0.0, min(float(raw), _MAX_RETRY_AFTER_SECONDS))
    except (ValueError, TypeError):
        pass
    try:
        dt = parsedate_to_datetime(raw)
    except (ValueError, TypeError):
        return default
    if dt is None:
        return default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delay = (dt - datetime.now(UTC)).total_seconds()
    return max(0.0, min(delay, _MAX_RETRY_AFTER_SECONDS))


def count_or_none(value: object) -> int | None:
    """A token count reported by a backend, or None when absent or not an integer.

    Shared by the providers so partial responses (older servers, test fakes)
    degrade to "unknown" instead of raising (docs/DECISIONS.md#adr-inference-telemetry).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


FinishReason = Literal["stop", "length", "content_filter", "tool_use", "error", "other"]


class ProviderRole(StrEnum):
    """Distinguishes the two inference roles in AlphaSwarm.

    ORCHESTRATOR: The high-quality model responsible for synthesis, reasoning,
        and decision-making across agent rounds.
    WORKER: The fast, lower-cost model used for individual agent inference
        during simulation rounds.
    """

    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"


class InferenceMessage(TypedDict):
    """A single turn in a chat conversation.

    Mirrors the OpenAI chat-message schema so the same structure works for
    Ollama (which accepts the same shape) and future cloud adapters.

    Fields:
        role: One of "system", "user", or "assistant".
        content: The text content of the message.
    """

    role: str
    content: str


@dataclass(frozen=True)
class InferenceResult:
    """Normalized output from any inference provider.

    Telemetry fields are ``None`` when the backend does not report them
    (docs/DECISIONS.md#adr-inference-telemetry).

    Attributes:
        content: The generated text (raw or JSON string).
        model: The model identifier that produced the response.
        input_tokens: Prompt tokens ("prompt_tokens" in logs and metrics). Ollama:
            ``prompt_eval_count``, the tokens actually prefilled (a reused KV prefix
            is not counted). Cloud: the whole prompt, cached tokens included.
        output_tokens: Completion tokens ("completion_tokens"). Ollama: ``eval_count``.
        cached_prompt_tokens: Prompt tokens served from a provider cache (OpenAI
            ``prompt_tokens_details.cached_tokens``, Anthropic ``cache_read_input_tokens``).
        prefill_ms: Prompt evaluation time (Ollama ``prompt_eval_duration``).
        decode_ms: Generation time (Ollama ``eval_duration``).
        load_ms: Model load time paid by this call (Ollama ``load_duration``).
        finish_reason: Why generation stopped, normalized across providers;
            ``"length"`` means the output cap cut the reply.
    """

    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    prefill_ms: float | None = None
    decode_ms: float | None = None
    load_ms: float | None = None
    finish_reason: FinishReason | None = None
