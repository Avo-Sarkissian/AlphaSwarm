"""ResourceGovernor with dynamic concurrency control and state machine.

Phase 1: No-op stub.
Phase 2: Fixed concurrency control for backpressure.
Phase 3: Dynamic TokenPool with debt tracking, 5-state machine, dual-signal
         memory monitoring, gradual recovery, scale-up logic, crisis timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import time
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
# TokenPool with debt tracking
# ---------------------------------------------------------------------------


class TokenPool:
    """Queue-based concurrency token pool with debt-aware shrinking.

    Replaces Phase 2 fixed semaphore. Supports O(1) grow/shrink
    without deadlock. When shrink() cannot remove tokens because they are
    checked out, it records debt. When those tokens are eventually released,
    they are consumed by the debt instead of returning to the pool.
    """

    def __init__(self, initial_size: int) -> None:
        self._pool: asyncio.Queue[bool] = asyncio.Queue()
        self._current_limit = initial_size
        self._debt: int = 0
        for _ in range(initial_size):
            self._pool.put_nowait(True)

    async def acquire(self) -> None:
        """Acquire a token. Blocks if pool is empty."""
        await self._pool.get()

    def release(self) -> None:
        """Return a token to the pool.

        If there is outstanding debt (from shrink while tokens were checked out),
        the token is consumed by the debt and NOT returned to the pool.
        """
        if self._debt > 0:
            self._debt -= 1
        else:
            self._pool.put_nowait(True)

    def grow(self, amount: int) -> None:
        """Add tokens to the pool, increasing current_limit.

        Outstanding debt (recorded by shrink() while tokens were checked out)
        is paid down FIRST: each unit of ``amount`` that cancels debt restores
        capacity already backed by a still-running checked-out inference, so
        only the remainder becomes new free tokens. Without this, a grow during
        crisis recovery would add ``amount`` free tokens on top of ``debt``
        still-checked-out tokens, letting in-flight inferences exceed
        current_limit and defeating the memory throttle at the worst moment (F-04).
        """
        to_pay = min(amount, self._debt)
        self._debt -= to_pay
        for _ in range(amount - to_pay):
            self._pool.put_nowait(True)
        self._current_limit += amount

    def shrink(self, amount: int) -> int:
        """Remove tokens from the pool.

        Two-phase shrink: First, try to remove free tokens via get_nowait().
        For tokens that cannot be removed (checked out), add to debt counter.
        current_limit is decremented immediately for all requested tokens.

        Returns:
            The total amount of shrinkage (always equals amount).
        """
        removed_from_queue = 0
        for _ in range(amount):
            try:
                self._pool.get_nowait()
                removed_from_queue += 1
            except asyncio.QueueEmpty:
                self._debt += 1
        self._current_limit -= amount
        return amount

    @property
    def current_limit(self) -> int:
        """Current intended capacity of the pool."""
        return self._current_limit

    @property
    def available(self) -> int:
        """Number of tokens currently available (not checked out)."""
        return self._pool.qsize()

    @property
    def debt(self) -> int:
        """Number of tokens that will be consumed on release instead of returned."""
        return self._debt

    def reset(self, size: int) -> None:
        """Drain pool and reinitialize to the given size, clearing all debt."""
        while not self._pool.empty():
            self._pool.get_nowait()
        self._debt = 0
        self._current_limit = size
        for _ in range(size):
            self._pool.put_nowait(True)


# ---------------------------------------------------------------------------
# ResourceGovernor
# ---------------------------------------------------------------------------


class ResourceGovernor:
    """Dynamic concurrency governor with Queue-based TokenPool and state machine.

    Monitors dual memory signals (kernel used % + pressure) and adjusts concurrency
    slots dynamically. Implements 5-state machine: RUNNING, THROTTLED, PAUSED,
    CRISIS, RECOVERING.

    Constructor signature:
        ResourceGovernor(settings: GovernorSettings | None = None, *,
                         state_store: StateStore | None = None,
                         monitor: MemoryReader | None = None)
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
        self._pool = TokenPool(settings.baseline_parallel)
        self._monitor: MemoryReader = monitor if monitor is not None else MemoryMonitor(settings)
        self._state = GovernorState.RUNNING
        self._state_store = state_store
        self._active_count = 0
        self._last_successful_inference = time.monotonic()
        self._crisis_start: float | None = None
        self._consecutive_green_checks = 0
        self._adjustment_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task[None] | None = None
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # Start in RUNNING state (not blocked)
        # Per-session telemetry: seconds per tracked state and peak memory.
        self._time_in_state: dict[GovernorTelemetryState, float] = _zero_time_in_state()
        self._peak_memory_percent = 0.0
        self._state_entered_at = _clock()
        self._transition_probe: TransitionProbe | None = None

    # --- Public API ---

    async def acquire(self) -> None:
        """Acquire a concurrency slot. Blocks when PAUSED/CRISIS or pool empty.

        Raises GovernorCrisisError if the monitor task has died, since no other
        code path can set _resume_event — blocking here would deadlock forever.

        The dead-monitor check runs AFTER _resume_event.wait() so that agents
        already blocked when the monitor dies are unblocked by the done callback
        (_on_monitor_done sets the event) and then fail here instead of hanging.
        """
        await self._resume_event.wait()
        self._check_monitor_alive()
        await self._pool.acquire()
        self._active_count += 1

    def _check_monitor_alive(self) -> None:
        """Raise GovernorCrisisError if the monitor task has died with an error.

        _monitor_loop already turns its own failures into GovernorCrisisError,
        so that instance is re-raised unchanged. Any other exception is wrapped,
        carrying the crisis duration so far when a crisis was in progress.
        """
        if self._monitor_task is None or not self._monitor_task.done():
            return
        try:
            exc = self._monitor_task.exception()
        except asyncio.CancelledError:
            return  # Normal cancellation from stop_monitoring
        if exc is None:
            return
        if isinstance(exc, GovernorCrisisError):
            raise exc
        duration = time.monotonic() - self._crisis_start if self._crisis_start is not None else 0.0
        raise GovernorCrisisError(
            "Monitor task died — cannot acquire slot",
            duration_seconds=duration,
        ) from exc

    def release(self, *, success: bool = True, result_tokens: int | None = None) -> None:
        """Release a concurrency slot.

        Args:
            success: If True (default), updates _last_successful_inference
                     timestamp, resetting the crisis timeout clock (D-08).
            result_tokens: Token count from the completed inference.  Currently
                ignored here; reserved for the RateLimitController in Task 12.
        """
        self._pool.release()
        self._active_count = max(0, self._active_count - 1)
        if success:
            self._last_successful_inference = time.monotonic()

    async def start_monitoring(self) -> None:
        """Start background memory monitoring loop."""
        if self._monitor_task is None or self._monitor_task.done():
            self._reset_telemetry()
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            self._monitor_task.add_done_callback(self._on_monitor_done)

    def _on_monitor_done(self, task: asyncio.Task[None]) -> None:
        """Done callback: unblock agents stuck in acquire() when monitor dies.

        Without this, agents already waiting on _resume_event.wait() would
        never wake up because the monitor (the only code that sets the event)
        is dead. Setting the event wakes them so they hit _check_monitor_alive
        and raise GovernorCrisisError instead of hanging forever.
        """
        self._resume_event.set()

    async def stop_monitoring(self) -> None:
        """Stop the monitoring loop and fully reset governor for the next session.

        Resets state machine, crisis timer, TokenPool, and resume event so that
        a subsequent start_monitoring() begins from a clean RUNNING baseline.
        """
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

        self._close_state_interval(self._state, _clock())
        # Bug 1 fix: reset state machine so stale PAUSED/CRISIS doesn't bleed
        self._state = GovernorState.RUNNING
        self._crisis_start = None
        self._consecutive_green_checks = 0

        # Bug 4 fix: each session starts at baseline; shrinks last the whole run (docs/DECISIONS.md#adr-round-runner)
        self._pool.reset(self._settings.baseline_parallel)
        self._active_count = 0

        self._resume_event.set()

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
        """Report wave batch results and shrink if failure rate exceeds threshold.

        Per D-04/D-05: If failure_rate >= batch_failure_threshold_percent,
        shrink by slot_adjustment_step. Never shrink below 1 slot.
        """
        total = success_count + failure_count
        if total == 0:
            return
        failure_rate = failure_count / total
        threshold = self._settings.batch_failure_threshold_percent / 100.0

        if failure_rate >= threshold:
            shrink_amount = min(
                self._settings.slot_adjustment_step,
                self._pool.current_limit - 1,  # D-05: minimum 1 slot
            )
            if shrink_amount > 0:
                self._pool.shrink(shrink_amount)
                log.warning(
                    "slot adjustment",
                    action="shrink",
                    amount=shrink_amount,
                    new_limit=self._pool.current_limit,
                    reason=f"wave failure rate {failure_rate:.1%} >= {threshold:.1%}",
                )

    # --- Properties ---

    @property
    def current_limit(self) -> int:
        """Current concurrency slot limit."""
        return self._pool.current_limit

    @property
    def active_count(self) -> int:
        """Number of currently checked-out slots."""
        return self._active_count

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
            # deterministic abort so _check_monitor_alive fails fast instead.
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
                    current_slots=self._pool.current_limit,
                    active_count=self._active_count,
                    pressure_level=reading.pressure_level.value,
                    memory_percent=reading.used_percent,
                    governor_state=self._state.value,
                    timestamp=time.monotonic(),
                )
            )

    def _update_resume_event(self) -> None:
        """Set or clear _resume_event based on current state."""
        if self._state in (GovernorState.PAUSED, GovernorState.CRISIS):
            self._resume_event.clear()
        else:
            self._resume_event.set()

    def _enter_crisis(self, reading: MemoryReading) -> None:
        """Enter CRISIS state: drop to 1 slot, record start time."""
        self._state = GovernorState.CRISIS
        # D-13: Drop to 1 slot
        shrink_amount = self._pool.current_limit - 1
        if shrink_amount > 0:
            self._pool.shrink(shrink_amount)
        self._crisis_start = time.monotonic()
        self._consecutive_green_checks = 0
        self._update_resume_event()

    async def _handle_running(self, reading: MemoryReading) -> None:
        """Handle state transitions from RUNNING."""
        if reading.is_crisis:
            self._enter_crisis(reading)
        elif reading.is_pause_zone:
            self._state = GovernorState.PAUSED
            self._consecutive_green_checks = 0
            self._update_resume_event()
        elif reading.is_throttle_zone:
            self._state = GovernorState.THROTTLED
            self._consecutive_green_checks = 0
            self._update_resume_event()
        elif reading.is_scale_up_eligible:
            self._consecutive_green_checks += 1
            if (
                self._consecutive_green_checks >= self._settings.scale_up_consecutive_checks
                and self._pool.current_limit < self._settings.max_parallel
            ):
                grow_amount = min(
                    self._settings.slot_adjustment_step,
                    self._settings.max_parallel - self._pool.current_limit,
                )
                if grow_amount > 0:
                    self._pool.grow(grow_amount)
                    log.info(
                        "slot adjustment",
                        action="grow",
                        amount=grow_amount,
                        new_limit=self._pool.current_limit,
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
            self._update_resume_event()
        elif not reading.is_throttle_zone:
            self._state = GovernorState.RUNNING
            self._consecutive_green_checks = 0
            self._update_resume_event()

    async def _handle_paused(self, reading: MemoryReading) -> None:
        """Handle state transitions from PAUSED."""
        if reading.is_crisis:
            self._enter_crisis(reading)
        elif not reading.is_pause_zone:
            if reading.is_throttle_zone:
                self._state = GovernorState.THROTTLED
            else:
                self._state = GovernorState.RUNNING
            self._update_resume_event()

    async def _handle_crisis(self, reading: MemoryReading) -> None:
        """Handle state transitions from CRISIS.

        Check timeout (D-07), then check for recovery to GREEN (D-03).
        """
        now = time.monotonic()

        # D-07: Crisis timeout check
        if (
            self._crisis_start is not None
            and now - self._crisis_start > self._settings.crisis_timeout_seconds
            and now - self._last_successful_inference > self._settings.crisis_timeout_seconds
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

        # D-03: Recovery when pressure returns to GREEN
        if not reading.is_crisis:
            self._state = GovernorState.RECOVERING
            self._crisis_start = None
            # Reset to baseline (D-03)
            current = self._pool.current_limit
            if current < self._settings.baseline_parallel:
                grow_amount = self._settings.baseline_parallel - current
                self._pool.grow(grow_amount)
                log.info(
                    "slot adjustment",
                    action="grow",
                    amount=grow_amount,
                    new_limit=self._pool.current_limit,
                    reason="crisis recovery reset to baseline",
                )
            self._update_resume_event()

    async def _handle_recovering(self, reading: MemoryReading) -> None:
        """Handle state transitions from RECOVERING.

        D-01: Gradual recovery +2 per check until baseline, then RUNNING.
        """
        if reading.is_crisis:
            self._enter_crisis(reading)
            return

        # If at or above baseline, transition to RUNNING
        if self._pool.current_limit >= self._settings.baseline_parallel:
            self._state = GovernorState.RUNNING
            self._consecutive_green_checks = 0
            self._update_resume_event()
        else:
            # D-01: Gradual +2 recovery
            grow_amount = min(
                self._settings.slot_adjustment_step,
                self._settings.baseline_parallel - self._pool.current_limit,
            )
            if grow_amount > 0:
                self._pool.grow(grow_amount)
                log.info(
                    "slot adjustment",
                    action="grow",
                    amount=grow_amount,
                    new_limit=self._pool.current_limit,
                    reason="gradual recovery toward baseline",
                )
            if self._pool.current_limit >= self._settings.baseline_parallel:
                self._state = GovernorState.RUNNING
                self._consecutive_green_checks = 0
                self._update_resume_event()
