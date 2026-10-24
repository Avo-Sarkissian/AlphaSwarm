"""Runtime assembly shared by the CLI subcommands and the FastAPI lifespan.

``InferenceRuntime`` owns the cached inference config and builds providers per
operation (each with its own budget meter, the per-operation cap). ``Runtime``
bundles it with the AppState and the JobRunner; ``build_runtime`` assembles one
without I/O, ``open_runtime`` is the one composition root and
``open_simulation`` yields one run's ``SimulationDeps``
(docs/DECISIONS.md#adr-web-lifespan).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import DriverError, Neo4jError

from alphaswarm.app import AppState, create_app_state
from alphaswarm.errors import (
    INFERENCE_CONFIG_INCOMPLETE_MESSAGE,
    INFERENCE_CONFIG_INVALID_MESSAGE,
    GraphError,
    InferenceConfigError,
    InferenceConfigIncompleteError,
    Neo4jUnavailableError,
)
from alphaswarm.governor import ResourceGovernor

# Called through their modules so patch("alphaswarm.inference.factory.build_providers")
# style tests reach the runtime too.
from alphaswarm.inference import config as inference_config
from alphaswarm.inference import factory
from alphaswarm.inference.retry import RetryGate
from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider
from alphaswarm.logging import configure_logging
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.readiness import NEO4J_AUTH_FIX, NEO4J_FIX
from alphaswarm.services.jobs import JobRunner
from alphaswarm.settings import AppSettings
from alphaswarm.telemetry import make_transition_probe

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.config import InferenceConfig
    from alphaswarm.inference.factory import BuiltProviders
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.inference.types import ProviderRole
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.simulation import SimulationDeps
    from alphaswarm.state import StateSink, StateStore

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
    def ollama_client(self) -> OllamaClient | None:
        """The shared OllamaClient (None without Ollama); the advisory gate reads its host."""
        return self._ollama_client

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
        """ResourceGovernor for a local worker, RateLimitController for a cloud worker.

        A governor gets the transition probe that logs loaded models and Docker VM
        memory on every state change (docs/DECISIONS.md#adr-inference-telemetry).
        """
        controller = factory.build_controller(await self.config(), self._settings.governor, state_store=state_store)
        if isinstance(controller, ResourceGovernor):
            loaded = self._model_manager.loaded_models if self._model_manager is not None else None
            controller.set_transition_probe(make_transition_probe(loaded))
        return controller

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


async def close_operation(built: BuiltProviders, *, teardown: bool) -> None:
    """Unload the orchestrator (when *teardown*) and close both providers' clients.

    Runs in every operation's ``finally`` (docs/DECISIONS.md#p15-d-12). Failures
    here are logged, never raised, so they cannot mask the operation's own result.
    """
    if teardown:
        try:
            await built.orchestrator.teardown()
        except Exception:
            log.warning("orchestrator_teardown_failed", exc_info=True)
    for provider in (built.orchestrator, built.worker):
        try:
            await provider.aclose()
        except Exception:
            log.warning("provider_close_failed", role=str(provider.role), exc_info=True)


@dataclass(frozen=True)
class Runtime:
    """Everything a CLI subcommand or the web app needs."""

    settings: AppSettings
    app_state: AppState
    inference: InferenceRuntime
    jobs: JobRunner
    neo4j_ready: bool


RuntimeFactory = Callable[[AppSettings], AbstractAsyncContextManager[Runtime]]


def build_runtime(
    settings: AppSettings,
    *,
    with_ollama: bool = True,
    with_neo4j: bool = True,
) -> Runtime:
    """Assemble the runtime without I/O (the Neo4j driver connects lazily).

    Market and news providers are built here for CLI and web alike, with the
    StateStore as their audit sink (docs/DECISIONS.md#p40-d-10).
    """
    personas = generate_personas(load_bracket_configs())
    app_state = create_app_state(settings, personas, with_ollama=with_ollama, with_neo4j=with_neo4j)
    market = YFinanceMarketDataProvider()
    news = RSSNewsProvider()
    market.attach_audit_sink(app_state.state_store)
    news.attach_audit_sink(app_state.state_store)
    app_state.market_provider = market
    app_state.news_provider = news
    inference = InferenceRuntime(
        settings,
        ollama_client=app_state.ollama_client,
        model_manager=app_state.model_manager,
    )
    return Runtime(
        settings=settings,
        app_state=app_state,
        inference=inference,
        jobs=JobRunner(app_state.state_store),
        neo4j_ready=False,
    )


def _neo4j_fix(exc: BaseException) -> str:
    """The operator's fix for a startup failure (the text /api/health shows): credentials or a stopped server."""
    cause = getattr(exc, "original_error", None)  # GraphError keeps the driver error
    auth = isinstance(exc, Neo4jAuthError) or isinstance(cause, Neo4jAuthError)
    return NEO4J_AUTH_FIX if auth else NEO4J_FIX


async def _prepare_graph(graph: GraphStateManager) -> bool:
    """Verify Neo4j, then apply the idempotent schema; return readiness.

    ensure_schema() also seeds the Agent nodes every write MATCHes
    (docs/DECISIONS.md#p4-d-05). A down or misconfigured database never stops
    startup: one ``neo4j_unavailable_at_startup`` warning names the fix and the
    runtime reports ``neo4j_ready=False``; once the database answers,
    /api/health applies the schema. Living here gives the CLI and the web
    lifespan the same check.
    """
    try:
        await graph.verify_connectivity()
        await graph.ensure_schema()
    except (GraphError, DriverError, Neo4jError) as exc:
        # GraphStateManager maps driver, auth and server errors (docs/DECISIONS.md#p4-d-07);
        # the raw driver errors are caught too, so an unmapped path still degrades.
        log.warning(
            "neo4j_unavailable_at_startup",
            error_type=type(exc).__name__,
            op=getattr(exc, "op", None),
            fix=_neo4j_fix(exc),
        )
        return False
    log.info("neo4j_schema_ready")
    return True


@asynccontextmanager
async def open_runtime(
    settings: AppSettings,
    *,
    with_ollama: bool = True,
    with_neo4j: bool = True,
    apply_schema: bool = True,
) -> AsyncIterator[Runtime]:
    """The one composition root for the CLI and the web lifespan.

    Enter: configure logging (the redacting structlog bridge,
    docs/DECISIONS.md#adr-security-2026-08), build the runtime, verify Neo4j and
    apply the schema (an unreachable database is logged and reported as
    ``neo4j_ready=False``). Exit, in this order, even when the body raises:
    cancel jobs, close the Ollama HTTP pool, close the Neo4j driver
    (docs/DECISIONS.md#adr-web-lifespan).
    """
    configure_logging(log_level=settings.log_level, json_output=not settings.debug)
    runtime = build_runtime(settings, with_ollama=with_ollama, with_neo4j=with_neo4j)
    async with AsyncExitStack() as stack:
        graph = runtime.app_state.graph_manager
        if graph is not None:
            stack.push_async_callback(graph.close)
        client = runtime.app_state.ollama_client
        if client is not None:
            stack.push_async_callback(client.aclose)
        stack.push_async_callback(runtime.jobs.shutdown)
        ready = await _prepare_graph(graph) if graph is not None and apply_schema else False
        log.info("runtime_opened", neo4j_ready=ready, with_ollama=with_ollama, with_neo4j=with_neo4j)
        yield dataclasses.replace(runtime, neo4j_ready=ready)
    log.info("runtime_closed")


@asynccontextmanager
async def open_simulation(
    inference: InferenceRuntime,
    app_state: AppState,
    *,
    state: StateSink | None,
) -> AsyncIterator[SimulationDeps]:
    """``SimulationDeps`` for one run; providers are closed (not torn down) afterwards.

    ``run_simulation`` owns prepare/teardown of both models (docs/DECISIONS.md#adr-round-runner).
    Raises Neo4jUnavailableError when this process has no graph.
    """
    # Imported here so this module stays importable without loading the engine.
    from alphaswarm.simulation import SimulationDeps

    graph = app_state.graph_manager
    if graph is None:
        raise Neo4jUnavailableError("Neo4j is not configured for this process", op="open_simulation")
    built = await inference.open_operation("simulation")
    try:
        controller = await inference.build_controller(app_state.state_store)
        if isinstance(controller, RetryGate):
            # Cloud worker: retries share the controller's cooldown and RPM bucket
            # (docs/DECISIONS.md#adr-cloud-retry).
            factory.attach_retry_gate(built, await inference.config(), controller)
        yield SimulationDeps(
            settings=app_state.settings,
            graph=graph,
            controller=controller,
            orchestrator=built.orchestrator,
            worker=built.worker,
            state=state,
            market=app_state.market_provider,
            news=app_state.news_provider,
        )
    finally:
        await close_operation(built, teardown=False)
