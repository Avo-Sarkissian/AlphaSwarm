"""ResourceGovernor: memory-aware concurrency limiter for the local (Ollama) path.

One limiter guards every slot: ``_limit``, ``_in_use``, ``_paused`` and
``_fatal``. Waiters re-check the whole predicate after every notify, so a pause,
a resize or a fatal monitor error reaches agents that are already queued
(docs/DECISIONS.md#adr-governor). The monitor loop reads a MemoryReader every
``check_interval_seconds`` and drives a 5-state machine: RUNNING, THROTTLED,
PAUSED, CRISIS, RECOVERING.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.errors import GovernorCrisisError
from alphaswarm.memory_monitor import MemoryMonitor, MemoryReader, MemoryReading
from alphaswarm.settings import GovernorSettings
from alphaswarm.types import GovernorTelemetryState

if TYPE_CHECKING:
    from types import TracebackType

    from alphaswarm.state import StateStore

log = structlog.get_logger(component="governor")

# Clock for the time-in-state bookkeeping only; tests replace it. The crisis
# timeout keeps calling time.monotonic() directly.
_clock: Callable[[], float] = time.monotonic

# Context logged on each state change: loaded models and Docker VM memory
# (docs/DECISIONS.md#adr-inference-telemetry).
TransitionProbe = Callable[[], Awaitable[Mapping[str, object]]]
_TRANSITION_PROBE_TIMEOUT_SECONDS: Final = 1.0


# ---------------------------------------------------------------------------
# GovernorState enum
# ---------------------------------------------------------------------------


class GovernorState(enum.StrEnum):
    """State machine states for ResourceGovernor."""

    RUNNING = "running"
    THROTTLED = "throttled"
    PAUSED = "paused"
    CRISIS = "crisis"
    RECOVERING = "recovering"


# States whose duration is reported in the cycle metrics (docs/DECISIONS.md#adr-inference-telemetry).
_TRACKED_STATES: Final[Mapping[GovernorState, GovernorTelemetryState]] = {
    GovernorState.THROTTLED: "throttled",
    GovernorState.PAUSED: "paused",
    GovernorState.CRISIS: "crisis",
}


def _zero_time_in_state() -> dict[GovernorTelemetryState, float]:
    return {"throttled": 0.0, "paused": 0.0, "crisis": 0.0}


# ---------------------------------------------------------------------------
# ResourceGovernor
# ---------------------------------------------------------------------------


class ResourceGovernor:
    """Memory-aware concurrency limiter for the local path (docs/DECISIONS.md#adr-governor).

    Reads a MemoryReader (the macOS kernel signal by default) and adjusts one slot
    limiter through a 5-state machine: RUNNING, THROTTLED, PAUSED, CRISIS,
    RECOVERING.

    Constructor:
        ResourceGovernor(settings=None, *, state_store=None, monitor=None)
    ``monitor`` defaults to ``MemoryMonitor(settings)``; tests pass a scripted reader.
    """

    def __init__(
        self,
        settings: GovernorSettings | None = None,
        *,
        state_store: StateStore | None = None,
        monitor: MemoryReader | None = None,
    ) -> None:
        if settings is None:
            settings = GovernorSettings()
        self._settings = settings
        self._monitor: MemoryReader = monitor if monitor is not None else MemoryMonitor(settings)
        self._state = GovernorState.RUNNING
        self._state_store = state_store
        # Limiter: one predicate every waiter re-checks after each notify
        # (docs/DECISIONS.md#adr-governor).
        self._limit = settings.baseline_parallel
        self._in_use = 0
        self._paused = False
        self._fatal: GovernorCrisisError | None = None
        self._fatal_delivered = False
        self._changed = asyncio.Event()
        # State machine.
        self._last_successful_inference = time.monotonic()
        self._crisis_start: float | None = None
        self._paused_since: float | None = None
        self._consecutive_green_checks = 0
        self._adjustment_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task[None] | None = None
        # Rolling-window failure accounting (docs/DECISIONS.md#p3-d-04).
        self._outcomes: deque[bool] = deque(maxlen=settings.failure_window_size)
        self._consecutive_successes = 0
        self._failure_debt = 0
        # Per-session telemetry: seconds per tracked state and peak memory.
        self._time_in_state: dict[GovernorTelemetryState, float] = _zero_time_in_state()
        self._peak_memory_percent = 0.0
        self._state_entered_at = _clock()
        self._transition_probe: TransitionProbe | None = None

    # --- Public API ---

    async def acquire(self) -> None:
        """Claim a slot; wait while PAUSED/CRISIS or while every slot is in use.

        Raises GovernorCrisisError once the monitor has failed or aborted; every
        waiter sees it, including those already queued.
        """
        while True:
            self._absorb_monitor_failure()
            if self._fatal is not None:
                self._fatal_delivered = True
                fatal = self._fatal
                # Each waiter gets its own instance (a shared one would collect
                # every waiter's traceback), chained to the original cause.
                cause = fatal.__cause__ if fatal.__cause__ is not None else fatal
                raise GovernorCrisisError(str(fatal), duration_seconds=fatal.duration_seconds) from cause
            if not self._paused and self._in_use < self._limit:
                self._in_use += 1
                return
            await self._changed.wait()

    def release(self, *, success: bool = True, result_tokens: int | None = None) -> None:
        """Return a slot; count the outcome; a success resets the crisis clock.

        Crisis clock: docs/DECISIONS.md#p3-d-08. ``result_tokens`` exists for the
        ConcurrencyController protocol; the local governor ignores it.
        """
        self._in_use = max(0, self._in_use - 1)
        if success:
            self._last_successful_inference = time.monotonic()
        self._record_outcome(success)
        self._notify()

    async def start_monitoring(self) -> None:
        """Start background memory monitoring loop."""
        if self._monitor_task is None or self._monitor_task.done():
            self._reset_telemetry()
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            self._monitor_task.add_done_callback(self._on_monitor_done)

    def _on_monitor_done(self, task: asyncio.Task[None]) -> None:
        """Done callback: a dead monitor becomes a fatal error every waiter sees."""
        self._absorb_monitor_failure(task)

    async def stop_monitoring(self) -> None:
        """Stop the monitor, reset for the next session, surface an unseen fatal error.

        A fatal monitor error that no acquire() delivered (for example the monitor
        died while every agent was already running) is re-raised here, so a crisis
        abort is never lost. When another exception is already propagating (a
        cancellation or a hard stop reaching a ``finally``), the error is logged
        instead, so it never masks that exception.
        """
        task = self._monitor_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._absorb_monitor_failure(task)
        fatal, delivered = self._fatal, self._fatal_delivered
        self._monitor_task = None
        # Freeze this session's time-in-state totals before the state resets to
        # RUNNING (docs/DECISIONS.md#adr-inference-telemetry).
        self._close_state_interval(self._state, _clock())
        self._reset_session()
        if fatal is None or delivered:
            return
        if sys.exception() is not None:
            log.error(
                "governor_fatal_error_suppressed",
                error=str(fatal),
                reason="another exception is already propagating",
            )
            return
        raise fatal

    def time_in_state(self) -> dict[GovernorTelemetryState, float]:
        """Seconds THROTTLED, PAUSED and CRISIS in this (or the last) monitoring session."""
        totals = dict(self._time_in_state)
        tracked = _TRACKED_STATES.get(self._state)
        if tracked is not None:
            totals[tracked] += max(0.0, _clock() - self._state_entered_at)
        return totals

    @property
    def peak_memory_percent(self) -> float:
        """Highest memory percent read in this (or the last) monitoring session."""
        return self._peak_memory_percent

    def set_transition_probe(self, probe: TransitionProbe | None) -> None:
        """Context gathered and logged on every state change (docs/DECISIONS.md#adr-inference-telemetry)."""
        self._transition_probe = probe

    @property
    def transition_probe(self) -> TransitionProbe | None:
        """The probe set by the composition root, if any."""
        return self._transition_probe

    async def _log_transition_context(self, old: GovernorState, new: GovernorState, reading: MemoryReading) -> None:
        if self._transition_probe is None:
            return
        try:
            # asyncio.timeout, not wait_for: on Python 3.11 wait_for can swallow a
            # cancellation that arrives as the probe finishes, and stop_monitoring()
            # would then wait forever on a monitor task that never stops.
            async with asyncio.timeout(_TRANSITION_PROBE_TIMEOUT_SECONDS):
                context = await self._transition_probe()
        except Exception:  # observability never stops monitoring (docs/DECISIONS.md#f-21)
            log.warning(
                "governor_transition_probe_failed",
                old_state=old.value,
                new_state=new.value,
                exc_info=True,
            )
            return
        log.info(
            "governor_transition_context",
            old_state=old.value,
            new_state=new.value,
            memory_percent=reading.used_percent,
            **context,
        )

    def _close_state_interval(self, state: GovernorState, now: float) -> None:
        """Add the time since the last transition to ``state``'s total."""
        tracked = _TRACKED_STATES.get(state)
        if tracked is not None:
            self._time_in_state[tracked] += max(0.0, now - self._state_entered_at)
        self._state_entered_at = now

    def _reset_telemetry(self) -> None:
        self._time_in_state = _zero_time_in_state()
        self._peak_memory_percent = 0.0
        self._state_entered_at = _clock()

    def report_wave_failures(self, success_count: int, failure_count: int) -> None:
        """No-op: failures are counted per call in release() (docs/DECISIONS.md#p3-d-04).

        Kept for the ConcurrencyController protocol; RateLimitController still
        uses wave totals.
        """

    def _record_outcome(self, success: bool) -> None:
        """Only inference failures count: a parse fallback releases with success=True."""
        self._outcomes.append(success)
        if success:
            self._consecutive_successes += 1
            self._maybe_regrow()
            return
        self._consecutive_successes = 0
        window = self._settings.failure_window_size
        if len(self._outcomes) < window:
            return
        failures = self._outcomes.count(False)
        if failures * 100 < self._settings.batch_failure_threshold_percent * len(self._outcomes):
            return
        self._outcomes.clear()
        if self._state is GovernorState.CRISIS:
            return
        shrink = min(self._settings.slot_adjustment_step, self._limit - 1)
        if shrink <= 0:
            return
        self._failure_debt += shrink
        self._set_limit(self._limit - shrink)
        log.warning(
            "slot adjustment",
            action="shrink",
            amount=shrink,
            new_limit=self._limit,
            reason=f"{failures} of the last {window} inferences failed",
        )

    def _maybe_regrow(self) -> None:
        if (
            self._failure_debt == 0
            or self._consecutive_successes < self._settings.failure_regrow_successes
            or self._state not in (GovernorState.RUNNING, GovernorState.THROTTLED)
        ):
            return
        self._consecutive_successes = 0
        grow = min(
            self._settings.slot_adjustment_step,
            self._failure_debt,
            self._settings.max_parallel - self._limit,
        )
        if grow <= 0:
            self._failure_debt = 0
            return
        self._failure_debt -= grow
        self._set_limit(self._limit + grow)
        log.info(
            "slot adjustment",
            action="grow",
            amount=grow,
            new_limit=self._limit,
            reason=f"{self._settings.failure_regrow_successes} consecutive successful inferences",
        )

    # --- Properties ---

    @property
    def current_limit(self) -> int:
        """Current concurrency slot limit."""
        return self._limit

    @property
    def active_count(self) -> int:
        """Number of slots currently in use."""
        return self._in_use

    @property
    def is_paused(self) -> bool:
        """True when governor is in PAUSED or CRISIS state."""
        return self._state in (GovernorState.PAUSED, GovernorState.CRISIS)

    @property
    def state(self) -> GovernorState:
        """Current state machine state (for observability)."""
        return self._state

    # --- Context manager (backward compat) ---

    async def __aenter__(self) -> ResourceGovernor:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # A failed call must not reset the crisis clock (docs/DECISIONS.md#p3-d-08).
        self.release(success=exc_type is None)

    # --- Limiter internals ---

    def _notify(self) -> None:
        """Wake every waiter so it re-checks the predicate."""
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def _set_limit(self, new_limit: int) -> None:
        """Resize; in-use above a smaller limit drains naturally (no debt bookkeeping)."""
        self._limit = max(1, new_limit)
        self._notify()

    def _sync_gate(self) -> None:
        """Close the queue in PAUSED and CRISIS, open it otherwise."""
        self._paused = self._state in (GovernorState.PAUSED, GovernorState.CRISIS)
        self._notify()

    def _absorb_monitor_failure(self, task: asyncio.Task[None] | None = None) -> None:
        """Record a dead monitor's exception as the fatal error (once)."""
        task = task if task is not None else self._monitor_task
        if self._fatal is not None or task is None or not task.done() or task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        if isinstance(exc, GovernorCrisisError):
            self._fatal = exc
        else:
            duration = time.monotonic() - self._crisis_start if self._crisis_start is not None else 0.0
            fatal = GovernorCrisisError(f"Memory monitor stopped unexpectedly: {exc}", duration_seconds=duration)
            fatal.__cause__ = exc
            self._fatal = fatal
        log.error("governor_monitor_failed", error=str(self._fatal))
        self._notify()

    def _reset_session(self) -> None:
        """Clean RUNNING baseline for the next monitoring session."""
        self._state = GovernorState.RUNNING
        self._crisis_start = None
        self._paused_since = None
        self._consecutive_green_checks = 0
        self._limit = self._settings.baseline_parallel
        self._in_use = 0
        self._paused = False
        self._fatal = None
        self._fatal_delivered = False
        self._outcomes.clear()
        self._consecutive_successes = 0
        self._failure_debt = 0
        self._notify()

    # --- Internal monitoring ---

    async def _monitor_loop(self) -> None:
        """Background loop: read memory, apply state transitions."""
        try:
            while True:
                reading = await self._monitor.read_combined()
                async with self._adjustment_lock:
                    await self._apply_state_transition(reading)
                # Emit metrics EVERY check, not only on state transitions: a
                # healthy run never transitions, which left the UI's PARALLEL
                # SLOTS tile stuck at 0/16 for the whole simulation. Double
                # emit on transition iterations is harmless (last write wins).
                # An observability failure must NEVER kill monitoring (F-21).
                try:
                    self._emit_metrics(reading)
                except Exception:
                    log.warning("governor_emit_metrics_failed", exc_info=True)
                await asyncio.sleep(self._settings.check_interval_seconds)
        except asyncio.CancelledError:
            return
        except GovernorCrisisError:
            raise
        except Exception as exc:
            # An unexpected failure (e.g. in read_combined or the state machine)
            # would otherwise silently terminate the monitor task, freezing the
            # pool limit and disabling all further throttling for the round
            # while in-flight agents keep running (F-21). Convert it into a
            # deterministic abort that every acquire() raises (the fatal error).
            log.error("governor_monitor_loop_failed", exc_info=True)
            raise GovernorCrisisError(
                f"Memory monitor loop terminated unexpectedly: {exc}",
                duration_seconds=0.0,
            ) from exc

    async def _apply_state_transition(self, reading: MemoryReading) -> None:
        """State machine transition logic.

        State transitions:
        - RUNNING: crisis -> CRISIS, pause_zone -> PAUSED, throttle_zone -> THROTTLED,
                   scale_up_eligible -> count checks, grow if consecutive threshold met
        - THROTTLED: crisis -> CRISIS, pause_zone -> PAUSED,
                     not throttle_zone -> RUNNING
        - PAUSED: crisis -> CRISIS, not pause_zone -> THROTTLED/RUNNING
        - CRISIS: green -> RECOVERING (reset to baseline), timeout -> raise error
        - RECOVERING: crisis -> CRISIS, at baseline -> RUNNING
        """
        self._peak_memory_percent = max(self._peak_memory_percent, reading.used_percent)
        old_state = self._state
        reason = f"pressure={reading.pressure_level.value}, used={reading.used_percent:.1f}%"

        if self._state == GovernorState.RUNNING:
            await self._handle_running(reading)
        elif self._state == GovernorState.THROTTLED:
            await self._handle_throttled(reading)
        elif self._state == GovernorState.PAUSED:
            await self._handle_paused(reading)
        elif self._state == GovernorState.CRISIS:
            await self._handle_crisis(reading)
        elif self._state == GovernorState.RECOVERING:
            await self._handle_recovering(reading)

        new_state = self._state
        if old_state != new_state:
            self._close_state_interval(old_state, _clock())
            log.warning(
                "governor state transition",
                old_state=old_state.value,
                new_state=new_state.value,
                reason=reason,
            )
            self._emit_metrics(reading)
            await self._log_transition_context(old_state, new_state, reading)

    def _emit_metrics(self, reading: MemoryReading) -> None:
        """Emit GovernorMetrics to StateStore on state change (D-09, D-11)."""
        if self._state_store is not None:
            from alphaswarm.state import GovernorMetrics

            self._state_store.update_governor_metrics(
                GovernorMetrics(
                    current_slots=self._limit,
                    active_count=self._in_use,
                    pressure_level=reading.pressure_level.value,
                    memory_percent=reading.used_percent,
                    governor_state=self._state.value,
                    timestamp=time.monotonic(),
                )
            )

    def _enter_crisis(self, reading: MemoryReading, *, since: float | None = None) -> None:
        """CRISIS: drop to 1 slot (docs/DECISIONS.md#p3-d-13) and start the crisis clock.

        ``since`` backdates the clock (an escalated pause counts from when the
        queue stopped), so the D-07 abort follows on the next check.
        """
        self._state = GovernorState.CRISIS
        self._set_limit(1)
        self._failure_debt = 0  # recovery targets the baseline instead
        self._crisis_start = since if since is not None else time.monotonic()
        self._paused_since = None
        self._consecutive_green_checks = 0
        self._sync_gate()

    async def _handle_running(self, reading: MemoryReading) -> None:
        """Handle state transitions from RUNNING."""
        if reading.is_crisis:
            self._enter_crisis(reading)
        elif reading.is_pause_zone:
            self._state = GovernorState.PAUSED
            self._paused_since = time.monotonic()
            self._consecutive_green_checks = 0
            self._sync_gate()
        elif reading.is_throttle_zone:
            self._state = GovernorState.THROTTLED
            self._consecutive_green_checks = 0
            self._sync_gate()
        elif reading.is_scale_up_eligible:
            self._consecutive_green_checks += 1
            if (
                self._consecutive_green_checks >= self._settings.scale_up_consecutive_checks
                and self._limit < self._settings.max_parallel
            ):
                grow_amount = min(
                    self._settings.slot_adjustment_step,
                    self._settings.max_parallel - self._limit,
                )
                if grow_amount > 0:
                    self._set_limit(self._limit + grow_amount)
                    log.info(
                        "slot adjustment",
                        action="grow",
                        amount=grow_amount,
                        new_limit=self._limit,
                        reason="consecutive green checks met scale-up threshold",
                    )
                self._consecutive_green_checks = 0
        else:
            # Not scale_up_eligible, reset counter
            self._consecutive_green_checks = 0

    async def _handle_throttled(self, reading: MemoryReading) -> None:
        """Handle state transitions from THROTTLED."""
        if reading.is_crisis:
            self._enter_crisis(reading)
        elif reading.is_pause_zone:
            self._state = GovernorState.PAUSED
            self._paused_since = time.monotonic()
            self._sync_gate()
        elif not reading.is_throttle_zone:
            self._state = GovernorState.RUNNING
            self._consecutive_green_checks = 0
            self._sync_gate()

    async def _handle_paused(self, reading: MemoryReading) -> None:
        """PAUSED: leave when the pause zone clears; escalate when stuck (docs/DECISIONS.md#p3-d-07)."""
        if reading.is_crisis:
            self._enter_crisis(reading)
            return
        if not reading.is_pause_zone:
            self._state = GovernorState.THROTTLED if reading.is_throttle_zone else GovernorState.RUNNING
            self._paused_since = None
            self._sync_gate()
            return
        now = time.monotonic()
        timeout = self._settings.crisis_timeout_seconds
        if (
            self._paused_since is not None
            and now - self._paused_since > timeout
            and now - self._last_successful_inference > timeout
        ):
            log.error(
                "governor_pause_escalated",
                paused_seconds=now - self._paused_since,
                reason="paused past crisis_timeout_seconds with no successful inference",
            )
            self._enter_crisis(reading, since=self._paused_since)

    async def _handle_crisis(self, reading: MemoryReading) -> None:
        """CRISIS: D-07 abort on timeout; leave only when pressure AND the pause zone clear."""
        now = time.monotonic()
        timeout = self._settings.crisis_timeout_seconds
        if (
            self._crisis_start is not None
            and now - self._crisis_start > timeout
            and now - self._last_successful_inference > timeout
        ):
            duration = now - self._crisis_start
            log.error(
                "governor crisis abort",
                duration_seconds=duration,
                reason="crisis timeout with no successful inference",
            )
            raise GovernorCrisisError(
                f"Governor crisis timeout after {duration:.1f}s with no successful inference",
                duration_seconds=duration,
            )
        if reading.is_crisis or reading.is_pause_zone:
            return
        self._state = GovernorState.RECOVERING
        self._crisis_start = None
        # D-03 sets the target (baseline, not the pre-incident count); D-01 says
        # how to get there: one step now, one step per calm check in RECOVERING
        # (docs/DECISIONS.md#p3-d-01, #p3-d-03).
        target = min(self._settings.baseline_parallel, self._limit + self._settings.slot_adjustment_step)
        if target > self._limit:
            amount = target - self._limit
            self._set_limit(target)
            log.info(
                "slot adjustment",
                action="grow",
                amount=amount,
                new_limit=self._limit,
                reason="crisis cleared: first recovery step toward baseline",
            )
        self._sync_gate()

    async def _handle_recovering(self, reading: MemoryReading) -> None:
        """Handle state transitions from RECOVERING.

        D-01: Gradual recovery +2 per check until baseline, then RUNNING.
        """
        if reading.is_crisis:
            self._enter_crisis(reading)
            return

        # If at or above baseline, transition to RUNNING
        if self._limit >= self._settings.baseline_parallel:
            self._state = GovernorState.RUNNING
            self._consecutive_green_checks = 0
            self._sync_gate()
        else:
            # D-01: Gradual +2 recovery
            grow_amount = min(
                self._settings.slot_adjustment_step,
                self._settings.baseline_parallel - self._limit,
            )
            if grow_amount > 0:
                self._set_limit(self._limit + grow_amount)
                log.info(
                    "slot adjustment",
                    action="grow",
                    amount=grow_amount,
                    new_limit=self._limit,
                    reason="gradual recovery toward baseline",
                )
            if self._limit >= self._settings.baseline_parallel:
                self._state = GovernorState.RUNNING
                self._consecutive_green_checks = 0
                self._sync_gate()
