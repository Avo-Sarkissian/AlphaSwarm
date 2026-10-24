"""InferenceProvider protocol — the contract every backend must satisfy.

All provider implementations (Ollama, OpenAI-compatible, Anthropic) must
satisfy this Protocol.  Because it is decorated with @runtime_checkable,
callers can use isinstance() checks at runtime (e.g., in tests and dispatch
logic) without requiring a shared abstract base class.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole


@runtime_checkable
class InferenceProvider(Protocol):
    """Structural protocol for all AlphaSwarm inference backends.

    Providers are stateful objects that manage a single (role, model) pairing.
    They are not thread-safe; callers must serialize access or use one instance
    per asyncio task.

    Lifecycle:
        1. Instantiate with role + model + backend-specific kwargs.
        2. Call ``await provider.prepare()`` before the first ``chat`` call to
           warm up connections, load models, etc.
        3. Issue any number of ``await provider.chat(...)`` calls.
        4. Call ``await provider.teardown()`` to release the model (Ollama
           unloads it; cloud providers do nothing), then ``await
           provider.aclose()`` to close any HTTP client the provider created.
           The two are not aliases.

    Attributes:
        role: Whether this provider acts as ORCHESTRATOR or WORKER.
        model: The model identifier string (e.g., "qwen3:8b", "gpt-4o").
    """

    role: ProviderRole
    model: str

    def is_local(self) -> bool:
        """Return True if inference runs on-device (Ollama), False for cloud."""
        ...

    async def prepare(self) -> None:
        """Warm up the provider (load model, open connections, etc.).

        Must be called before the first ``chat`` call.  Implementations should
        be idempotent — calling prepare twice must not raise.
        """
        ...

    async def teardown(self) -> None:
        """Release the model ``prepare`` loaded (Ollama unloads it; cloud providers do nothing).

        Symmetric to ``prepare``: after teardown, ``chat`` must not be called until
        ``prepare`` runs again. HTTP clients stay open; ``aclose`` closes them.
        """
        ...

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
        """Run a chat-completion round and return normalized output.

        Args:
            messages: Ordered list of conversation turns.
            response_schema: JSON Schema dict constraining the response shape.
                Providers that support structured output (Ollama format=,
                OpenAI response_format, Anthropic tool_choice) should honour
                this.  Providers that do not may ignore it or raise.
            json_mode: When True, instruct the provider to emit raw JSON
                without a schema constraint.  Ignored if response_schema is set.
            temperature: Sampling temperature override (provider default if None).
            max_tokens: Maximum tokens to generate (provider default if None).
            seed: Sampling seed for reproducible decoding (provider default if
                None). Ollama maps it to ``options["seed"]`` and OpenAI-compatible
                servers to the ``seed`` field; Anthropic has no seed and ignores it
                (docs/DECISIONS.md#adr-run-manifest).

        Returns:
            InferenceResult with content, model, and optional token counts.

        Raises:
            InferenceError: On any backend failure after retries exhausted.
            AuthError: On 401/403 credential failures.
        """
        ...

    async def aclose(self) -> None:
        """Close client resources this provider owns (not an alias for ``teardown``)."""
        ...
