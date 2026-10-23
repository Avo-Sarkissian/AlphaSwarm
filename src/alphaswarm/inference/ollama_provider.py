"""OllamaProvider — thin adapter that makes the local Ollama path conform to InferenceProvider.

This adapter is a faithful pass-through: it translates the provider-agnostic
``InferenceProvider.chat()`` signature into the ``OllamaClient.chat()`` calling
shape used by the existing worker, without changing any local inference behavior.

Local path calling shape (must stay identical to worker.py):
    client.chat(
        model=...,
        messages=...,
        format=DECISION_JSON_SCHEMA,   # or "json" or None
        think=False,
        keep_alive="5m",
        options={"temperature": ...},  # or None if not set
    )
"""

from __future__ import annotations

from typing import Any

import structlog

from alphaswarm.inference.provider import InferenceProvider  # noqa: F401  (Protocol)
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole
from alphaswarm.ollama_client import OllamaClient
from alphaswarm.ollama_models import OllamaModelManager

logger = structlog.get_logger(component="ollama_provider")


class OllamaProvider:
    """Adapter that wraps ``OllamaClient`` behind the ``InferenceProvider`` protocol.

    Instantiate once per (role, model) pairing.  The ``OllamaClient`` and
    ``OllamaModelManager`` lifecycles are owned by the caller; ``aclose()`` is
    a no-op here because the client is shared.

    Args:
        role: Whether this instance acts as ORCHESTRATOR or WORKER.
        model_tag: Ollama model tag (e.g. ``"alphaswarm-worker"``).
        client: Shared ``OllamaClient`` wrapper.  Must remain open for the
            lifetime of this provider.
        model_manager: ``OllamaModelManager`` used to load/unload the model.
        keep_alive: Keep-alive duration forwarded verbatim to each
            ``OllamaClient.chat()`` call.  Defaults to ``"5m"``.
        clean_state_on_prepare: When True, ``prepare()`` unloads resident
            AlphaSwarm models before loading this one.  ``build_providers``
            sets it for the worker only.  Defaults to ``False``.

    Satisfies:
        ``InferenceProvider`` (structural Protocol — no inheritance required).
    """

    def __init__(
        self,
        role: ProviderRole,
        model_tag: str,
        client: OllamaClient,
        model_manager: OllamaModelManager | None = None,
        *,
        keep_alive: str = "5m",
        clean_state_on_prepare: bool = False,
    ) -> None:
        self.role: ProviderRole = role
        self.model: str = model_tag
        self._client: OllamaClient = client
        self._model_manager: OllamaModelManager | None = model_manager
        self._keep_alive: str = keep_alive
        # Only the worker cleans: rounds start with no AlphaSwarm model resident, but an
        # orchestrator job (report, advisory) must never evict a worker an interview is
        # using (docs/DECISIONS.md#adr-round-runner).
        self.clean_state_on_prepare: bool = clean_state_on_prepare

    # ------------------------------------------------------------------
    # InferenceProvider — protocol surface
    # ------------------------------------------------------------------

    def is_local(self) -> bool:
        """Return True — Ollama inference is always on-device."""
        return True

    async def prepare(self) -> None:
        """Load the model, first unloading resident AlphaSwarm models when this provider
        was built with ``clean_state_on_prepare=True`` (the worker;
        docs/DECISIONS.md#adr-round-runner).

        When ``model_manager`` is ``None`` this is a safe no-op: the model lifecycle is
        the caller's responsibility.
        """
        if self._model_manager is None:
            logger.debug("prepare_skipped_no_manager", model=self.model)
            return
        if self.clean_state_on_prepare:
            await self._model_manager.ensure_clean_state()
        await self._model_manager.load_model(self.model)

    async def teardown(self) -> None:
        """Unload the model from Ollama memory via the model manager.

        When ``model_manager`` is ``None``, this is a safe no-op.
        """
        if self._model_manager is None:
            logger.debug("teardown_skipped_no_manager", model=self.model)
            return
        await self._model_manager.unload_model(self.model)

    async def aclose(self) -> None:
        """No-op — the OllamaClient lifecycle is owned by the caller."""

    async def chat(
        self,
        messages: list[InferenceMessage],
        *,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> InferenceResult:
        """Run chat completion via the local Ollama backend.

        Mapping rules (must mirror worker.py exactly):
        - ``response_schema`` → ``format=<schema dict>``   (structured output)
        - ``json_mode=True``  → ``format="json"``          (raw JSON, no schema)
        - neither             → ``format=None``
        - ``temperature``     → ``options={"temperature": <value>}`` or None
        - ``max_tokens``      → accepted but silently ignored (Modelfile
          ``num_predict`` governs; OllamaClient already strips ``num_ctx``)
        - ``think=False``     always (disables thinking for structured outputs)
        - ``keep_alive``      from constructor default (``"5m"``)

        Args:
            messages: Ordered conversation turns.
            response_schema: JSON Schema dict for structured-output decoding.
                Takes precedence over ``json_mode``.
            json_mode: Emit raw JSON without a schema constraint.
            temperature: Sampling temperature override; None uses Modelfile default.
            max_tokens: Accepted for interface compatibility; has no effect.

        Returns:
            ``InferenceResult`` with ``content``, ``model``, ``eval_count``,
            and ``eval_duration_ns`` populated.  ``input_tokens`` /
            ``output_tokens`` come from ``prompt_eval_count`` / ``eval_count``.
        """
        # Resolve format (schema wins over json_mode)
        if response_schema is not None:
            fmt: str | dict[str, Any] | None = response_schema
        elif json_mode:
            fmt = "json"
        else:
            fmt = None

        # Build options only when temperature is explicitly set.
        # Do NOT pass num_ctx — OllamaClient strips it, but omitting it
        # avoids a spurious log-warning on every single call.
        options: dict[str, Any] | None = {"temperature": temperature} if temperature is not None else None

        resp = await self._client.chat(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]  # dict[str,str] ≈ InferenceMessage
            format=fmt,
            think=False,
            keep_alive=self._keep_alive,
            options=options,
        )

        return InferenceResult(
            content=resp.message.content or "",
            model=self.model,
            # Token counts for telemetry and live TPS; local calls are never billed
            # (only cloud providers are wrapped by BudgetTrackingProvider).
            input_tokens=getattr(resp, "prompt_eval_count", None),
            output_tokens=getattr(resp, "eval_count", None),
        )
