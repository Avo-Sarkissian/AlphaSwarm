"""Behavioral governor tests driven by scripted memory readings.

The real monitor loop and state machine run; only the memory source is scripted
through ResourceGovernor(monitor=...). Known governor defects are pinned as strict
xfails (docs/DECISIONS.md#adr-governor).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alphaswarm.batch_dispatcher import dispatch_wave
from alphaswarm.config import GovernorSettings
from alphaswarm.errors import GovernorCrisisError
from alphaswarm.governor import GovernorState, ResourceGovernor, TokenPool
from alphaswarm.inference.types import ProviderRole
from alphaswarm.memory_monitor import MemoryReading, PressureLevel
from alphaswarm.worker import WorkerPersonaConfig
from tests.inference.fakes import FakeInferenceProvider
from tests.support.aio import eventually
from tests.support.monitor import ScriptedMonitor, fast_governor_settings, reading

GREEN = reading(50.0)
PAUSE = reading(92.0)
YELLOW = reading(50.0, PressureLevel.YELLOW)

MakeGovernor = Callable[..., tuple[ResourceGovernor, ScriptedMonitor]]


@pytest.fixture
async def make_governor() -> AsyncIterator[MakeGovernor]:
    """Build governors on stepwise scripted monitors and always shut them down."""
    created: list[ResourceGovernor] = []

    def _make(
        items: Sequence[MemoryReading | BaseException], **overrides: Any
    ) -> tuple[ResourceGovernor, ScriptedMonitor]:
        monitor = ScriptedMonitor(items, repeat_last=False)
        gov = ResourceGovernor(fast_governor_settings(**overrides), monitor=monitor)
        created.append(gov)
        return gov, monitor

    yield _make
    for gov in created:
        with contextlib.suppress(GovernorCrisisError):
            await gov.stop_monitoring()
        # A monitor that died keeps its exception on the task; one public acquire()
        # retrieves it through the fail-fast path, so asyncio does not log
        # "Task exception was never retrieved".
        try:
            await gov.acquire()
        except GovernorCrisisError:
            continue
        gov.release()


async def _cancel(*tasks: asyncio.Task[Any]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, GovernorCrisisError):
            await task


async def _turns(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def test_pause_blocks_new_acquirers_until_pressure_drops(
    make_governor: MakeGovernor,
) -> None:
    gov, monitor = make_governor([GREEN], baseline_parallel=2)
    await gov.start_monitoring()
    await eventually(lambda: monitor.reads == 1, what="first reading")
    monitor.push(PAUSE)
    await eventually(lambda: gov.state is GovernorState.PAUSED, what="PAUSED")
    newcomer = asyncio.create_task(gov.acquire())
    try:
        await _turns()
        assert not newcomer.done(), "acquire() must block while PAUSED"
        monitor.push(GREEN)
        await eventually(newcomer.done, what="acquire after pressure drops")
        assert gov.state is GovernorState.RUNNING
        assert gov.active_count == 1
    finally:
        await _cancel(newcomer)


@pytest.mark.xfail(
    strict=True,
    reason="T1.4: a waiter already queued on the TokenPool starts while PAUSED (fix: plan 18)",
)
async def test_queued_waiter_does_not_start_while_paused(make_governor: MakeGovernor) -> None:
    gov, monitor = make_governor([GREEN], baseline_parallel=1)
    await gov.start_monitoring()
    await eventually(lambda: monitor.reads == 1, what="first reading")
    await gov.acquire()  # the only slot
    queued = asyncio.create_task(gov.acquire())  # passes the resume gate, waits on the pool
    try:
        await _turns(5)
        assert not queued.done()
        monitor.push(PAUSE)
        await eventually(lambda: gov.state is GovernorState.PAUSED, what="PAUSED")
        gov.release()  # frees the slot while PAUSED
        await _turns()
        assert not queued.done(), "a queued waiter started while the governor was PAUSED"
    finally:
        await _cancel(queued)


async def test_crisis_abort_raises_in_a_waiter_blocked_on_the_resume_gate(
    make_governor: MakeGovernor,
) -> None:
    gov, monitor = make_governor([YELLOW], baseline_parallel=1, crisis_timeout_seconds=-1.0)
    await gov.start_monitoring()
    await eventually(lambda: gov.state is GovernorState.CRISIS, what="CRISIS")
    waiter = asyncio.create_task(gov.acquire())
    try:
        await _turns(5)
        assert not waiter.done()
        monitor.push(YELLOW)  # the crisis timeout (forced to -1 s) has elapsed: abort
        await eventually(waiter.done, what="waiter to fail after the crisis abort")
        assert isinstance(waiter.exception(), GovernorCrisisError)
        with pytest.raises(GovernorCrisisError):
            await gov.acquire()  # newcomers fail fast too
    finally:
        await _cancel(waiter)


@pytest.mark.xfail(
    strict=True,
    reason="T1.4: a crisis abort never reaches waiters queued on the TokenPool (fix: plan 18)",
)
async def test_crisis_abort_raises_in_every_queued_waiter(make_governor: MakeGovernor) -> None:
    gov, monitor = make_governor([GREEN], baseline_parallel=2, crisis_timeout_seconds=-1.0)
    await gov.start_monitoring()
    await eventually(lambda: monitor.reads == 1, what="first reading")
    await gov.acquire()
    await gov.acquire()
    queued = asyncio.create_task(gov.acquire())
    try:
        await _turns(5)
        monitor.push(YELLOW)
        await eventually(lambda: gov.state is GovernorState.CRISIS, what="CRISIS")
        monitor.push(YELLOW)
        await eventually(lambda: monitor.reads == 3, what="abort reading consumed")
        await eventually(queued.done, what="queued waiter to fail after the crisis abort")
        assert isinstance(queued.exception(), GovernorCrisisError)
    finally:
        await _cancel(queued)


@pytest.mark.xfail(
    strict=True,
    reason="T1.4: stop_monitoring() swallows a fatal monitor error (fix: plan 18)",
)
async def test_stop_monitoring_reraises_a_fatal_monitor_error(
    make_governor: MakeGovernor,
) -> None:
    gov, monitor = make_governor([RuntimeError("sysctl exploded")], baseline_parallel=1)
    await gov.start_monitoring()
    await eventually(lambda: monitor.reads == 1, what="failing read")
    with pytest.raises(GovernorCrisisError):
        await gov.stop_monitoring()


@pytest.mark.xfail(
    strict=True,
    reason="T1.4: PAUSED never escalates to CRISIS, so a stuck reading wedges a round (fix: plan 18)",
)
async def test_paused_escalates_to_crisis_after_the_timeout(make_governor: MakeGovernor) -> None:
    gov, monitor = make_governor([PAUSE], baseline_parallel=1, crisis_timeout_seconds=-1.0)
    await gov.start_monitoring()
    await eventually(lambda: gov.state is GovernorState.PAUSED, what="PAUSED")
    monitor.push(PAUSE)
    await eventually(lambda: monitor.reads == 2, what="second pause reading")
    await eventually(lambda: gov.state is GovernorState.CRISIS, what="escalation to CRISIS")


@pytest.mark.xfail(
    strict=True,
    reason="T1.4: crisis recovery snaps straight to baseline instead of ramping by slot_adjustment_step (fix: plan 18)",
)
async def test_crisis_recovery_ramps_toward_baseline_by_adjustment_step(
    make_governor: MakeGovernor,
) -> None:
    gov, monitor = make_governor([YELLOW], baseline_parallel=8, max_parallel=16)
    await gov.start_monitoring()
    await eventually(lambda: gov.state is GovernorState.CRISIS, what="CRISIS")
    assert gov.current_limit == 1
    monitor.push(GREEN)
    await eventually(lambda: gov.state is not GovernorState.CRISIS, what="crisis exit")
    assert gov.current_limit < 8, "crisis exit jumped straight back to the baseline"
    assert gov.current_limit <= 1 + GovernorSettings().slot_adjustment_step


async def test_shrink_holds_new_starts_until_in_flight_work_drains(
    make_governor: MakeGovernor,
) -> None:
    gov, monitor = make_governor([GREEN], baseline_parallel=4)
    await gov.start_monitoring()
    await eventually(lambda: monitor.reads == 1, what="first reading")
    for _ in range(4):
        await gov.acquire()
    waiter = asyncio.create_task(gov.acquire())  # queued on the pool while RUNNING
    try:
        await _turns(5)
        monitor.push(YELLOW)  # CRISIS: limit 4 -> 1 while 4 slots are checked out
        await eventually(lambda: gov.state is GovernorState.CRISIS, what="CRISIS")
        assert gov.current_limit == 1
        for _ in range(3):
            gov.release()  # in-flight work drains from 4 to 1
        await _turns()
        assert not waiter.done(), "a new start slipped in above the shrunken limit"
    finally:
        await _cancel(waiter)


async def test_dead_monitor_surfaces_through_dispatch_wave(
    make_governor: MakeGovernor, sample_personas: list[WorkerPersonaConfig]
) -> None:
    gov, monitor = make_governor([RuntimeError("sysctl exploded")], baseline_parallel=2)
    await gov.start_monitoring()
    await eventually(lambda: monitor.reads == 1, what="failing read")
    provider = FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=[])
    zero_jitter = GovernorSettings(jitter_min_seconds=0.0, jitter_max_seconds=0.0)
    with pytest.raises(GovernorCrisisError):
        await dispatch_wave(
            personas=sample_personas,
            governor=gov,
            provider=provider,
            user_message="seed",
            settings=zero_jitter,
        )
    assert provider.calls == []


@settings(max_examples=200, deadline=None)
@given(
    initial=st.integers(min_value=1, max_value=8),
    ops=st.lists(
        st.tuples(
            st.sampled_from(["acquire", "release", "grow", "shrink"]),
            st.integers(min_value=1, max_value=4),
        ),
        max_size=60,
    ),
)
def test_token_pool_never_admits_more_than_its_limit(initial: int, ops: list[tuple[str, int]]) -> None:
    """Resizing never lets effective in-flight work exceed current_limit."""

    async def _drive() -> None:
        pool = TokenPool(initial)
        checked_out = 0
        for op, amount in ops:
            if op == "acquire" and pool.available > 0:
                await pool.acquire()
                checked_out += 1
            elif op == "release" and checked_out > 0:
                pool.release()
                checked_out -= 1
            elif op == "grow":
                pool.grow(amount)
            elif op == "shrink":
                step = min(amount, pool.current_limit - 1)
                if step > 0:
                    pool.shrink(step)
            effective = checked_out - pool.debt
            assert effective <= pool.current_limit
            assert pool.available == pool.current_limit - effective

    # A private loop on purpose: asyncio.run() would also clear the thread's current
    # event loop, orphaning the one pytest-asyncio installed; that loop then leaks as an
    # unclosed socket and fails a later test under filterwarnings = error.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive())
    finally:
        loop.close()
