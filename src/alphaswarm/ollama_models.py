"""Sequential model loading and unloading for Ollama.

Enforces the INFRA-03 contract: orchestrator model loads, unloads completely,
then worker model loads. No dual-model coexistence.

Uses an asyncio.Lock to serialize all model transitions, preventing race
conditions from concurrent async calls. Addresses review concern about
model transition serialization.
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
        self._current_model: str | None = None
        self._lock = asyncio.Lock()
        self._configured_aliases: set[str] = configured_aliases or set()

    @property
    def current_model(self) -> str | None:
        """Return the currently loaded model tag, or None."""
        return self._current_model

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
            self._current_model = model
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
            await self._client.chat(
                model=model,
                messages=[],
                keep_alive=0,
            )
            if self._current_model == model:
                self._current_model = None
            await logger.ainfo("model unloaded", model=model)

    async def is_model_loaded(self, model: str) -> bool:
        """Check if a model is currently loaded via ps().

        Args:
            model: Ollama model tag to check.

        Returns:
            True if model appears in ps() response.
        """
        ps_response = await self._client.raw_client.ps()
        loaded_names = [m.model for m in ps_response.models]
        return model in loaded_names

    async def ensure_clean_state(self) -> None:
        """Unload all AlphaSwarm-configured models currently loaded.

        Only unloads models whose tags are in self._configured_aliases.
        Does NOT unload unrelated models loaded by other Ollama users.
        Addresses review concern: ensure_clean_state was too broad.
        """
        ps_response = await self._client.raw_client.ps()
        for m in ps_response.models:
            if m.model in self._configured_aliases:
                await self.unload_model(m.model)
