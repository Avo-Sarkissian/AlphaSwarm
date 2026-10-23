"""Ollama model loading and unloading.

Rounds never run with the orchestrator and the worker loaded together: seeding loads
and unloads the orchestrator, then the worker is loaded once for every round
(docs/DECISIONS.md#adr-round-runner). Ollama itself may hold up to two models
(CLAUDE.md constraint 2), for example an interview's worker next to a report's
orchestrator.

Uses an asyncio.Lock to serialize all model transitions, preventing race
conditions from concurrent async calls.
"""

from __future__ import annotations

import asyncio

import structlog

from alphaswarm.errors import ModelLoadError
from alphaswarm.ollama_client import OllamaClient

logger = structlog.get_logger(component="ollama_models")


class OllamaModelManager:
    """Manages sequential model loading and unloading.

    Uses keep_alive=0 for unloading (NOT delete, which removes files permanently).
    Uses ps() to verify model state transitions.
    Uses asyncio.Lock to serialize concurrent load/unload requests.

    Args:
        client: OllamaClient wrapper for Ollama calls.
        configured_aliases: Set of model tags that AlphaSwarm manages.
            ensure_clean_state() only unloads these, not unrelated models.

    Usage:
        manager = OllamaModelManager(client, {"alphaswarm-orchestrator", "alphaswarm-worker"})
        await manager.load_model("alphaswarm-orchestrator")
        # ... use model ...
        await manager.unload_model("alphaswarm-orchestrator")
        await manager.load_model("alphaswarm-worker")
    """

    def __init__(
        self,
        client: OllamaClient,
        configured_aliases: set[str] | None = None,
    ) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self._configured_aliases: set[str] = configured_aliases or set()

    async def load_model(self, model: str) -> None:
        """Load a model into Ollama memory.

        Sends a minimal chat request to trigger model loading, then
        verifies via ps() that the model is actually loaded.
        Serialized by internal Lock to prevent concurrent load/unload races.

        Args:
            model: Ollama model tag (e.g., "alphaswarm-orchestrator").

        Raises:
            ModelLoadError: If the model fails to load or ps() does not
                show the model as loaded after the load attempt.
        """
        async with self._lock:
            await logger.ainfo("loading model", model=model)
            try:
                await self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    keep_alive="5m",
                )
            except Exception as exc:
                raise ModelLoadError(
                    message=f"Failed to load model {model}: {exc}",
                    model=model,
                    original_error=exc if isinstance(exc, Exception) else None,
                ) from exc

            if not await self.is_model_loaded(model):
                raise ModelLoadError(
                    message=f"Model {model} not found in ps() after load attempt",
                    model=model,
                )
            await logger.ainfo("model loaded", model=model)

    async def unload_model(self, model: str) -> None:
        """Unload a model from Ollama memory via keep_alive=0.

        Does NOT delete the model files. Uses keep_alive=0 on an empty
        chat request to signal Ollama to unload from memory.
        Serialized by internal Lock.

        Args:
            model: Ollama model tag to unload.
        """
        async with self._lock:
            await logger.ainfo("unloading model", model=model)
            try:
                await self._client.chat(
                    model=model,
                    messages=[],
                    keep_alive=0,
                )
                await logger.ainfo("model unloaded", model=model)
            except Exception:
                # Best-effort unload: some Ollama builds reject an empty messages
                # list, and a failed unload must not abort the caller
                # (ensure_clean_state loops over models; docs/DECISIONS.md#f-32).
                await logger.awarning("unload_model_failed", model=model, exc_info=True)

    async def is_model_loaded(self, model: str) -> bool:
        """Check if a model is currently loaded via ps().

        Args:
            model: Ollama model tag to check.

        Returns:
            True if model appears in ps() response.
        """
        ps_response = await self._client.raw_client.ps()

        # Normalize comparison: Ollama ps() returns "model:latest" but callers
        # pass bare "model". Strip ":latest" suffix for matching.
        def _bare(name: str) -> str:
            return name.removesuffix(":latest")

        loaded_bare = [_bare(m.model) for m in ps_response.models if m.model is not None]
        return _bare(model) in loaded_bare

    async def ensure_clean_state(self) -> None:
        """Unload all AlphaSwarm-configured models currently loaded.

        Only unloads models whose tags are in self._configured_aliases.
        Does NOT unload unrelated models loaded by other Ollama users.
        Addresses review concern: ensure_clean_state was too broad.

        Best-effort on the ``ps()` probe: in a pure-cloud run (both roles on a
        cloud provider) the Ollama daemon may not be running at all. This method
        is called unconditionally at simulation start, so a hard failure here
        would abort an otherwise all-cloud run before any cloud call is made.
        If the daemon is unreachable there is nothing local to clean, so we log
        and return rather than propagate the connection error.
        """
        try:
            ps_response = await self._client.raw_client.ps()
        except Exception as exc:  # noqa: BLE001 — best-effort; cloud runs may have no Ollama
            logger.warning(
                "ensure_clean_state_skipped",
                reason="ollama_ps_unavailable",
                error=str(exc),
            )
            return
        bare_aliases = {a.removesuffix(":latest") for a in self._configured_aliases}
        for m in ps_response.models:
            name = m.model
            if name is None:
                continue
            if name.removesuffix(":latest") in bare_aliases:
                # unload_model is best-effort (it swallows its own errors), so one
                # stuck model can't abort the loop and leave the rest resident,
                # preserving the max-2-models invariant (docs/DECISIONS.md#f-32).
                await self.unload_model(name)
