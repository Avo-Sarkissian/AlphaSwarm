"""One retry policy for every inference backend (docs/DECISIONS.md#adr-cloud-retry).

- ``classify_status`` sorts an HTTP failure (status plus error body) into
  retry, rate-limited, auth, config or fail.
- ``RetryPolicy`` is capped full-jitter backoff: each wait is drawn from
  [0, min(cap, base * 2**attempt)] with base 1 s and cap 30 s. Sleep and the
  random draw are injectable, so tests never wait.
- ``retry_after_seconds`` reads Retry-After (delta-seconds or HTTP-date,
  clamped to 60 s); when present it replaces the backoff.
- ``RetryGate`` is the shared pacing RateLimitController offers in cloud mode:
  one cooldown after a 429 and a fresh RPM token for every retry.

Timeouts are never retried by any backend: a call that used its whole timeout
points at an overloaded endpoint, and retrying multiplies the stall.
"""

from __future__ import annotations

import asyncio
import enum
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from alphaswarm.errors import RETRYABLE_HTTP_STATUSES
from alphaswarm.inference.types import parse_retry_after

BACKOFF_BASE_S: Final = 1.0
BACKOFF_CAP_S: Final = 30.0
AUTH_STATUSES: Final[frozenset[int]] = frozenset({401, 403})
CONFIG_STATUSES: Final[frozenset[int]] = frozenset({400, 404, 422})

# A 400 that mentions one of these is about this prompt, not the configuration.
_CONTEXT_LIMIT_MARKERS: Final = (
    "context_length_exceeded",
    "context length",
    "context window",
    "maximum context",
    "prompt is too long",
    "too many tokens",
    "string_above_max_length",
    "reduce the length",
)
_CONTENT_FILTER_MARKERS: Final = (
    "content_filter",
    "content management policy",
    "content_policy_violation",
    "responsibleaipolicyviolation",
    "flagged as",
)
_UNPARSED: Final = -1.0


class Verdict(enum.StrEnum):
    """What to do with one failed request."""

    RETRY = "retry"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    CONFIG = "config"
    FAIL = "fail"


def is_context_limit_message(text: str) -> bool:
    """True when an error body says the prompt was too long for the model."""
    lower = text.lower()
    return any(marker in lower for marker in _CONTEXT_LIMIT_MARKERS)


def is_content_filter_message(text: str) -> bool:
    """True when an error body says a content filter rejected this prompt."""
    lower = text.lower()
    return any(marker in lower for marker in _CONTENT_FILTER_MARKERS)


def classify_status(status: int, body: str = "") -> Verdict:
    """Retry 408/409/429/5xx/529; never retry 400/401/403/404/422."""
    if status in AUTH_STATUSES:
        return Verdict.AUTH
    if status == 429:
        return Verdict.RATE_LIMITED
    if status in RETRYABLE_HTTP_STATUSES or status >= 500:
        return Verdict.RETRY
    if status in CONFIG_STATUSES:
        if is_context_limit_message(body) or is_content_filter_message(body):
            return Verdict.FAIL  # this prompt only: one PARSE_ERROR, not a stopped run
        return Verdict.CONFIG
    return Verdict.FAIL


def retry_after_seconds(raw: str | None) -> float | None:
    """Retry-After in seconds (clamped to 60 s), or None when absent or unparseable."""
    if raw is None or not raw.strip():
        return None
    value = parse_retry_after(raw, default=_UNPARSED)
    return None if value == _UNPARSED else value


@dataclass(frozen=True)
class RetryPolicy:
    """Capped full-jitter backoff. How MANY retries is the provider's ``max_retries``."""

    base_s: float = BACKOFF_BASE_S
    cap_s: float = BACKOFF_CAP_S
    # None means asyncio.sleep, looked up at call time so tests can patch it.
    sleep: Callable[[float], Awaitable[object]] | None = None
    rng: Callable[[], float] = random.random

    def backoff_s(self, attempt: int) -> float:
        """Wait before retry ``attempt + 1``: uniform in [0, min(cap, base * 2**attempt)]."""
        ceiling = min(self.cap_s, self.base_s * float(2 ** min(max(attempt, 0), 30)))
        return min(1.0, max(0.0, self.rng())) * ceiling

    async def pause(self, seconds: float) -> None:
        if self.sleep is not None:
            await self.sleep(seconds)
        else:
            await asyncio.sleep(seconds)


DEFAULT_RETRY_POLICY: Final = RetryPolicy()


@runtime_checkable
class RetryGate(Protocol):
    """Shared retry pacing (RateLimitController implements it in cloud mode)."""

    def note_rate_limited(self, seconds: float) -> None: ...

    async def before_retry(self) -> None: ...


async def wait_before_retry(
    policy: RetryPolicy,
    attempt: int,
    *,
    gate: RetryGate | None,
    rate_limited: bool = False,
    retry_after_s: float | None = None,
) -> float:
    """Wait before retry ``attempt + 1`` and return the planned delay in seconds.

    Retry-After wins over the backoff. With a gate, a 429's delay becomes the
    shared cooldown (every caller waits it once instead of each sleeping its
    own), and every retry then takes a fresh RPM token through ``before_retry``.
    """
    delay = retry_after_s if retry_after_s is not None else policy.backoff_s(attempt)
    if gate is None:
        await policy.pause(delay)
        return delay
    if rate_limited:
        gate.note_rate_limited(delay)
    else:
        await policy.pause(delay)
    await gate.before_retry()
    return delay
