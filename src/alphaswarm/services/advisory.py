"""AdvisoryService: the only service that touches holdings.

Import-linter lets this module import ``alphaswarm.advisory`` and
``alphaswarm.holdings.types`` (two explicit ``ignore_imports`` edges) and
nothing else from holdings; the portfolio arrives through an injected callable
(``PortfolioCache.get`` in the web app). Holdings never reach logs, Neo4j or
WebSocket frames (docs/DECISIONS.md#adr-holdings-isolation).

The advisory runs only for a local orchestrator or with the cloud opt-in. The
config check comes before the holdings are read, and ``generate`` repeats it
under the orchestrator lock, then asks the Ollama server whether the model runs
remotely (docs/DECISIONS.md#adr-advisory-pipeline).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Final, Literal, Protocol

import structlog

from alphaswarm.advisory import AdvisoryReport, synthesize
from alphaswarm.advisory.sector_map import load_sector_map
from alphaswarm.errors import AlphaSwarmError
from alphaswarm.fsutil import atomic_write_text, prune_old_files
from alphaswarm.inference.config import ProviderType
from alphaswarm.inference.factory import advisory_block_reason
from alphaswarm.logging import validation_error_summary
from alphaswarm.services.runtime import close_operation

if TYPE_CHECKING:
    from pathlib import Path

    from alphaswarm.advisory.sector_map import SectorMap
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.holdings.types import PortfolioSnapshot
    from alphaswarm.inference.config import InferenceConfig
    from alphaswarm.services.jobs import JobRunner
    from alphaswarm.services.runtime import InferenceRuntime

log = structlog.get_logger(component="services.advisory")

Blocked = Literal["no_portfolio", "cloud_advisory_disabled"]
# Same literal as the post-run pipeline's AdvisoryGate; not imported from there,
# because the pipeline's wiring imports this module.
Gate = Literal["run", "no_portfolio", "cloud_advisory_disabled"]

NO_PORTFOLIO_MESSAGE: Final = "No holdings are loaded, so there is nothing to advise on"
CLOUD_ADVISORY_MESSAGE: Final = (
    "Advisory is disabled while the orchestrator is a cloud or remote model (a cloud "
    "provider, an Ollama cloud model, or an Ollama server off this machine: check the "
    "Ollama base URL, OLLAMA_HOST, and the orchestrator's base_url in the inference "
    "config), so the portfolio stays on this machine. Switch the orchestrator to a local "
    "Ollama model on localhost, or opt in: tick 'Allow cloud advisory' in Settings > Model, "
    "or set allow_cloud_advisory to true in the inference config when the checkbox is not "
    "shown."
)
MODEL_CHECK_FAILED_MESSAGE: Final = (
    "Advisory is disabled because the Ollama server could not confirm that the "
    "orchestrator model runs on this machine (its /api/show request failed). Make sure "
    "Ollama is running and the model exists, or set allow_cloud_advisory to true in the "
    "inference config to opt in."
)


class PortfolioSource(Protocol):
    """Anything with ``async get() -> PortfolioSnapshot | None`` (``PortfolioCache``)."""

    async def get(self) -> PortfolioSnapshot | None: ...


class AdvisoryNotAllowedError(AlphaSwarmError):
    """The advisory may not run now: no holdings, or a cloud or remote orchestrator without the opt-in.

    Messages are fixed text, safe to return over HTTP; ``job_failure_code`` lets
    JobRunner record the gate as the job's failure code.
    """

    def __init__(self, gate: Blocked, message: str | None = None) -> None:
        if message is None:
            message = NO_PORTFOLIO_MESSAGE if gate == "no_portfolio" else CLOUD_ADVISORY_MESSAGE
        super().__init__(message)
        self.gate: Blocked = gate

    @property
    def job_failure_code(self) -> str:
        return self.gate


class AdvisoryService:
    """Synthesises advisories into ``advisory_dir``."""

    def __init__(
        self,
        *,
        graph: GraphStateManager,
        inference: InferenceRuntime,
        jobs: JobRunner,
        advisory_dir: Path,
        portfolio: Callable[[], Awaitable[PortfolioSnapshot | None]],
        keep_last: int = 20,
        sector_map_path: Path | None = None,
    ) -> None:
        self._graph = graph
        self._inference = inference
        self._jobs = jobs
        self._advisory_dir = advisory_dir
        self._portfolio = portfolio
        self._keep_last = keep_last
        self._sector_map_path = sector_map_path

    @property
    def advisory_dir(self) -> Path:
        return self._advisory_dir

    @property
    def jobs(self) -> JobRunner:
        """The JobRunner this service starts its jobs on (refusals are recorded there)."""
        return self._jobs

    async def gate(self, cycle_id: str) -> Gate:
        """Whether the advisory may run now for *cycle_id*.

        Raises InferenceConfigError when the stored config is unusable (fails closed).
        """
        blocked, _cfg, _snapshot = await self._check(cycle_id)
        result: Gate = "run" if blocked is None else blocked
        log.info("advisory_gate_checked", cycle_id=cycle_id, gate=result)
        return result

    async def _check(self, cycle_id: str) -> tuple[Blocked | None, InferenceConfig, PortfolioSnapshot | None]:
        """The orchestrator first, then the holdings, so a refused config never reads them."""
        cfg = await self._inference.config()
        reason = self._block_reason(cfg)
        if reason is not None:
            log.warning("advisory_blocked_cloud_disabled", cycle_id=cycle_id, reason=reason)
            return "cloud_advisory_disabled", cfg, None
        snapshot = await self._portfolio()
        if snapshot is None or not snapshot.holdings:
            return "no_portfolio", cfg, None
        return None, cfg, snapshot

    def _block_reason(self, cfg: InferenceConfig) -> str | None:
        """advisory_block_reason() against the host the shared OllamaClient connects to.

        The host is read from the client itself, so the check and the connection
        cannot disagree. Without a client only the opt-in passes (fails closed).
        """
        client = self._inference.ollama_client
        if client is None:
            return None if cfg.allow_cloud_advisory else "ollama_client_missing"
        return advisory_block_reason(cfg, ollama_base_url=client.base_url)

    async def _refuse_remote_ollama_model(self, cfg: InferenceConfig, cycle_id: str) -> None:
        """Ask the Ollama server whether the orchestrator model runs remotely; any failure refuses.

        A name check cannot see an alias whose Modelfile is ``FROM`` a cloud
        model (the default ``alphaswarm-orchestrator`` is such an alias).
        """
        if cfg.allow_cloud_advisory or cfg.orchestrator.provider != ProviderType.OLLAMA:
            return
        client = self._inference.ollama_client
        assert client is not None  # _block_reason refused a missing client without the opt-in
        try:
            remote = await client.is_remote_model(cfg.orchestrator.model)
        except Exception as exc:
            log.warning("advisory_blocked_model_check_failed", cycle_id=cycle_id, error_type=type(exc).__name__)
            raise AdvisoryNotAllowedError("cloud_advisory_disabled", MODEL_CHECK_FAILED_MESSAGE) from None
        if remote:
            log.warning("advisory_blocked_cloud_disabled", cycle_id=cycle_id, reason="remote_model")
            raise AdvisoryNotAllowedError("cloud_advisory_disabled")

    async def _load_sector_map(self) -> SectorMap | None:
        # Read per run, so edits to the local map apply without a restart; the
        # loader never raises (missing: fictional example, invalid: empty map).
        if self._sector_map_path is None:
            return None
        return await asyncio.to_thread(load_sector_map, self._sector_map_path)

    async def generate(self, cycle_id: str) -> AdvisoryReport:
        """Synthesise, then write ``{cycle_id}_advisory.json`` (0600) and prune old files.

        The gate is re-checked under the orchestrator lock, right before any
        provider is built: Settings may have switched to a cloud orchestrator
        while the job waited (docs/DECISIONS.md#adr-advisory-pipeline).
        """
        async with self._jobs.orchestrator_lock:
            blocked, cfg, snapshot = await self._check(cycle_id)
            if blocked is not None:
                raise AdvisoryNotAllowedError(blocked)
            assert snapshot is not None  # _check returns a snapshot whenever nothing blocks
            await self._refuse_remote_ollama_model(cfg, cycle_id)
            sector_map = await self._load_sector_map()
            path = self._advisory_dir / f"{cycle_id}_advisory.json"
            try:
                built = await self._inference.open_operation("advisory")
                try:
                    await built.orchestrator.prepare()
                    report = await synthesize(
                        cycle_id=cycle_id,
                        portfolio=snapshot,
                        graph_manager=self._graph,
                        provider=built.orchestrator,
                        sector_map=sector_map,
                    )
                finally:
                    await close_operation(built, teardown=True)
                await asyncio.to_thread(atomic_write_text, path, report.model_dump_json(indent=2))
            except Exception as exc:
                # Class and validation summary only, never str(exc) or a traceback:
                # advisory exceptions can echo holdings (docs/DECISIONS.md#adr-holdings-isolation).
                log.error(
                    "advisory_generation_failed",
                    cycle_id=cycle_id,
                    exc_type=type(exc).__name__,
                    **validation_error_summary(exc),
                )
                raise
        await self._prune(cycle_id)
        log.info(
            "advisory_written",
            cycle_id=cycle_id,
            total=report.total_holdings,
            affected=report.affected_holdings,
        )
        return report

    async def _prune(self, cycle_id: str) -> None:
        """Keep the newest ``keep_last`` advisory files; a failed prune never fails the advisory."""
        try:
            pruned = await asyncio.to_thread(
                prune_old_files,
                self._advisory_dir,
                "*_advisory.json",
                keep=self._keep_last,
            )
        except OSError as exc:
            log.warning("advisory_prune_failed", cycle_id=cycle_id, error_type=type(exc).__name__)
            return
        if pruned:
            log.info("advisory_files_pruned", cycle_id=cycle_id, count=len(pruned))

    def start(self, cycle_id: str) -> asyncio.Task[None]:
        """Run ``generate`` as the background advisory job (JobInProgressError when busy)."""

        async def _job() -> None:
            await self.generate(cycle_id)

        return self._jobs.start("advisory", cycle_id, _job)
