"""Serialized, verified model loading and unloading for Ollama.

Every load and unload goes through one asyncio.Lock and is checked with ps():
a load must appear, an unload must disappear (polled every 0.25 s for up to
30 s, then a warning). Load and unload times are logged in ms.

Rounds never run with the orchestrator and the worker loaded together: seeding loads
and unloads the orchestrator, then the worker is loaded once for every round
(docs/DECISIONS.md#adr-round-runner). Ollama itself may hold up to two models
(CLAUDE.md constraint 2), for example an interview's worker next to a report's
orchestrator.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

import structlog

from alphaswarm.errors import ModelLoadError
from alphaswarm.ollama_client import OllamaClient

logger = structlog.get_logger(component="ollama_models")

# Warm-up request sent by every load (docs/DECISIONS.md#adr-inference-timeouts): a
# short realistic prompt (some Ollama builds reject an empty messages list),
# reasoning off and one output token. It pays model load and MLX kernel
# compilation, so it runs on the long orchestrator read timeout.
WARMUP_PROMPT: Final = (
    "You are a market analyst. Answer in one word: is the headline "
    "'Company beats quarterly earnings estimates' bullish or bearish?"
)
WARMUP_OPTIONS: Final[Mapping[str, int]] = MappingProxyType({"num_predict": 1})
# A warm-up prefill rate below this suggests the llama.cpp fallback instead of MLX
# (benchmarks: worker 2,361 t/s, orchestrator 3,395 t/s; docs/DECISIONS.md#adr-model-stack).
WARMUP_SLOW_PREFILL_TPS: Final = 200.0


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def warmup_stats(response: object, wall_seconds: float) -> dict[str, float | int | None]:
    """Wall time, load time, prompt size and prefill rate of one warm-up reply."""
    prompt_tokens = _count(getattr(response, "prompt_eval_count", None))
    prefill_ns = _count(getattr(response, "prompt_eval_duration", None))
    load_ns = _count(getattr(response, "load_duration", None))
    prefill_tps = round(prompt_tokens / (prefill_ns / 1e9), 1) if prompt_tokens and prefill_ns else None
    return {
        "warmup_ms": round(wall_seconds * 1000, 1),
        "load_ms": None if load_ns is None else round(load_ns / 1e6, 1),
        "prompt_tokens": prompt_tokens,
        "prefill_tps": prefill_tps,
    }


async def _log_warmup(model: str, stats: Mapping[str, float | int | None]) -> None:
    await logger.ainfo("model_warmed", model=model, **stats)
    rate = stats["prefill_tps"]
    if isinstance(rate, float) and rate < WARMUP_SLOW_PREFILL_TPS:
        await logger.awarning(
            "model_warmup_slow",
            model=model,
            prefill_tps=rate,
            threshold_tps=WARMUP_SLOW_PREFILL_TPS,
            hint="check OLLAMA_USE_MLX on the Ollama server (docs/RUNBOOK.md section 1)",
        )


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
        *,
        unload_timeout_s: float = 30.0,
        poll_interval_s: float = 0.25,
    ) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self._configured_aliases: set[str] = configured_aliases or set()
        self._unload_timeout_s = unload_timeout_s
        self._poll_interval_s = poll_interval_s

    async def load_model(self, model: str) -> None:
        """Load a model into Ollama memory.

        Sends a short warm-up request (reasoning off, one output token, long read
        timeout) that loads the model, logs its load time and prefill rate, then
        verifies via ps() that the model is loaded.
        Serialized by internal Lock to prevent concurrent load/unload races.

        Args:
            model: Ollama model tag (e.g., "alphaswarm-orchestrator").

        Raises:
            ModelLoadError: If the model fails to load or ps() does not
                show the model as loaded after the load attempt.
        """
        async with self._lock:
            await logger.ainfo("loading model", model=model)
            started = time.monotonic()
            try:
                response = await self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": WARMUP_PROMPT}],
                    think=False,
                    keep_alive="5m",
                    options=dict(WARMUP_OPTIONS),
                    timeout_role="orchestrator",
                )
            except Exception as exc:
                raise ModelLoadError(
                    message=f"Failed to load model {model}: {exc}",
                    model=model,
                    original_error=exc if isinstance(exc, Exception) else None,
                ) from exc
            await _log_warmup(model, warmup_stats(response, time.monotonic() - started))

            if not await self.is_model_loaded(model):
                raise ModelLoadError(
                    message=f"Model {model} not found in ps() after load attempt",
                    model=model,
                )
            await logger.ainfo("model_loaded", model=model, load_ms=round((time.monotonic() - started) * 1000))

    async def unload_model(self, model: str) -> None:
        """Unload via keep_alive=0, then poll ps() until the model is gone.

        Does NOT delete the model files. Ollama acknowledges keep_alive=0 before
        it frees the weights, so the next load could otherwise overlap this
        model. A failed or unverified unload is logged and never aborts the
        caller (ensure_clean_state loops over models; docs/DECISIONS.md#f-32).
        """
        async with self._lock:
            started = time.monotonic()
            await logger.ainfo("model_unload_requested", model=model)
            try:
                await self._client.chat(model=model, messages=[], keep_alive=0)
            except Exception:
                # Some Ollama builds reject an empty messages list.
                await logger.awarning("unload_model_failed", model=model, exc_info=True)
                return
            gone = await self._wait_until_unloaded(model, started)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            if gone:
                await logger.ainfo("model_unloaded", model=model, unload_ms=elapsed_ms)
            else:
                await logger.awarning(
                    "model_unload_unverified",
                    model=model,
                    waited_ms=elapsed_ms,
                    timeout_s=self._unload_timeout_s,
                )

    async def _wait_until_unloaded(self, model: str, started: float) -> bool:
        deadline = started + self._unload_timeout_s
        while True:
            try:
                if not await self.is_model_loaded(model):
                    return True
            except Exception:
                await logger.awarning("model_unload_check_failed", model=model, exc_info=True)
                return False
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self._poll_interval_s)

    async def loaded_models(self) -> list[str]:
        """Sorted names of every model Ollama holds in memory, AlphaSwarm's or not."""
        ps_response = await self._client.raw_client.ps()
        # ProcessResponse.Model.model is Optional[str] in ollama-python 0.6.
        return sorted(m.model for m in ps_response.models if m.model)

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

        Only the Ollama worker provider calls this, from ``prepare()`` right before
        it loads the worker (docs/DECISIONS.md#adr-round-runner); a cloud worker
        never does. The ``ps()`` probe is best-effort: if the daemon is unreachable
        there is nothing local to clean, so this logs and returns, and the
        ``load_model()`` that follows reports the failure as a ``ModelLoadError``.
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
