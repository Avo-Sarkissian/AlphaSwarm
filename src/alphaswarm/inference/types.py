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
from typing import TypedDict

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

    Attributes:
        content: The generated text (raw or JSON string).
        model: The model identifier that produced the response.
        input_tokens: Number of prompt tokens consumed (None if provider
            does not report this).
        output_tokens: Number of completion tokens generated (None if
            provider does not report this).
        eval_count: Ollama-specific completion token count alias (None for
            non-Ollama providers).
        eval_duration_ns: Ollama-specific wall-clock duration in nanoseconds
            (None for non-Ollama providers).
    """

    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    eval_count: int | None = None
    eval_duration_ns: int | None = None
