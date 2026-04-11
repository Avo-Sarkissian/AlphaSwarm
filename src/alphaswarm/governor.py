"""ResourceGovernor with dynamic concurrency control and state machine.

Phase 1: No-op stub.
Phase 2: Fixed concurrency control for backpressure.
Phase 3: Dynamic TokenPool with debt tracking, 5-state machine, dual-signal
         memory monitoring, gradual recovery, scale-up logic, crisis timeout.
"""

from __future__ import annotations

import asyncio
import enum
import time
from typing import TYPE_CHECKING, Protocol

import structlog

from alphaswarm.config import GovernorSettings
from alphaswarm.errors import GovernorCrisisError
from alphaswarm.memory_monitor import MemoryMonitor, MemoryReading

if TYPE_CHECKING:
    from alphaswarm.state import StateStore

log = structlog.get_logger(component="governor")


# ---------------------------------------------------------------------------
# GovernorState enum
# ---------------------------------------------------------------------------


class GovernorState(enum.Enum):
    """State machine states for ResourceGovernor."""

    RUNNING = "running"
    THROTTLED = "throttled"
    PAUSED = "paused"
    CRISIS = "crisis"
    RECOVERING = "recovering"


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
        """Add tokens to the pool, increasing current_limit."""
        for _ in range(amount):
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
# ResourceGovernorProtocol (extended for Phase 3)
# ---------------------------------------------------------------------------


class ResourceGovernorProtocol(Protocol):
    """Interface contract for ResourceGovernor."""

    async def acquire(self) -> None: ...
    def release(self, *, success: bool = True) -> None: ...
    async def start_monitoring(self) -> None: ...
    async def stop_monitoring(self) -> None: ...

    @property
    def current_limit(self) -> int: ...

    @property
    def active_count(self) -> int: ...

    @property
    def is_paused(self) -> bool: ...


# ---------------------------------------------------------------------------
# ResourceGovernor
# ---------------------------------------------------------------------------


class ResourceGovernor:
    """Dynamic concurrency governor with Queue-based TokenPool and state machine.

    Monitors dual memory signals (psutil + macOS sysctl) and adjusts concurrency
    slots dynamically. Implements 5-state machine: RUNNING, THROTTLED, PAUSED,
    CRISIS, RECOVERING.

    Constructor signature (LOCKED -- Plan 02 depends on this exact interface):
        ResourceGovernor(settings: GovernorSettings, *, state_store: StateStore | None = None)
    """

    def __init__(
        self,
        settings: GovernorSettings | None = None,
        *,
        state_store: StateStore | None = None,
    ) -> None:
        if settings is None:
            settings = GovernorSettings()
        self._settings = settings
        self._pool = TokenPool(settings.baseline_parallel)
        self._monitor = MemoryMonitor(settings)
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
        """Raise if the monitor task has died with an error."""
        if self._monitor_task is None or not self._monitor_task.done():
            return
        try:
            exc = self._monitor_task.exception()
        except asyncio.CancelledError:
            return  # Normal cancellation from stop_monitoring
        if exc is not None:
            raise GovernorCrisisError(
                "Monitor task died — cannot acquire slot",
            ) from exc

    def release(self, *, success: bool = True) -> None:
        """Release a concurrency slot.

        Args:
            success: If True (default), updates _last_successful_inference
                     timestamp, resetting the crisis timeout clock (D-08).
        """
        self._pool.release()
        self._active_count = max(0, self._active_count - 1)
        if success:
            self._last_successful_inference = time.monotonic()

    def suspend(self) -> None:
        """Block new acquire() calls by clearing the resume event.

        Used to pause agent acquisitions during an inter-round shock
        authoring window (Phase 26). Per 26-CONTEXT.md D-01..D-03, this
        method deliberately bypasses the governor state machine:

        - Does NOT touch self._state, self._crisis_start, or
          self._consecutive_green_checks
        - Does NOT interact with the monitoring loop (which keeps running)
        - Does NOT call stop_monitoring() (which resets the TokenPool)

        The monitor loop's own authority over _resume_event (via
        _update_resume_event()) is unaffected during shock pause because the
        loop only fires on memory-pressure transitions, and inter-round gaps
        have zero active agents. If pressure does spike during the shock
        window, the monitor loop will re-clear this event on its next tick;
        resume() then defers to that state (see resume() docstring).

        Idempotent. Safe to call multiple times.
        """
        self._resume_event.clear()
        log.info("governor_suspended", reason="shock_window")

    def resume(self) -> None:
        """Unblock new acquire() calls ONLY if governor state is RUNNING.

        Per 2026-04-11 reviews revision (Codex HIGH / Gemini LOW concern):
        the callee now respects the authoritative state machine. If the
        monitor loop transitioned the governor to PAUSED or CRISIS during
        the shock window (e.g. memory pressure spiked while the user was
        typing), this method is a safe no-op — the monitor loop's own
        _update_resume_event() will re-set the gate when pressure clears.

        This prevents a subtle race where resume() could release agents
        during a real memory-pressure event, violating the core memory-
        safety invariant from CLAUDE.md (hard constraint).

        Idempotent. Safe to call under all governor states.

        Mirror of suspend() for the common RUNNING path. Per CONTEXT.md D-02.
        """
        if self._state == GovernorState.RUNNING:
            self._resume_event.set()
            log.info("governor_resumed", reason="shock_window")
        else:
            log.warning(
                "governor_resume_deferred_memory_pressure",
                reason="shock_window",
                governor_state=self._state.value,
            )

    async def start_monitoring(self) -> None:
        """Start background memory monitoring loop."""
        if self._monitor_task is None or self._monitor_task.done():
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
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        # Bug 1 fix: reset state machine so stale PAUSED/CRISIS doesn't bleed
        self._state = GovernorState.RUNNING
        self._crisis_start = None
        self._consecutive_green_checks = 0

        # Bug 4 fix: reset pool to baseline so Round 1 shrinkage doesn't degrade Round 2
        self._pool.reset(self._settings.baseline_parallel)
        self._active_count = 0

        self._resume_event.set()

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

    async def __aexit__(self, *args: object) -> None:
        self.release()

    # --- Internal monitoring ---

    async def _monitor_loop(self) -> None:
        """Background loop: read memory, apply state transitions."""
        try:
            while True:
                reading = await self._monitor.read_combined()
                async with self._adjustment_lock:
                    await self._apply_state_transition(reading)
                await asyncio.sleep(self._settings.check_interval_seconds)
        except asyncio.CancelledError:
            return
        except GovernorCrisisError:
            raise

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
        old_state = self._state
        reason = (
            f"sysctl={reading.pressure_level.value}, "
            f"psutil={reading.psutil_percent:.1f}%"
        )

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
            log.warning(
                "governor state transition",
                old_state=old_state.value,
                new_state=new_state.value,
                reason=reason,
            )
            self._emit_metrics(reading)

    def _emit_metrics(self, reading: MemoryReading) -> None:
        """Emit GovernorMetrics to StateStore on state change (D-09, D-11)."""
        if self._state_store is not None:
            from alphaswarm.state import GovernorMetrics

            self._state_store.update_governor_metrics(
                GovernorMetrics(
                    current_slots=self._pool.current_limit,
                    active_count=self._active_count,
                    pressure_level=reading.pressure_level.value,
                    memory_percent=reading.psutil_percent,
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
