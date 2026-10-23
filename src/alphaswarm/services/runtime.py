"""Runtime assembly shared by the CLI subcommands and the FastAPI lifespan.

``InferenceRuntime`` owns the cached inference config and builds providers per
operation (each with its own budget meter, the per-operation cap). Later in
this module: ``Runtime``, ``build_runtime``, ``open_runtime`` (the one
composition root) and ``open_simulation`` (docs/DECISIONS.md#adr-web-lifespan).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog

from alphaswarm.errors import (
    INFERENCE_CONFIG_INCOMPLETE_MESSAGE,
    INFERENCE_CONFIG_INVALID_MESSAGE,
    InferenceConfigError,
    InferenceConfigIncompleteError,
)

# Called through their modules so patch("alphaswarm.inference.factory.build_providers")
# style tests reach the runtime too.
from alphaswarm.inference import config as inference_config
from alphaswarm.inference import factory

if TYPE_CHECKING:
    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.config import InferenceConfig
    from alphaswarm.inference.factory import BuiltProviders
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.inference.types import ProviderRole
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.settings import AppSettings
    from alphaswarm.state import StateStore

log = structlog.get_logger(component="services.runtime")

OperationName = Literal["simulation", "inject", "report", "advisory", "interview", "settings_test"]


def _file_key(path: Path) -> tuple[int, int] | None:
    """``(mtime_ns, size)`` of *path*, or None when it cannot be stat'ed (e.g. missing)."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


class InferenceRuntime:
    """Cached inference config plus provider construction per operation.

    Error texts never carry the config path or values: the load error can
    quote the path, and the file holds API keys, so only the error type is
    logged and the fixed messages are raised ``from None``
    (docs/DECISIONS.md#adr-local-first-inference).
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        ollama_client: OllamaClient | None,
        model_manager: OllamaModelManager | None,
    ) -> None:
        self._settings = settings
        self._ollama_client = ollama_client
        self._model_manager = model_manager
        self._lock = asyncio.Lock()
        self._cached: InferenceConfig | None = None
        self._cache_key: tuple[int, int] | None = None
        self._last_meter: BudgetMeter | None = None

    @property
    def config_path(self) -> Path:
        """Absolute path of the stored inference config."""
        return self._settings.resolve_path(self._settings.inference_config_path)

    @property
    def last_meter(self) -> BudgetMeter | None:
        """Budget meter of the most recently opened operation (telemetry)."""
        return self._last_meter

    async def config(self) -> InferenceConfig:
        """The stored config (or local defaults), re-read when the file's mtime or size changes.

        Raises InferenceConfigError (fixed message, no path) when the file is
        invalid or unreadable.
        """
        async with self._lock:
            key = await asyncio.to_thread(_file_key, self.config_path)
            if self._cached is None or key != self._cache_key:
                try:
                    self._cached = await asyncio.to_thread(inference_config.load_inference_config, self._settings)
                except (ValueError, OSError) as exc:
                    log.error("inference_config_invalid", error_type=type(exc).__name__)
                    raise InferenceConfigError(INFERENCE_CONFIG_INVALID_MESSAGE) from None
                self._cache_key = key
            return self._cached

    async def mode(self) -> Literal["local", "cloud", "mixed"]:
        """``"local"``, ``"cloud"`` or ``"mixed"`` for the current config."""
        return factory.inference_mode(await self.config())

    async def open_operation(self, name: OperationName) -> BuiltProviders:
        """Both role providers for one operation, sharing a fresh budget meter."""
        cfg = await self.config()
        try:
            built = factory.build_providers(
                cfg,
                ollama_client=self._ollama_client,
                ollama_model_manager=self._model_manager,
            )
        except ValueError as exc:
            self._log_incomplete(cfg, exc, name)
            raise InferenceConfigIncompleteError(INFERENCE_CONFIG_INCOMPLETE_MESSAGE) from None
        self._last_meter = built.budget_meter
        log.info("inference_operation_opened", operation=name, mode=factory.inference_mode(cfg))
        return built

    async def open_role(self, role: ProviderRole, name: OperationName) -> InferenceProvider:
        """One role's provider only, so an incomplete other role does not block it (interviews use the worker)."""
        cfg = await self.config()
        try:
            provider = factory.build_role_provider(
                cfg,
                role,
                ollama_client=self._ollama_client,
                ollama_model_manager=self._model_manager,
            )
        except ValueError as exc:
            self._log_incomplete(cfg, exc, name)
            raise InferenceConfigIncompleteError(INFERENCE_CONFIG_INCOMPLETE_MESSAGE) from None
        log.info("inference_role_opened", operation=name, role=role.value)
        return provider

    async def build_controller(self, state_store: StateStore) -> ConcurrencyController:
        """ResourceGovernor for a local worker, RateLimitController for a cloud worker."""
        return factory.build_controller(await self.config(), self._settings.governor, state_store=state_store)

    @staticmethod
    def _log_incomplete(cfg: InferenceConfig, exc: ValueError, name: OperationName) -> None:
        # The config loads (the health check reports it ok), but a cloud role
        # lacks its API key or base URL: the fix is in Settings.
        log.error(
            "inference_config_incomplete",
            operation=name,
            error_type=type(exc).__name__,
            orchestrator_provider=cfg.orchestrator.provider.value,
            worker_provider=cfg.worker.provider.value,
        )
