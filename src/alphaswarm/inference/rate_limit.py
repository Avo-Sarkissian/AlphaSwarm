"""Rate-limit controller for cloud inference providers.

Implements the ConcurrencyController protocol for the cloud path:
  - TokenBucket: continuous-refill token bucket with an injected clock.
  - RateLimitController: in-flight cap + RPM/TPM pacing + adaptive shrink, and
    the RetryGate the cloud providers retry through: a 429 seen by one agent
    sets one shared cooldown, and every retry takes a fresh RPM token
    (docs/DECISIONS.md#adr-cloud-retry).

Budget enforcement is intentionally NOT here; it lives in BudgetTrackingProvider
(budget.py), so every cloud call (workers, seed, advisory, report) is counted.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from types import TracebackType

log = structlog.get_logger(component="inference.rate_limit")

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
    ``capacity`` equals ``rate_per_min``: after an idle minute a full minute's
    quota can go out at once (the burst is one minute of requests, not one second).
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
    avg_tokens_per_call:
        Estimated token cost reserved at ``acquire()`` time for TPM pacing.
        Reconciled to the actual cost at ``release()`` time if
        ``result_tokens`` is provided.
    now:
        Injected clock callable (seconds).  Default ``time.monotonic``.
        Inject a fake in tests.
    sleep:
        Injected sleep coroutine for pacing and cooldown waits. ``None`` uses
        ``asyncio.sleep``, looked up at call time so tests can patch it.
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
        avg_tokens_per_call: int = 1500,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] | None = None,
        failure_shrink_threshold: float = 0.20,
        min_in_flight: int = 1,
    ) -> None:
        self._max_in_flight = max_in_flight
        self._target_slots = max_in_flight
        self._min_in_flight = min_in_flight
        self._failure_shrink_threshold = failure_shrink_threshold
        self._avg_tokens_per_call = avg_tokens_per_call
        self._now = now
        self._sleep = sleep

        self._requests_per_min = requests_per_min
        self._tokens_per_min = tokens_per_min

        # Semaphore initialized to max_in_flight
        self._semaphore = asyncio.Semaphore(max_in_flight)

        # Token buckets
        self._rpm_bucket = TokenBucket(requests_per_min, now=now)
        self._tpm_bucket = TokenBucket(tokens_per_min, now=now)

        # Shrink tracking: how many semaphore tokens to drain without releasing
        self._shrink_pending: int = 0

        self._in_flight: int = 0  # active call count (informational)
        # One cooldown shared by every caller after a 429 (docs/DECISIONS.md#adr-cloud-retry).
        self._cooldown_until: float = float("-inf")

    # ------------------------------------------------------------------
    # ConcurrencyController protocol
    # ------------------------------------------------------------------

    async def acquire(self) -> None:
        """Claim an in-flight slot, wait out any shared cooldown, then pace via RPM + TPM.

        If a shrink is pending, the caller first claims it (decrements
        ``_shrink_pending``) and takes one semaphore token, which stays held
        back for good, then acquires its own slot in the same call. A caller
        cancelled while waiting for that token hands the claim back; one
        cancelled while pacing returns its slot and refunds both bucket
        reservations, so a cancelled waiter never leaks a permit or tokens.
        """
        # Drain a pending shrink token first. Claim the shrink before waiting so
        # two concurrent callers never both drain it; if this caller is
        # cancelled before the token is taken, hand the claim back
        # (docs/DECISIONS.md#adr-governor).
        if self._shrink_pending > 0:
            self._shrink_pending -= 1
            try:
                await self._semaphore.acquire()
            except BaseException:
                self._shrink_pending += 1
                raise
            # This token is now permanently held back; acquire the real slot next.

        await self._semaphore.acquire()
        self._in_flight += 1
        reserved_rpm = reserved_tpm = False
        try:
            # A 429 seen by any caller pauses everyone (docs/DECISIONS.md#adr-cloud-retry).
            await self._wait_for_cooldown()
            # Rate-limit: reserve estimated cost and wait if needed.
            rpm_wait = self._rpm_bucket.reserve(1)
            reserved_rpm = True
            tpm_wait = self._tpm_bucket.reserve(self._avg_tokens_per_call)
            reserved_tpm = True
            wait = max(rpm_wait, tpm_wait)
            if wait > 0:
                await self._pause(wait)
        except BaseException:
            # Cancelled (or interrupted) while pacing: the caller never gets the
            # slot, so return the permit and refund both reservations.
            if reserved_rpm:
                self._rpm_bucket.refund(1)
            if reserved_tpm:
                self._tpm_bucket.refund(self._avg_tokens_per_call)
            self._in_flight = max(0, self._in_flight - 1)
            self._semaphore.release()
            raise

    def release(self, *, success: bool = True, result_tokens: int | None = None) -> None:
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
        # TPM reconciliation. acquire() always reserved avg_tokens_per_call
        # upfront. Three cases when TPM is enforced:
        if self._tokens_per_min is not None:
            if result_tokens is not None:
                # Actual usage known → reconcile estimate vs actual.
                # delta > 0 → over-reserved → refund; delta < 0 → under-reserved → take more
                self._tpm_bucket.refund(self._avg_tokens_per_call - result_tokens)
            elif not success:
                # FAILED call produced no output → refund the full reservation
                # so a failure can't permanently burn avg_tokens_per_call and
                # drive the bucket into a deficit it never recovers from (F-11).
                self._tpm_bucket.refund(self._avg_tokens_per_call)
            # else: SUCCESS but the provider/proxy omitted usage data
            # (result_tokens is None). Keep the upfront avg reservation rather
            # than refunding it — the call DID spend tokens, so refunding would
            # under-count TPM and under-throttle, risking 429s on the very
            # gateways that drop the usage block.

        self._semaphore.release()
        self._in_flight = max(0, self._in_flight - 1)

    def report_wave_failures(self, success_count: int, failure_count: int) -> None:
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
        if failure_rate >= self._failure_shrink_threshold and self._target_slots > self._min_in_flight:
            self._target_slots -= 1
            self._shrink_pending += 1
            log.info(
                "rate_limit_slots_shrunk",
                failure_rate_percent=round(failure_rate * 100, 1),
                threshold_percent=round(self._failure_shrink_threshold * 100, 1),
                target_slots=self._target_slots,
                shrink_pending=self._shrink_pending,
            )

    async def start_monitoring(self) -> None:
        """No-op: the cloud controller has nothing to poll (ConcurrencyController protocol)."""

    async def stop_monitoring(self) -> None:
        """No-op counterpart of ``start_monitoring``."""

    async def __aenter__(self) -> RateLimitController:
        """Acquire a concurrency slot (async context manager entry)."""
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the slot with the call's real outcome (failed calls refund TPM)."""
        self.release(success=exc_type is None)

    # ------------------------------------------------------------------
    # RetryGate (docs/DECISIONS.md#adr-cloud-retry)
    # ------------------------------------------------------------------

    def note_rate_limited(self, seconds: float) -> None:
        """A 429 anywhere pauses every caller; concurrent 429s merge (max, never sum)."""
        until = self._now() + max(0.0, seconds)
        if until > self._cooldown_until:
            self._cooldown_until = until
            log.info("rate_limit_cooldown_set", cooldown_s=round(seconds, 2))

    async def before_retry(self) -> None:
        """A retry is a new request: wait out any cooldown, then take a fresh RPM token."""
        await self._wait_for_cooldown()
        wait = self._rpm_bucket.reserve(1)
        if wait > 0:
            try:
                await self._pause(wait)
            except BaseException:
                self._rpm_bucket.refund(1)
                raise

    @property
    def cooldown_remaining(self) -> float:
        """Seconds left in the shared cooldown (0 when none)."""
        return max(0.0, self._cooldown_until - self._now())

    async def _wait_for_cooldown(self) -> None:
        """Sleep until the shared cooldown ends; re-check, since another 429 may extend it."""
        while (remaining := self._cooldown_until - self._now()) > 0:
            await self._pause(remaining)

    async def _pause(self, seconds: float) -> None:
        if self._sleep is not None:
            await self._sleep(seconds)
        else:
            await asyncio.sleep(seconds)
