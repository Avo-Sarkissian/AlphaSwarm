"""Adaptive rate-limit controller for cloud inference providers.

Implements the ConcurrencyController protocol for the cloud path.
Provides:
  - TokenBucket: continuous-refill token bucket with injected clock for deterministic testing.
  - RateLimitController: in-flight slot limiting + RPM/TPM rate limiting + adaptive shrink.

Budget enforcement is intentionally NOT here — it lives in BudgetTrackingProvider (budget.py)
so that ALL cloud calls (workers, seed, advisory, report) are counted uniformly, regardless
of whether they go through the concurrency controller.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from alphaswarm.inference.concurrency import ConcurrencyController

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


class TokenBucket:
    """Continuous-refill token bucket with injected clock.

    Parameters
    ----------
    rate_per_min:
        Maximum sustained rate (tokens per minute).  ``None`` means unlimited —
        ``reserve`` always returns 0.0 and no state is tracked.
    now:
        Callable returning the current time in seconds.  Default is
        ``time.monotonic``.  Inject a fake clock in tests so bucket math is
        verifiable without real sleeping.

    Notes
    -----
    ``capacity`` equals ``rate_per_min`` (1-second burst headroom is implicit).
    Tokens refill continuously: each call to ``reserve`` first refills based on
    elapsed time since the last interaction, then checks / decrements.

    The bucket allows deficits — ``reserve`` may return a wait time > 0 and
    decrement the level below zero.  The caller is expected to sleep (or not)
    based on the returned wait, then proceed.  The deficit refills naturally
    over time.  This is the "leaky token bucket" / "token bucket with deficit"
    model, which handles bursts correctly without losing requests.
    """

    def __init__(
        self,
        rate_per_min: int | None,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate_per_min = rate_per_min
        self._now = now

        if rate_per_min is not None:
            self._rate_per_sec: float = rate_per_min / 60.0
            self._capacity: float = float(rate_per_min)
            self._tokens: float = float(rate_per_min)  # start full
            self._last_refill: float = now()
        # else: no state needed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """Advance tokens based on elapsed time; cap at capacity."""
        now = self._now()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reserve(self, n: int) -> float:
        """Reserve *n* tokens and return the seconds the caller must wait.

        Parameters
        ----------
        n:
            Number of tokens to consume.

        Returns
        -------
        float
            Seconds to wait before the reserved tokens are "available".
            0.0 means the tokens were immediately available.
            Positive means the bucket is in deficit; the caller should sleep
            this long before issuing the request.

        Notes
        -----
        The bucket is decremented by *n* immediately (even if it goes into
        deficit) so that concurrent callers correctly see the future state
        and don't all try to claim the same tokens.
        """
        if self._rate_per_min is None:
            return 0.0

        self._refill()
        self._tokens -= n

        if self._tokens >= 0:
            return 0.0

        # How long until the deficit refills to 0?
        wait = (-self._tokens) / self._rate_per_sec
        return wait

    def refund(self, delta: int) -> None:
        """Return *delta* tokens to the bucket WITHOUT clamping to capacity.

        Used by RateLimitController.release() to reconcile the estimated vs
        actual token cost.  A positive delta means we over-reserved; a
        negative delta means we under-reserved (caller takes more tokens).

        Parameters
        ----------
        delta:
            Signed delta to add back (positive = over-reserved, negative =
            under-reserved).

        Notes
        -----
        Refund intentionally does NOT clamp at capacity.  Under concurrency,
        multiple callers may have already driven the bucket into deficit via
        their own reservations.  Clamping here would silently erase those
        in-flight deficits and loosen TPM pacing.  The capacity ceiling is
        enforced by ``_refill``, which caps its own additions at capacity
        on every subsequent call.  Conservation: reserve(n) then refund(n)
        returns the bucket to its prior logical level regardless of
        intervening concurrent reservations.
        """
        if self._rate_per_min is None:
            return

        self._refill()
        self._tokens += delta  # NO clamp — _refill enforces capacity ceiling


# ---------------------------------------------------------------------------
# RateLimitController
# ---------------------------------------------------------------------------


class RateLimitController:
    """Cloud-path ConcurrencyController: in-flight cap + RPM/TPM rate limiting.

    Satisfies the ``ConcurrencyController`` protocol so it can be used
    interchangeably with ``ResourceGovernor`` in factory dispatch.

    Parameters
    ----------
    max_in_flight:
        Maximum simultaneous requests.  The effective maximum may shrink at
        runtime via ``report_wave_failures`` (down to ``min_in_flight``).
    requests_per_min:
        Sustained request rate cap.  ``None`` = unlimited.
    tokens_per_min:
        Sustained token rate cap.  ``None`` = unlimited.
    state_store:
        Optional object with a ``set(key, value)`` method for emitting
        periodic metrics.  If ``None``, monitoring is a harmless no-op.
    avg_tokens_per_call:
        Estimated token cost reserved at ``acquire()`` time for TPM pacing.
        Reconciled to the actual cost at ``release()`` time if
        ``result_tokens`` is provided.
    now:
        Injected clock callable (seconds).  Default ``time.monotonic``.
        Inject a fake in tests.
    failure_shrink_threshold:
        Wave failure-rate fraction at or above which effective max_in_flight
        is reduced by 1.  Default 0.20 (20%).
    min_in_flight:
        Floor for adaptive shrink.  Default 1.

    Shrink implementation
    ---------------------
    We track ``_target_slots`` (the desired effective concurrency) separately
    from the semaphore's internal count.  When ``_target_slots`` is reduced,
    the next ``_target_slots`` - old count acquire calls "borrow" a slot
    without releasing it back — we do this lazily: a dedicated
    ``_shrink_in_progress`` counter records how many tokens we still need to
    drain.  Each ``acquire()`` call first checks whether a drain token is owed
    and, if so, acquires from the semaphore without releasing (decrementing
    ``_shrink_in_progress`` and looping to acquire a real slot next).

    This avoids spawning background tasks and keeps the semaphore as the
    single source of truth for blocking.  It is safe under asyncio's
    single-threaded cooperative model.
    """

    def __init__(
        self,
        *,
        max_in_flight: int,
        requests_per_min: int | None,
        tokens_per_min: int | None,
        state_store: Any = None,
        avg_tokens_per_call: int = 1500,
        now: Callable[[], float] = time.monotonic,
        failure_shrink_threshold: float = 0.20,
        min_in_flight: int = 1,
    ) -> None:
        self._max_in_flight = max_in_flight
        self._target_slots = max_in_flight
        self._min_in_flight = min_in_flight
        self._failure_shrink_threshold = failure_shrink_threshold
        self._avg_tokens_per_call = avg_tokens_per_call
        self._state_store = state_store
        self._now = now

        self._requests_per_min = requests_per_min
        self._tokens_per_min = tokens_per_min

        # Semaphore initialized to max_in_flight
        self._semaphore = asyncio.Semaphore(max_in_flight)

        # Token buckets
        self._rpm_bucket = TokenBucket(requests_per_min, now=now)
        self._tpm_bucket = TokenBucket(tokens_per_min, now=now)

        # Shrink tracking: how many semaphore tokens to drain without releasing
        self._shrink_pending: int = 0

        # Monitoring
        self._monitor_task: asyncio.Task[None] | None = None
        self._in_flight: int = 0  # active call count (informational)

    # ------------------------------------------------------------------
    # ConcurrencyController protocol
    # ------------------------------------------------------------------

    async def acquire(self) -> None:
        """Claim an in-flight slot, then pace via RPM + TPM buckets.

        If a shrink is pending, we drain one semaphore token (decrement
        ``_shrink_pending``) and loop to acquire a real slot next time.
        """
        # Handle any pending shrink tokens: acquire but don't return them,
        # effectively reducing the available pool by 1.
        if self._shrink_pending > 0:
            self._shrink_pending -= 1
            await self._semaphore.acquire()
            # Do NOT release — this token is now permanently held back.
            # Now acquire again for the actual request.

        await self._semaphore.acquire()
        self._in_flight += 1

        # Rate-limit: reserve estimated cost and wait if needed
        rpm_wait = self._rpm_bucket.reserve(1)
        tpm_wait = self._tpm_bucket.reserve(self._avg_tokens_per_call)
        wait = max(rpm_wait, tpm_wait)
        if wait > 0:
            await asyncio.sleep(wait)

    def release(
        self, *, success: bool = True, result_tokens: int | None = None
    ) -> None:
        """Free the in-flight slot and reconcile TPM bucket if token count known.

        Parameters
        ----------
        success:
            Whether the call succeeded (informational; not used for budget).
        result_tokens:
            Actual output tokens from the completed call.  If provided and
            tokens_per_min is set, reconcile: we reserved ``avg_tokens_per_call``
            upfront.  If actual < reserved, refund the difference; if actual >
            reserved, take additional tokens.
        """
        # TPM reconciliation
        if result_tokens is not None and self._tokens_per_min is not None:
            delta = self._avg_tokens_per_call - result_tokens
            # delta > 0 → over-reserved → refund; delta < 0 → under-reserved → take more
            self._tpm_bucket.refund(delta)

        self._semaphore.release()
        self._in_flight = max(0, self._in_flight - 1)

    def report_wave_failures(
        self, success_count: int, failure_count: int
    ) -> None:
        """Shrink effective max_in_flight if failure rate >= threshold.

        Parameters
        ----------
        success_count:
            Number of successful calls in the wave.
        failure_count:
            Number of failed calls in the wave.

        Notes
        -----
        Only shrinks; never grows.  The new target is floored at
        ``min_in_flight``.  The actual drain happens lazily on the next
        ``acquire()`` calls.
        """
        total = success_count + failure_count
        if total == 0:
            return

        failure_rate = failure_count / total
        if (
            failure_rate >= self._failure_shrink_threshold
            and self._target_slots > self._min_in_flight
        ):
            self._target_slots -= 1
            self._shrink_pending += 1
            logger.info(
                "RateLimitController: failure rate %.1f%% >= threshold %.1f%% — "
                "shrinking effective max_in_flight to %d (pending drain: %d)",
                failure_rate * 100,
                self._failure_shrink_threshold * 100,
                self._target_slots,
                self._shrink_pending,
            )

    async def start_monitoring(self) -> None:
        """Launch background metrics emitter task (~2 s cadence)."""
        if self._monitor_task is not None:
            return  # idempotent
        self._monitor_task = asyncio.create_task(
            self._monitoring_loop(), name="rate-limit-monitor"
        )

    async def stop_monitoring(self) -> None:
        """Cancel and await the background monitoring task cleanly."""
        if self._monitor_task is None:
            return
        self._monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._monitor_task
        self._monitor_task = None

    async def __aenter__(self) -> RateLimitController:
        """Acquire a concurrency slot (async context manager entry)."""
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Release the concurrency slot (async context manager exit)."""
        self.release()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _monitoring_loop(self) -> None:
        """Keep-alive loop while the controller is running.

        Live RPM/TPM WebSocket telemetry is a future enhancement — mode and
        running spend are already surfaced via GET /api/health.  StateStore has
        no ``set()`` method, so we do not attempt to emit here; that call was
        removed to stop the silent AttributeError that fired every ~2 s.
        """
        while True:
            await asyncio.sleep(2.0)


# Runtime-checkable protocol compliance assertion (fails fast at import if
# the class drifts out of sync with the protocol).
assert isinstance(
    RateLimitController(
        max_in_flight=1,
        requests_per_min=None,
        tokens_per_min=None,
    ),
    ConcurrencyController,
), "RateLimitController must satisfy ConcurrencyController protocol"
