"""Domain exceptions for AlphaSwarm inference and orchestration."""

from __future__ import annotations

from decimal import Decimal

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
        duration_seconds: How long the crisis lasted before the abort
            (0.0 when the monitor died outside a crisis).
    """

    def __init__(self, message: str, *, duration_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.duration_seconds = duration_seconds


class ParseError(Exception):
    """Raised when structured output parsing fails at all tiers.

    This is a non-retryable error -- the LLM output could not be parsed
    into the expected Pydantic model. Note: parse_agent_decision() never
    raises this; it returns PARSE_ERROR signal instead. This class exists
    for cases where callers explicitly need exception-based error handling.
    """

    def __init__(self, message: str, raw_content: str) -> None:
        super().__init__(message)
        self.raw_content = raw_content


class Neo4jConnectionError(Exception):
    """Raised when Neo4j driver cannot connect or verify connectivity."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error


class Neo4jWriteError(Exception):
    """Raised when a Neo4j write transaction fails after managed retries."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error
