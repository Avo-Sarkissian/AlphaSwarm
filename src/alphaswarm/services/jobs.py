"""Background orchestrator jobs (report, advisory): one at a time, recorded per cycle.

JobRunner keeps the task handles, records each job's state in the StateStore
(the single source of truth for "running", read by routes and by
SimulationManager), keeps per-cycle failure codes for GET 500s, owns the
orchestrator lock and cancels everything at shutdown
(docs/DECISIONS.md#adr-background-tasks, #adr-sequential-model-lifecycle).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.errors import AlphaSwarmError, InferenceConfigError
from alphaswarm.logging import validation_error_summary
from alphaswarm.state import JobKind, JobStatus

if TYPE_CHECKING:
    from alphaswarm.state import StateStore

__all__ = ["JOB_FAILURE_CODES", "JobInProgressError", "JobKind", "JobRunner"]

log = structlog.get_logger(component="services.jobs")

JOB_FAILURE_CODES: Final[dict[JobKind, str]] = {
    "report": "report_generation_failed",
    "advisory": "advisory_generation_failed",
}
INFERENCE_CONFIG_FAILURE_CODE: Final = "inference_config_invalid"
_KINDS: Final[tuple[JobKind, ...]] = ("report", "advisory")


class JobInProgressError(AlphaSwarmError):
    """Another orchestrator job holds the slot; ``kind`` names that job."""

    def __init__(self, kind: JobKind) -> None:
        super().__init__(f"A {kind} job is already using the orchestrator; retry when it finishes")
        self.kind: JobKind = kind

    @property
    def code(self) -> str:
        return f"{self.kind}_generation_in_progress"


def _failure_code(kind: JobKind, exc: BaseException | None) -> str:
    """The code GET reports for a failed *kind* job.

    A domain refusal keeps its own code so the UI can say why: an unusable
    inference config, or an AlphaSwarmError that declares a ``job_failure_code``
    string (a refused advisory gate). Anything else, and a cancellation, gets
    the per-kind code.
    """
    if isinstance(exc, InferenceConfigError):
        return INFERENCE_CONFIG_FAILURE_CODE
    if isinstance(exc, AlphaSwarmError):
        code = getattr(exc, "job_failure_code", None)
        if isinstance(code, str) and code:
            return code
    return JOB_FAILURE_CODES[kind]


class JobRunner:
    """Runs report/advisory jobs one at a time."""

    def __init__(self, state_store: StateStore) -> None:
        self._store = state_store
        self._lock = asyncio.Lock()
        self._tasks: dict[JobKind, asyncio.Task[None]] = {}
        self._failures: dict[tuple[JobKind, str], str] = {}

    @property
    def orchestrator_lock(self) -> asyncio.Lock:
        """Serialises orchestrator users inside this process (services take it around a call)."""
        return self._lock

    def status(self, kind: JobKind) -> JobStatus:
        jobs = self._store.job_statuses()
        return jobs.advisory if kind == "advisory" else jobs.report

    def running(self) -> JobKind | None:
        """The job kind currently marked running in the StateStore, if any."""
        for kind in _KINDS:
            if self.status(kind).state == "running":
                return kind
        return None

    def is_busy(self) -> bool:
        return self.running() is not None

    def error_for(self, kind: JobKind, cycle_id: str) -> str | None:
        """Failure code recorded for this cycle's last *kind* job, if it failed."""
        return self._failures.get((kind, cycle_id))

    def record_refusal(self, kind: JobKind, cycle_id: str, code: str) -> None:
        """Record that a *kind* job for *cycle_id* was refused before it started.

        GET then answers with *code* instead of 404 while the UI polls. A running
        job's status is left alone: the StateStore stays the truth about "running".
        """
        self._failures[(kind, cycle_id)] = code
        if self.status(kind).state != "running":
            self._store.set_job_status(kind, JobStatus("failed", cycle_id, code))
        log.info("job_refused", kind=kind, cycle_id=cycle_id, code=code)

    def start(
        self,
        kind: JobKind,
        cycle_id: str,
        factory: Callable[[], Awaitable[None]],
    ) -> asyncio.Task[None]:
        """Start *factory()* as the *kind* job for *cycle_id*.

        Raises JobInProgressError (synchronously, before anything starts) while
        another job runs.
        """
        blocker = self.running()
        if blocker is not None:
            raise JobInProgressError(blocker)
        self._failures.pop((kind, cycle_id), None)

        async def _run() -> None:
            # The task runs in a copied context, so this binding stays task-local
            # (docs/DECISIONS.md#adr-security-2026-08).
            structlog.contextvars.bind_contextvars(cycle_id=cycle_id, job=kind)
            await factory()

        task: asyncio.Task[None] = asyncio.create_task(_run(), name=f"{kind}_{cycle_id}")
        self._tasks[kind] = task
        self._store.set_job_status(kind, JobStatus("running", cycle_id))
        task.add_done_callback(lambda done: self._on_done(kind, cycle_id, done))
        log.info("job_started", kind=kind, cycle_id=cycle_id)
        return task

    def _on_done(self, kind: JobKind, cycle_id: str, task: asyncio.Task[None]) -> None:
        """Record the outcome; a done-callback must never raise."""
        try:
            if self._tasks.get(kind) is task:
                del self._tasks[kind]
            if task.cancelled():
                code = _failure_code(kind, None)
                self._failures[(kind, cycle_id)] = code
                self._store.set_job_status(kind, JobStatus("failed", cycle_id, code))
                log.warning("job_cancelled", kind=kind, cycle_id=cycle_id)
                return
            exc = task.exception()
            if exc is None:
                self._store.set_job_status(kind, JobStatus("idle", cycle_id))
                log.info("job_completed", kind=kind, cycle_id=cycle_id)
                return
            code = _failure_code(kind, exc)
            self._failures[(kind, cycle_id)] = code
            self._store.set_job_status(kind, JobStatus("failed", cycle_id, code))
            if kind == "advisory":
                # Advisory exceptions can echo tickers (pydantic, providers): class and
                # validation summary only (docs/DECISIONS.md#adr-holdings-isolation).
                log.error(
                    "job_failed",
                    kind=kind,
                    cycle_id=cycle_id,
                    exc_type=type(exc).__name__,
                    **validation_error_summary(exc),
                )
            else:
                log.error("job_failed", kind=kind, cycle_id=cycle_id, exc_info=exc)
        except Exception:
            log.exception("job_done_callback_failed", kind=kind, cycle_id=cycle_id)

    async def shutdown(self) -> None:
        """Cancel and await every running job (lifespan / CLI exit)."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
