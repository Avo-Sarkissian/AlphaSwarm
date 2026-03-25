"""Domain exceptions for AlphaSwarm Ollama integration."""

from __future__ import annotations


class OllamaInferenceError(Exception):
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
    ) -> None:
        super().__init__(message)
        self.model = model
        self.original_error = original_error


class ModelLoadError(OllamaInferenceError):
    """Raised when a model fails to load or unload."""


class GovernorCrisisError(Exception):
    """Raised when governor crisis timeout expires (5min sustained pressure, no success).

    Attributes:
        duration_seconds: How long the crisis lasted before timeout.
    """

    def __init__(self, message: str, duration_seconds: float) -> None:
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
