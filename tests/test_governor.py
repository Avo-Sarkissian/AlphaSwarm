"""Tests for TokenPool, ResourceGovernor state machine, and StateStore integration."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.config import GovernorSettings
from alphaswarm.errors import GovernorCrisisError
from alphaswarm.governor import GovernorState, ResourceGovernor, TokenPool
from alphaswarm.memory_monitor import MemoryReading, PressureLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(
    psutil_percent: float = 50.0,
    pressure_level: PressureLevel = PressureLevel.GREEN,
) -> MemoryReading:
    """Create a MemoryReading with standard thresholds."""
    return MemoryReading(
        psutil_percent=psutil_percent,
        pressure_level=pressure_level,
        timestamp=time.monotonic(),
        throttle_threshold=80.0,
        pause_threshold=90.0,
        scale_up_threshold=60.0,
    )


# ---------------------------------------------------------------------------
# TokenPool tests
# ---------------------------------------------------------------------------


class TestTokenPool:
    """Test TokenPool: init, acquire, release, grow, shrink, debt pattern."""

    async def test_init_with_n_tokens(self) -> None:
        pool = TokenPool(4)
        assert pool.current_limit == 4
        assert pool.available == 4
        assert pool.debt == 0

    async def test_acquire_blocks_when_empty(self) -> None:
        pool = TokenPool(1)
        await pool.acquire()
        assert pool.available == 0

        # Second acquire should block (timeout to prove it)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(pool.acquire(), timeout=0.05)

    async def test_release_returns_token(self) -> None:
        pool = TokenPool(2)
        await pool.acquire()
        assert pool.available == 1
        pool.release()
        assert pool.available == 2

    async def test_grow_adds_tokens(self) -> None:
        pool = TokenPool(4)
        pool.grow(2)
        assert pool.current_limit == 6
        assert pool.available == 6

    async def test_shrink_removes_free_tokens(self) -> None:
        pool = TokenPool(4)
        removed = pool.shrink(2)
        assert removed == 2
        assert pool.current_limit == 2
        assert pool.available == 2

    async def test_shrink_when_all_checked_out_sets_debt(self) -> None:
        """When all tokens are checked out, shrink sets debt counter."""
        pool = TokenPool(4)
        # Acquire all 4 tokens
        for _ in range(4):
            await pool.acquire()
        assert pool.available == 0

        removed = pool.shrink(2)
        # Limit changes immediately, debt records deferred removal
        assert removed == 2
        assert pool.current_limit == 2
        assert pool.debt == 2

    async def test_release_with_debt_discards_token(self) -> None:
        """Debt pattern: release consumes debt instead of returning to pool."""
        pool = TokenPool(4)
        # Acquire all 4
        for _ in range(4):
            await pool.acquire()
        # Shrink by 2 (all checked out -> debt=2)
        pool.shrink(2)
        assert pool.debt == 2
        assert pool.current_limit == 2

        # Release 2 tokens: consumed by debt, not returned to pool
        pool.release()
        assert pool.debt == 1
        assert pool.available == 0

        pool.release()
        assert pool.debt == 0
        assert pool.available == 0

    async def test_release_after_debt_repaid_returns_normally(self) -> None:
        """After debt is fully repaid, subsequent releases return tokens to pool."""
        pool = TokenPool(4)
        for _ in range(4):
            await pool.acquire()
        pool.shrink(2)
        assert pool.debt == 2

        # Release 2: consumed by debt
        pool.release()
        pool.release()
        assert pool.debt == 0
        assert pool.available == 0

        # Release remaining 2: returned to pool normally
        pool.release()
        assert pool.available == 1
        pool.release()
        assert pool.available == 2
        assert pool.current_limit == 2

    async def test_shrink_partial_debt(self) -> None:
        """Shrink with some free and some checked out tokens."""
        pool = TokenPool(4)
        # Acquire 2, leave 2 free
        await pool.acquire()
        await pool.acquire()

        # Shrink by 3: 2 removed from free pool, 1 becomes debt
        removed = pool.shrink(3)
        assert removed == 3
        assert pool.current_limit == 1
        assert pool.debt == 1
        assert pool.available == 0


# ---------------------------------------------------------------------------
# ResourceGovernor basic tests
# ---------------------------------------------------------------------------


class TestResourceGovernorBasic:
    """Test ResourceGovernor initialization and basic acquire/release."""

    def test_init_state_running_at_baseline(self) -> None:
        settings = GovernorSettings()
        gov = ResourceGovernor(settings)
        assert gov.state == GovernorState.RUNNING
        assert gov.current_limit == 8
        assert gov.active_count == 0

    async def test_acquire_increments_active_count(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov.acquire()
        assert gov.active_count == 1

    async def test_release_success_true_decrements_active_count(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov.acquire()
        gov.release(success=True)
        assert gov.active_count == 0

    async def test_release_success_false_decrements_active_count(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov.acquire()
        gov.release(success=False)
        assert gov.active_count == 0

    async def test_release_default_success_true(self) -> None:
        """Backward compat: release() with no args defaults to success=True."""
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov.acquire()
        gov.release()  # no args
        assert gov.active_count == 0

    async def test_is_paused_false_when_running(self) -> None:
        settings = GovernorSettings()
        gov = ResourceGovernor(settings)
        assert gov.is_paused is False

    async def test_context_manager_backward_compat(self) -> None:
        """__aenter__/__aexit__ still work for backward compatibility."""
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        async with gov:
            assert gov.active_count == 1
        assert gov.active_count == 0


# ---------------------------------------------------------------------------
# State transition tests
# ---------------------------------------------------------------------------


class TestGovernorStateTransitions:
    """Test state machine transitions with mock MemoryMonitor."""

    async def test_running_to_throttled(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        reading = _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        await gov._apply_state_transition(reading)
        assert gov.state == GovernorState.THROTTLED

    async def test_running_to_paused(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        reading = _reading(psutil_percent=92.0, pressure_level=PressureLevel.GREEN)
        await gov._apply_state_transition(reading)
        assert gov.state == GovernorState.PAUSED
        assert gov.is_paused is True

    async def test_running_to_crisis_on_yellow(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        reading = _reading(psutil_percent=50.0, pressure_level=PressureLevel.YELLOW)
        await gov._apply_state_transition(reading)
        assert gov.state == GovernorState.CRISIS
        assert gov.is_paused is True

    async def test_running_to_crisis_on_red(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        reading = _reading(psutil_percent=50.0, pressure_level=PressureLevel.RED)
        await gov._apply_state_transition(reading)
        assert gov.state == GovernorState.CRISIS

    async def test_crisis_drops_to_1_slot(self) -> None:
        """D-13: Crisis entry drops current_limit to 1."""
        settings = GovernorSettings(baseline_parallel=8)
        gov = ResourceGovernor(settings)
        reading = _reading(pressure_level=PressureLevel.YELLOW)
        await gov._apply_state_transition(reading)
        assert gov.state == GovernorState.CRISIS
        assert gov.current_limit == 1

    async def test_crisis_to_recovering_on_green(self) -> None:
        """D-03: Crisis -> RECOVERING when green, resets to baseline."""
        settings = GovernorSettings(baseline_parallel=8)
        gov = ResourceGovernor(settings)
        # Enter crisis
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.YELLOW))
        assert gov.state == GovernorState.CRISIS
        assert gov.current_limit == 1

        # Green reading -> RECOVERING, reset to baseline
        await gov._apply_state_transition(_reading(psutil_percent=50.0))
        assert gov.state == GovernorState.RECOVERING
        assert gov.current_limit == 8

    async def test_recovering_to_running(self) -> None:
        """Recovery completes when baseline reached."""
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        # Enter crisis
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.RED))
        assert gov.state == GovernorState.CRISIS
        # Recover
        await gov._apply_state_transition(_reading(psutil_percent=50.0))
        assert gov.state == GovernorState.RECOVERING
        # Since recovery resets to baseline immediately, next green -> RUNNING
        await gov._apply_state_transition(_reading(psutil_percent=50.0))
        assert gov.state == GovernorState.RUNNING

    async def test_crisis_back_to_crisis_from_recovering(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.YELLOW))
        assert gov.state == GovernorState.CRISIS
        await gov._apply_state_transition(_reading(psutil_percent=50.0))
        assert gov.state == GovernorState.RECOVERING
        # Crisis again
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.RED))
        assert gov.state == GovernorState.CRISIS

    async def test_throttled_to_crisis(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        # Enter THROTTLED
        await gov._apply_state_transition(
            _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.THROTTLED
        # Then CRISIS
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.YELLOW))
        assert gov.state == GovernorState.CRISIS

    async def test_throttled_to_paused(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov._apply_state_transition(
            _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.THROTTLED
        await gov._apply_state_transition(
            _reading(psutil_percent=92.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.PAUSED

    async def test_throttled_back_to_running(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov._apply_state_transition(
            _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.THROTTLED
        await gov._apply_state_transition(
            _reading(psutil_percent=50.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.RUNNING

    async def test_paused_to_crisis(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov._apply_state_transition(
            _reading(psutil_percent=92.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.PAUSED
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.RED))
        assert gov.state == GovernorState.CRISIS

    async def test_paused_to_running_when_pressure_drops(self) -> None:
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)
        await gov._apply_state_transition(
            _reading(psutil_percent=92.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.PAUSED
        await gov._apply_state_transition(
            _reading(psutil_percent=50.0, pressure_level=PressureLevel.GREEN)
        )
        # Should go back to RUNNING (not throttled since below throttle threshold)
        assert gov.state == GovernorState.RUNNING


# ---------------------------------------------------------------------------
# Scale-up tests (D-02)
# ---------------------------------------------------------------------------


class TestGovernorScaleUp:
    """Test D-02: scale up above baseline after consecutive green checks."""

    async def test_scale_up_after_consecutive_green_checks(self) -> None:
        """3 consecutive Green checks under 60% -> grow by 2 above baseline."""
        settings = GovernorSettings(
            baseline_parallel=8,
            max_parallel=16,
            scale_up_consecutive_checks=3,
            slot_adjustment_step=2,
        )
        gov = ResourceGovernor(settings)
        assert gov.current_limit == 8

        low_reading = _reading(psutil_percent=40.0, pressure_level=PressureLevel.GREEN)
        # 3 consecutive eligible checks
        await gov._apply_state_transition(low_reading)
        await gov._apply_state_transition(low_reading)
        await gov._apply_state_transition(low_reading)
        assert gov.current_limit == 10  # 8 + 2

    async def test_scale_up_resets_on_non_eligible(self) -> None:
        """Consecutive counter resets when not scale_up_eligible."""
        settings = GovernorSettings(
            baseline_parallel=8,
            scale_up_consecutive_checks=3,
            slot_adjustment_step=2,
        )
        gov = ResourceGovernor(settings)
        low = _reading(psutil_percent=40.0, pressure_level=PressureLevel.GREEN)
        high = _reading(psutil_percent=70.0, pressure_level=PressureLevel.GREEN)

        await gov._apply_state_transition(low)
        await gov._apply_state_transition(low)
        # High reading resets counter
        await gov._apply_state_transition(high)
        await gov._apply_state_transition(low)
        await gov._apply_state_transition(low)
        # Only 2 consecutive, not 3
        assert gov.current_limit == 8

    async def test_scale_up_capped_at_max_parallel(self) -> None:
        """Scale up never exceeds max_parallel."""
        settings = GovernorSettings(
            baseline_parallel=8,
            max_parallel=10,
            scale_up_consecutive_checks=3,
            slot_adjustment_step=2,
        )
        gov = ResourceGovernor(settings)
        low = _reading(psutil_percent=40.0, pressure_level=PressureLevel.GREEN)

        # First scale-up: 8 -> 10
        for _ in range(3):
            await gov._apply_state_transition(low)
        assert gov.current_limit == 10

        # Second attempt: already at max, no change
        for _ in range(3):
            await gov._apply_state_transition(low)
        assert gov.current_limit == 10


# ---------------------------------------------------------------------------
# Crisis timeout tests (D-07, D-08)
# ---------------------------------------------------------------------------


class TestGovernorCrisisTimeout:
    """Test crisis timeout and reset behavior."""

    async def test_crisis_timeout_raises_error(self) -> None:
        """D-07: GovernorCrisisError after crisis_timeout_seconds with no successful inference."""
        settings = GovernorSettings(
            baseline_parallel=4,
            crisis_timeout_seconds=30.0,  # short for test
        )
        gov = ResourceGovernor(settings)

        # Set last_successful_inference far in the past
        gov._last_successful_inference = time.monotonic() - 60

        # Enter crisis
        await gov._apply_state_transition(_reading(pressure_level=PressureLevel.YELLOW))
        assert gov.state == GovernorState.CRISIS

        # Manually set crisis_start to far in the past
        gov._crisis_start = time.monotonic() - 60

        # Next crisis check should raise
        with pytest.raises(GovernorCrisisError) as exc_info:
            await gov._apply_state_transition(_reading(pressure_level=PressureLevel.YELLOW))
        assert exc_info.value.duration_seconds > 0

    async def test_crisis_timeout_reset_on_successful_release(self) -> None:
        """D-08: Successful release resets the crisis timeout clock."""
        settings = GovernorSettings(baseline_parallel=4, crisis_timeout_seconds=30.0)
        gov = ResourceGovernor(settings)

        before = gov._last_successful_inference
        await gov.acquire()
        gov.release(success=True)
        assert gov._last_successful_inference > before

    async def test_crisis_timeout_not_reset_on_failed_release(self) -> None:
        """Failed release does NOT reset the crisis timeout clock."""
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)

        initial = gov._last_successful_inference
        await gov.acquire()
        gov.release(success=False)
        assert gov._last_successful_inference == initial


# ---------------------------------------------------------------------------
# Wave failure / shrink tests (D-04, D-05)
# ---------------------------------------------------------------------------


class TestGovernorWaveFailures:
    """Test report_wave_failures shrink behavior."""

    async def test_shrink_on_high_failure_rate(self) -> None:
        """D-04: Failure rate >= 20% triggers shrink by slot_adjustment_step."""
        settings = GovernorSettings(
            baseline_parallel=8,
            slot_adjustment_step=2,
            batch_failure_threshold_percent=20.0,
        )
        gov = ResourceGovernor(settings)
        assert gov.current_limit == 8

        # 20% failure rate: 2 failures out of 10
        gov.report_wave_failures(success_count=8, failure_count=2)
        assert gov.current_limit == 6

    async def test_shrink_minimum_1_slot(self) -> None:
        """D-05: Governor never shrinks below 1 slot."""
        settings = GovernorSettings(
            baseline_parallel=2,
            slot_adjustment_step=4,
            batch_failure_threshold_percent=20.0,
        )
        gov = ResourceGovernor(settings)
        # Try to shrink below 1
        gov.report_wave_failures(success_count=1, failure_count=9)
        assert gov.current_limit >= 1

    async def test_no_shrink_on_low_failure_rate(self) -> None:
        """Below threshold failure rate does not shrink."""
        settings = GovernorSettings(
            baseline_parallel=8,
            batch_failure_threshold_percent=20.0,
        )
        gov = ResourceGovernor(settings)
        gov.report_wave_failures(success_count=9, failure_count=1)  # 10% < 20%
        assert gov.current_limit == 8


# ---------------------------------------------------------------------------
# GovernorState enum
# ---------------------------------------------------------------------------


class TestGovernorStateEnum:
    """Test GovernorState enum values."""

    def test_running_value(self) -> None:
        assert GovernorState.RUNNING.value == "running"

    def test_throttled_value(self) -> None:
        assert GovernorState.THROTTLED.value == "throttled"

    def test_paused_value(self) -> None:
        assert GovernorState.PAUSED.value == "paused"

    def test_crisis_value(self) -> None:
        assert GovernorState.CRISIS.value == "crisis"

    def test_recovering_value(self) -> None:
        assert GovernorState.RECOVERING.value == "recovering"


# ---------------------------------------------------------------------------
# State transition logging
# ---------------------------------------------------------------------------


class TestGovernorLogging:
    """Test that state transitions include reason in log output."""

    async def test_state_transition_logs_reason(self) -> None:
        """State transitions log old_state, new_state, and reason."""
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings)

        with patch("alphaswarm.governor.log") as mock_log:
            await gov._apply_state_transition(
                _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
            )
            # Verify warning was called with reason
            mock_log.warning.assert_called()
            call_kwargs = mock_log.warning.call_args
            # Check that keyword args contain old_state, new_state, reason
            assert "old_state" in call_kwargs.kwargs or any(
                "old_state" in str(a) for a in call_kwargs.args
            )
            assert "reason" in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# StateStore integration
# ---------------------------------------------------------------------------


class TestGovernorStateStore:
    """Test StateStore metric emission on state change."""

    async def test_state_store_update_governor_metrics_called(self) -> None:
        """Governor with state_store calls update_governor_metrics on state transition."""
        mock_store = MagicMock()
        mock_store.update_governor_metrics = MagicMock()

        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings, state_store=mock_store)

        await gov._apply_state_transition(
            _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        )
        mock_store.update_governor_metrics.assert_called_once()

    async def test_state_store_none_no_error(self) -> None:
        """Governor without state_store does not error on state transition."""
        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings, state_store=None)

        # Should not raise
        await gov._apply_state_transition(
            _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        )
        assert gov.state == GovernorState.THROTTLED

    async def test_state_store_metrics_have_correct_fields(self) -> None:
        """GovernorMetrics passed to state_store has expected fields."""
        mock_store = MagicMock()
        captured_metrics = []
        mock_store.update_governor_metrics = lambda m: captured_metrics.append(m)

        settings = GovernorSettings(baseline_parallel=4)
        gov = ResourceGovernor(settings, state_store=mock_store)

        await gov._apply_state_transition(
            _reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        )
        assert len(captured_metrics) == 1
        metrics = captured_metrics[0]
        assert hasattr(metrics, "current_slots")
        assert hasattr(metrics, "active_count")
        assert hasattr(metrics, "pressure_level")
        assert hasattr(metrics, "memory_percent")
        assert hasattr(metrics, "governor_state")
        assert hasattr(metrics, "timestamp")
        assert metrics.governor_state == "throttled"
        assert metrics.memory_percent == 85.0


# ---------------------------------------------------------------------------
# Monitoring lifecycle
# ---------------------------------------------------------------------------


class TestGovernorMonitoring:
    """Test start_monitoring/stop_monitoring lifecycle."""

    async def test_start_stop_monitoring(self) -> None:
        """Monitor loop starts and stops without error."""
        settings = GovernorSettings(baseline_parallel=4, check_interval_seconds=0.5)
        gov = ResourceGovernor(settings)

        # Mock the monitor's read_combined to return a benign reading
        gov._monitor = MagicMock()
        gov._monitor.read_combined = AsyncMock(return_value=_reading())

        await gov.start_monitoring()
        assert gov._monitor_task is not None

        await asyncio.sleep(0.1)
        await gov.stop_monitoring()


# ---------------------------------------------------------------------------
# ResourceGovernorProtocol compliance
# ---------------------------------------------------------------------------


class TestResourceGovernorProtocol:
    """Test that ResourceGovernor satisfies extended protocol."""

    def test_has_release_with_success_kwarg(self) -> None:
        settings = GovernorSettings()
        gov = ResourceGovernor(settings)
        import inspect

        sig = inspect.signature(gov.release)
        assert "success" in sig.parameters

    def test_has_is_paused_property(self) -> None:
        settings = GovernorSettings()
        gov = ResourceGovernor(settings)
        assert isinstance(type(gov).is_paused, property)
