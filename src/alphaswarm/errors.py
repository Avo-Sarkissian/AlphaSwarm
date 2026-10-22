"""Domain exceptions for AlphaSwarm inference, orchestration and persistence.

New domain errors derive from ``AlphaSwarmError``. The older inference errors
(``InferenceError``, ``BudgetExceededError``, ``GovernorCrisisError``) keep
their parents so existing ``except`` clauses behave exactly as before
(docs/DECISIONS.md#adr-taskgroup-dispatch).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

# ---------------------------------------------------------------------------
# Provider-agnostic inference errors
# ---------------------------------------------------------------------------


class InferenceError(Exception):
    """Provider-agnostic base for all inference failures.

    Use this as the catch-all type when downstream code should handle errors
    from any backend (Ollama, OpenAI-compatible, Anthropic, etc.) uniformly.

    Attributes:
        provider: Short identifier for the backend that raised (e.g., "ollama",
            "openai", "anthropic").
        model: The model identifier that was being called.
        original_error: The underlying exception, if available.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.original_error = original_error


class OllamaInferenceError(InferenceError):
    """Raised when all backoff retries are exhausted for an Ollama call.

    Also wraps non-retryable errors (e.g., RequestError) at the public API
    boundary so downstream code catches a single domain exception type.
    Addresses review concern: RequestError wrapping at public boundary.

    Attributes:
        model: The Ollama model tag that failed.
        original_error: The underlying exception that caused the failure.
    """

    def __init__(
        self,
        message: str,
        model: str,
        original_error: Exception | None = None,
        *,
        provider: str = "ollama",
    ) -> None:
        super().__init__(message, provider=provider, model=model, original_error=original_error)


class ModelLoadError(OllamaInferenceError):
    """Raised when a model fails to load or unload."""


class AuthError(InferenceError):
    """Raised on 401/403 authentication or authorization failures.

    Signals that the API key or credentials are invalid/missing.  Should not
    be retried without correcting the credential.
    """


class BudgetExceededError(Exception):
    """Raised when cumulative spend would exceed the configured cap.

    This is a standalone exception (not a subclass of InferenceError) so that
    budget enforcement can be treated as a hard stop that propagates past any
    generic inference error handlers.

    Attributes:
        spent_usd: Cumulative spend in USD at the moment of the violation.
        cap_usd: The configured budget cap in USD.
    """

    def __init__(self, spent_usd: Decimal, cap_usd: Decimal) -> None:
        super().__init__(
            f"Budget cap exceeded: spent ${spent_usd:.4f} > cap ${cap_usd:.4f}"
        )
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd


class GovernorCrisisError(Exception):
    """Raised when the governor must abort the run.

    Causes: a sustained memory crisis with no successful inference
    (docs/DECISIONS.md#p3-d-07), or a dead memory monitor.

    Attributes:
        duration_seconds: How long the crisis lasted before the abort. Always
            0.0 when the monitor loop failed, and when the monitor died outside
            a crisis.
    """

    def __init__(self, message: str, *, duration_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.duration_seconds = duration_seconds


class Neo4jConnectionError(Exception):
    """Raised when Neo4j driver cannot connect or verify connectivity."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error


class AlphaSwarmError(Exception):
    """Base class for AlphaSwarm domain errors."""


class GraphError(AlphaSwarmError):
    """A Neo4j operation failed.

    ``op`` names the GraphStateManager operation (for example
    ``"write_decisions"``; None when the raise site does not say) so logs and
    the UI can say what was being done without quoting driver text
    (docs/DECISIONS.md#adr-taskgroup-dispatch).
    """

    def __init__(
        self,
        message: str,
        original_error: BaseException | None = None,
        *,
        op: str | None = None,
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.op = op


class Neo4jUnavailableError(GraphError):
    """The database could not be reached: driver error, auth failure or pool timeout."""


class Neo4jQueryError(GraphError):
    """A read failed on the server (syntax, constraint or transaction timeout)."""


class Neo4jWriteError(GraphError):
    """A write failed, or created fewer nodes than expected."""


class RoundFailedError(AlphaSwarmError):
    """Too many agents failed in a round, so the round is not persisted.

    Raised after ``dispatch_wave`` and before the round's first Neo4j write
    when ``failed * 100 > threshold_percent * total``
    (docs/DECISIONS.md#adr-taskgroup-dispatch).
    """

    def __init__(
        self,
        round_num: int,
        failed: int,
        total: int,
        threshold_percent: float,
    ) -> None:
        super().__init__(
            f"Round {round_num} aborted: {failed} of {total} agents failed "
            f"(limit {threshold_percent:g}%)"
        )
        self.round_num = round_num
        self.failed = failed
        self.total = total
        self.threshold_percent = threshold_percent


class InferenceConfigError(AlphaSwarmError):
    """The persisted inference configuration could not be loaded or built."""


# ---------------------------------------------------------------------------
# UI-safe description of a failed run (StateStore.last_error)
# ---------------------------------------------------------------------------

RunErrorCode = Literal[
    "budget_exceeded",
    "auth_failed",
    "governor_crisis",
    "round_failed",
    "provider_config",  # mapped once ProviderConfigError exists
    "graph_unavailable",
    "graph_error",
    "inference_config_invalid",
    "internal_error",
]

RUN_ERROR_MESSAGE_MAX_CHARS: Final = 300


@dataclass(frozen=True)
class RunError:
    """What the UI shows about a failed run.

    ``message`` is a fixed template filled from structured attributes only;
    it never quotes exception text, so it cannot leak a path, a key or a
    holdings value (docs/DECISIONS.md#adr-taskgroup-dispatch).
    """

    code: RunErrorCode
    message: str
    round_num: int | None
    ts: float


def run_error_from_exception(exc: BaseException, *, round_num: int | None) -> RunError:
    """Classify *exc* into a RunError. ``round_num`` is the round in progress, if any."""
    code, message = _describe(_first_leaf(exc))
    return RunError(
        code=code,
        message=message[:RUN_ERROR_MESSAGE_MAX_CHARS],
        round_num=round_num,
        ts=time.time(),
    )


def _first_leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _describe(exc: BaseException) -> tuple[RunErrorCode, str]:
    if isinstance(exc, BudgetExceededError):
        return (
            "budget_exceeded",
            f"Spend cap reached: ${exc.spent_usd:.2f} spent of a ${exc.cap_usd:.2f} cap. "
            "Raise the cap in Settings to continue.",
        )
    if isinstance(exc, AuthError):
        return (
            "auth_failed",
            f"The {exc.provider} provider rejected the credentials for model "
            f"{exc.model}. Update the API key in Settings.",
        )
    if isinstance(exc, GovernorCrisisError):
        if exc.duration_seconds > 0:
            return (
                "governor_crisis",
                f"The memory governor aborted the run after {exc.duration_seconds:.0f} s "
                "of sustained memory pressure.",
            )
        # No crisis was timed, so the abort came from the memory monitor dying.
        return (
            "governor_crisis",
            "The memory governor aborted the run because its memory monitor stopped. "
            "See the server log for details.",
        )
    if isinstance(exc, RoundFailedError):
        return (
            "round_failed",
            f"Round {exc.round_num} aborted: {exc.failed} of {exc.total} agents failed "
            f"(limit {exc.threshold_percent:g}%). Check the model server or provider.",
        )
    if isinstance(exc, Neo4jUnavailableError):
        return (
            "graph_unavailable",
            "Neo4j is unavailable. Start the database and run again.",
        )
    if isinstance(exc, GraphError):
        return (
            "graph_error",
            f"A Neo4j operation failed ({exc.op or 'unknown'}). See the server log for details.",
        )
    if isinstance(exc, InferenceConfigError):
        return (
            "inference_config_invalid",
            "The saved inference configuration is invalid. "
            "Open Settings and save a valid configuration.",
        )
    return ("internal_error", f"Unexpected {type(exc).__name__}. See the server log for details.")
