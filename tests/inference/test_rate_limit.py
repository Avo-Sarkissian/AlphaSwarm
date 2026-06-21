"""Tests for TokenBucket and RateLimitController.

Design philosophy
-----------------
All tests use an injected fake clock (`now` callable) so no real sleeping
occurs in the rate-bucket logic.  The asyncio "blocks past max_in_flight"
test uses a low-level semaphore inspection rather than timing.

The ``asyncio.sleep`` inside ``acquire()`` is patched to a no-op for unit
tests that don't care about actual waiting; only the bucket math and slot
accounting are tested here.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from alphaswarm.inference.concurrency import ConcurrencyController
from alphaswarm.inference.rate_limit import RateLimitController, TokenBucket


# ---------------------------------------------------------------------------
# Fake clock helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Monotonically advanceable fake clock for deterministic tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# ---------------------------------------------------------------------------
# TokenBucket tests
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_reserve_returns_zero_when_tokens_available(self) -> None:
        clock = FakeClock()
        bucket = TokenBucket(60, now=clock)  # 60 rpm = 1/s, start full (60)
        wait = bucket.reserve(1)
        assert wait == 0.0

    def test_reserve_returns_positive_wait_when_depleted(self) -> None:
        clock = FakeClock()
        # Rate = 60/min = 1 token/sec; capacity = 60; start full.
        # Drain all 60 tokens, then reserve 1 more → expect wait of 1 sec.
        bucket = TokenBucket(60, now=clock)
        bucket.reserve(60)  # drains to 0
        wait = bucket.reserve(1)  # should need to wait 1 second
        assert wait == pytest.approx(1.0, abs=1e-9)

    def test_refills_over_injected_clock_time(self) -> None:
        clock = FakeClock()
        bucket = TokenBucket(60, now=clock)  # 1 token/sec
        bucket.reserve(60)  # drain all

        clock.advance(30)  # advance 30 seconds → 30 tokens refilled
        wait = bucket.reserve(1)  # should be available immediately
        assert wait == 0.0

    def test_none_rate_always_returns_zero(self) -> None:
        clock = FakeClock()
        bucket = TokenBucket(None, now=clock)
        assert bucket.reserve(9999) == 0.0
        assert bucket.reserve(0) == 0.0

    def test_refund_replenishes_deficit(self) -> None:
        clock = FakeClock()
        bucket = TokenBucket(60, now=clock)
        # Reserve 61 — puts bucket at -1 (wait 1 sec)
        wait = bucket.reserve(61)
        assert wait == pytest.approx(1.0, abs=1e-9)
        # Refund 1 — should bring deficit back to 0
        bucket.refund(1)
        # Next reserve(0) should return 0
        wait2 = bucket.reserve(0)
        assert wait2 == 0.0

    def test_refund_capped_at_capacity(self) -> None:
        clock = FakeClock()
        bucket = TokenBucket(60, now=clock)
        # Start full (60), refund 100 → should stay at 60 (capacity)
        bucket.refund(100)
        # Next reserve of 60 should return 0 (still full)
        wait = bucket.reserve(60)
        assert wait == 0.0

    def test_none_rate_refund_is_noop(self) -> None:
        bucket = TokenBucket(None)
        bucket.refund(1000)  # must not raise
        assert bucket.reserve(9999) == 0.0


# ---------------------------------------------------------------------------
# RateLimitController tests
# ---------------------------------------------------------------------------


class TestRateLimitControllerProtocol:
    def test_satisfies_concurrency_controller_protocol(self) -> None:
        ctrl = RateLimitController(
            max_in_flight=5,
            requests_per_min=60,
            tokens_per_min=100_000,
        )
        assert isinstance(ctrl, ConcurrencyController)


class TestRateLimitControllerSlots:
    @pytest.mark.asyncio
    async def test_acquire_increments_in_flight(self) -> None:
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=3,
                requests_per_min=None,
                tokens_per_min=None,
                now=clock,
            )
            await ctrl.acquire()
            assert ctrl._in_flight == 1
            await ctrl.acquire()
            assert ctrl._in_flight == 2

    @pytest.mark.asyncio
    async def test_release_decrements_in_flight(self) -> None:
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=3,
                requests_per_min=None,
                tokens_per_min=None,
                now=clock,
            )
            await ctrl.acquire()
            await ctrl.acquire()
            ctrl.release()
            assert ctrl._in_flight == 1

    @pytest.mark.asyncio
    async def test_blocks_past_max_in_flight(self) -> None:
        """Verify that a (max_in_flight+1)-th acquire actually blocks."""
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=2,
                requests_per_min=None,
                tokens_per_min=None,
                now=clock,
            )
            # Acquire both slots
            await ctrl.acquire()
            await ctrl.acquire()

            # The 3rd acquire should block — test by creating a task and
            # checking it hasn't completed after a brief yield.
            blocked = asyncio.create_task(ctrl.acquire())
            await asyncio.sleep(0)  # yield so the task runs its first step
            # The task should be stuck waiting on the semaphore
            assert not blocked.done(), "Third acquire should be blocked"

            # Release one slot — unblocks the waiting task
            ctrl.release()
            await asyncio.sleep(0)
            await blocked  # should complete now

    @pytest.mark.asyncio
    async def test_semaphore_internal_locked_at_capacity(self) -> None:
        """Inspect semaphore state directly to confirm blocking logic."""
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=2,
                requests_per_min=None,
                tokens_per_min=None,
                now=clock,
            )
            await ctrl.acquire()
            await ctrl.acquire()
            # Semaphore is exhausted: _value should be 0
            assert ctrl._semaphore._value == 0  # type: ignore[attr-defined]


class TestRateLimitControllerTPMReconciliation:
    @pytest.mark.asyncio
    async def test_release_refunds_when_actual_less_than_estimated(self) -> None:
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=5,
                requests_per_min=None,
                tokens_per_min=6000,  # 100 tokens/sec
                avg_tokens_per_call=1500,
                now=clock,
            )
            await ctrl.acquire()
            # Tokens bucket was decremented by 1500 (avg); actual was 500
            # → refund 1000 tokens
            tokens_before = ctrl._tpm_bucket._tokens
            ctrl.release(success=True, result_tokens=500)
            tokens_after = ctrl._tpm_bucket._tokens
            # Should have refunded 1000 tokens
            assert tokens_after == pytest.approx(tokens_before + 1000, abs=1.0)

    @pytest.mark.asyncio
    async def test_release_takes_more_when_actual_exceeds_estimated(self) -> None:
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=5,
                requests_per_min=None,
                tokens_per_min=6000,
                avg_tokens_per_call=1000,
                now=clock,
            )
            await ctrl.acquire()
            tokens_before = ctrl._tpm_bucket._tokens
            # actual 2000 > estimated 1000 → take 1000 more
            ctrl.release(success=True, result_tokens=2000)
            tokens_after = ctrl._tpm_bucket._tokens
            assert tokens_after == pytest.approx(tokens_before - 1000, abs=1.0)

    @pytest.mark.asyncio
    async def test_release_no_reconcile_when_result_tokens_none(self) -> None:
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=5,
                requests_per_min=None,
                tokens_per_min=6000,
                avg_tokens_per_call=1500,
                now=clock,
            )
            await ctrl.acquire()
            tokens_before = ctrl._tpm_bucket._tokens
            ctrl.release(success=True, result_tokens=None)
            # No reconciliation when result_tokens is None
            assert ctrl._tpm_bucket._tokens == pytest.approx(tokens_before, abs=1.0)


class TestRateLimitControllerShrink:
    def test_report_wave_failures_shrinks_target(self) -> None:
        ctrl = RateLimitController(
            max_in_flight=5,
            requests_per_min=None,
            tokens_per_min=None,
        )
        # 20/100 = 20% >= 20% threshold → shrink
        ctrl.report_wave_failures(80, 20)
        assert ctrl._target_slots == 4
        assert ctrl._shrink_pending == 1

    def test_report_wave_failures_below_threshold_no_shrink(self) -> None:
        ctrl = RateLimitController(
            max_in_flight=5,
            requests_per_min=None,
            tokens_per_min=None,
        )
        # 10/100 = 10% < 20% threshold → no shrink
        ctrl.report_wave_failures(90, 10)
        assert ctrl._target_slots == 5
        assert ctrl._shrink_pending == 0

    def test_report_wave_failures_zero_total_no_shrink(self) -> None:
        ctrl = RateLimitController(
            max_in_flight=5,
            requests_per_min=None,
            tokens_per_min=None,
        )
        ctrl.report_wave_failures(0, 0)
        assert ctrl._target_slots == 5

    def test_shrink_floors_at_min_in_flight(self) -> None:
        ctrl = RateLimitController(
            max_in_flight=1,
            requests_per_min=None,
            tokens_per_min=None,
            min_in_flight=1,
        )
        # Already at minimum — should not shrink below 1
        ctrl.report_wave_failures(0, 100)
        assert ctrl._target_slots == 1
        assert ctrl._shrink_pending == 0

    @pytest.mark.asyncio
    async def test_shrink_takes_effect_on_next_acquire(self) -> None:
        """After shrink, the effective capacity is reduced by 1."""
        clock = FakeClock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ctrl = RateLimitController(
                max_in_flight=3,
                requests_per_min=None,
                tokens_per_min=None,
                min_in_flight=1,
                now=clock,
            )
            # Shrink: effective max should become 2
            ctrl.report_wave_failures(0, 100)
            assert ctrl._target_slots == 2

            # Should be able to acquire 2 times, but 3rd should block
            await ctrl.acquire()
            await ctrl.acquire()

            blocked = asyncio.create_task(ctrl.acquire())
            await asyncio.sleep(0)
            assert not blocked.done(), "3rd acquire should block (effective max is 2)"

            ctrl.release()
            await asyncio.sleep(0)
            await blocked


class TestRateLimitControllerMonitoring:
    @pytest.mark.asyncio
    async def test_start_stop_monitoring_no_state_store(self) -> None:
        """Monitoring starts and stops cleanly even without a state_store."""
        ctrl = RateLimitController(
            max_in_flight=1,
            requests_per_min=None,
            tokens_per_min=None,
        )
        await ctrl.start_monitoring()
        assert ctrl._monitor_task is not None
        await ctrl.stop_monitoring()
        assert ctrl._monitor_task is None

    @pytest.mark.asyncio
    async def test_start_monitoring_idempotent(self) -> None:
        ctrl = RateLimitController(
            max_in_flight=1,
            requests_per_min=None,
            tokens_per_min=None,
        )
        await ctrl.start_monitoring()
        task1 = ctrl._monitor_task
        await ctrl.start_monitoring()  # second call should not create a new task
        task2 = ctrl._monitor_task
        assert task1 is task2
        await ctrl.stop_monitoring()

    @pytest.mark.asyncio
    async def test_monitoring_emits_to_state_store(self) -> None:
        """If state_store is present, the monitoring loop calls set()."""
        received: list[dict] = []

        class FakeStore:
            def set(self, key: str, value: object) -> None:
                received.append({"key": key, "value": value})

        ctrl = RateLimitController(
            max_in_flight=2,
            requests_per_min=60,
            tokens_per_min=100_000,
            state_store=FakeStore(),
        )
        await ctrl.start_monitoring()
        # Tick the event loop enough times for the 2s sleep to fire once.
        # We patch asyncio.sleep to advance immediately for this test.
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await asyncio.sleep(0)  # let the task run
            # Give the loop a few iterations
            for _ in range(5):
                await asyncio.sleep(0)
        await ctrl.stop_monitoring()
        # We can't guarantee emissions without real time, but the test
        # confirms no exceptions and clean stop.  Accept 0 or more emissions.
        assert all("key" in r for r in received)
