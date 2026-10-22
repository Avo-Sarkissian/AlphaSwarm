"""Tests for batch dispatch via asyncio.TaskGroup with jitter and failure tracking."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.config import GovernorSettings
from alphaswarm.errors import (
    AuthError,
    BudgetExceededError,
    GovernorCrisisError,
    InferenceError,
    OllamaInferenceError,
)
from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import WorkerPersonaConfig
from tests.inference.fakes import FakeInferenceProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_BUY_JSON = (
    '{"signal": "buy", "confidence": 0.8, "sentiment": 0.4, '
    '"rationale": "strong momentum", "cited_agents": []}'
)


def _fake_provider(content: str = _VALID_BUY_JSON, *, n: int = 1000) -> FakeInferenceProvider:
    """Return a FakeInferenceProvider scripted with n identical results.

    Default n=1000 is a generous upper bound for batch tests so the scripted
    list is never exhausted by a 4-100 persona wave.
    """
    scripted = [
        InferenceResult(
            content=content,
            model="fake-model",
            eval_count=50,
            eval_duration_ns=1_000_000_000,
        )
        for _ in range(n)
    ]
    return FakeInferenceProvider(
        role=ProviderRole.WORKER,
        model="fake-model",
        scripted=scripted,
    )


def _fake_provider_with_metadata() -> FakeInferenceProvider:
    """Like _fake_provider() but returns a full result with rationale for ITEM 4 tests."""
    content = (
        '{"signal": "buy", "confidence": 0.8, "sentiment": 0.4, '
        '"rationale": "strong buy", "cited_agents": []}'
    )
    return _fake_provider(content=content)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def governor() -> ResourceGovernor:
    """ResourceGovernor with default settings for batch tests."""
    return ResourceGovernor(GovernorSettings(baseline_parallel=16))


@pytest.fixture()
def sample_personas() -> list[WorkerPersonaConfig]:
    """4-persona list for batch dispatch tests."""
    return [
        WorkerPersonaConfig(
            agent_id="quants_01",
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt="test",
            risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="quants_02",
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt="test",
            risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="degens_01",
            bracket="degens",
            influence_weight=0.3,
            temperature=1.2,
            system_prompt="test",
            risk_profile="0.95",
        ),
        WorkerPersonaConfig(
            agent_id="degens_02",
            bracket="degens",
            influence_weight=0.3,
            temperature=1.2,
            system_prompt="test",
            risk_profile="0.95",
        ),
    ]


# ---------------------------------------------------------------------------
# dispatch_wave returns correct results
# ---------------------------------------------------------------------------


async def test_dispatch_wave_returns_list_of_decisions(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """dispatch_wave returns a list of AgentDecision, one per persona."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="AAPL rumor",
            settings=settings,
        )

    assert len(results) == len(sample_personas)
    assert all(isinstance(r, AgentDecision) for r in results)


async def test_dispatch_wave_accepts_persona_list_returns_decisions(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """dispatch_wave accepts list[WorkerPersonaConfig] and returns list[AgentDecision]."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=settings,
        )

    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, AgentDecision)


# ---------------------------------------------------------------------------
# Jitter
# ---------------------------------------------------------------------------


async def test_jitter_applied_before_dispatch(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """asyncio.sleep is called with jitter values in [0.5, 1.5] range."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))
    settings = GovernorSettings(baseline_parallel=16)
    sleep_values: list[float] = []

    async def capture_sleep(duration: float) -> None:
        sleep_values.append(duration)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", side_effect=capture_sleep):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=settings,
        )

    assert len(sleep_values) == len(sample_personas)
    for v in sleep_values:
        assert settings.jitter_min_seconds <= v <= settings.jitter_max_seconds


async def test_jitter_within_settings_range(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """Jitter values respect custom GovernorSettings jitter_min/max."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))
    settings = GovernorSettings(
        baseline_parallel=16, jitter_min_seconds=0.5, jitter_max_seconds=0.8
    )
    sleep_values: list[float] = []

    async def capture_sleep(duration: float) -> None:
        sleep_values.append(duration)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", side_effect=capture_sleep):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=settings,
        )

    for v in sleep_values:
        assert 0.5 <= v <= 0.8


# ---------------------------------------------------------------------------
# Partial failure -> PARSE_ERROR
# ---------------------------------------------------------------------------


async def test_partial_failure_produces_parse_error(
    governor: ResourceGovernor,
) -> None:
    """One agent raising OllamaInferenceError produces PARSE_ERROR; others succeed."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    personas = [
        WorkerPersonaConfig(
            agent_id="ok_01", bracket="quants", influence_weight=0.7,
            temperature=0.3, system_prompt="test", risk_profile="0.4",
        ),
        WorkerPersonaConfig(
            agent_id="fail_01", bracket="quants", influence_weight=0.7,
            temperature=0.3, system_prompt="test", risk_profile="0.4",
        ),
    ]

    call_count = 0

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OllamaInferenceError("test error", model="test")
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=2)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
            )

    parse_errors = [r for r in results if r.signal == SignalType.PARSE_ERROR]
    successes = [r for r in results if r.signal != SignalType.PARSE_ERROR]
    assert len(parse_errors) == 1
    assert len(successes) == 1


# ---------------------------------------------------------------------------
# Failure tracking -> governor.report_wave_failures
# ---------------------------------------------------------------------------


async def test_high_failure_rate_calls_report_wave_failures(
    governor: ResourceGovernor,
) -> None:
    """When >= 20% fail, governor.report_wave_failures is called."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    # 3 out of 10 fail = 30% > 20% threshold
    personas = [
        WorkerPersonaConfig(
            agent_id=f"agent_{i:02d}", bracket="quants", influence_weight=0.7,
            temperature=0.3, system_prompt="test", risk_profile="0.4",
        )
        for i in range(10)
    ]

    call_idx = 0

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        nonlocal call_idx
        call_idx += 1
        if call_idx <= 3:
            raise OllamaInferenceError("fail", model="test")
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=10)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(governor, "report_wave_failures") as mock_report:
            settings = GovernorSettings(baseline_parallel=16)

            with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
                await dispatch_wave(
                    personas=personas,
                    governor=governor,
                    provider=provider,
                    user_message="test",
                    settings=settings,
                )

            mock_report.assert_called_once_with(7, 3)


async def test_low_failure_rate_does_not_call_report(
    governor: ResourceGovernor,
) -> None:
    """When < 20% fail (1/10 = 10%), report_wave_failures is NOT called for shrinkage."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    personas = [
        WorkerPersonaConfig(
            agent_id=f"agent_{i:02d}", bracket="quants", influence_weight=0.7,
            temperature=0.3, system_prompt="test", risk_profile="0.4",
        )
        for i in range(10)
    ]

    call_idx = 0

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            raise OllamaInferenceError("fail", model="test")
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=10)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(governor, "report_wave_failures") as mock_report:
            settings = GovernorSettings(baseline_parallel=16)

            with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
                await dispatch_wave(
                    personas=personas,
                    governor=governor,
                    provider=provider,
                    user_message="test",
                    settings=settings,
                )

            # 1/10 = 10%, below 20% threshold; report is still called but
            # with 9 success and 1 failure, and the governor internally
            # decides NOT to shrink since 10% < 20%.
            # Per plan: governor.report_wave_failures is called when failure_count > 0
            mock_report.assert_called_once_with(9, 1)


async def test_zero_failures_does_not_call_report(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """When all agents succeed, report_wave_failures is NOT called."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))

    with patch.object(governor, "report_wave_failures") as mock_report:
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
            )

        mock_report.assert_not_called()


# ---------------------------------------------------------------------------
# GovernorCrisisError propagation
# ---------------------------------------------------------------------------


async def test_governor_crisis_error_propagates(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """GovernorCrisisError is NOT caught by _safe_agent_inference -- propagates out."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=GovernorCrisisError("crisis", duration_seconds=300.0)
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(GovernorCrisisError) as exc_info,
        ):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
            )

        # Unwrapped to the bare error; the TaskGroup group is kept as __cause__.
        assert isinstance(exc_info.value.__cause__, ExceptionGroup)


# ---------------------------------------------------------------------------
# CancelledError propagation (review concern #2)
# ---------------------------------------------------------------------------


async def test_cancelled_error_propagates(
    governor: ResourceGovernor,
) -> None:
    """asyncio.CancelledError is NOT caught as PARSE_ERROR -- propagates out."""
    from alphaswarm.batch_dispatcher import _safe_agent_inference

    persona = WorkerPersonaConfig(
        agent_id="test_01", bracket="quants", influence_weight=0.7,
        temperature=0.3, system_prompt="test", risk_profile="0.4",
    )

    provider = _fake_provider(n=1)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=asyncio.CancelledError()
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await _safe_agent_inference(
                persona=persona,
                governor=governor,
                provider=provider,
                user_message="test",
                peer_context=None,
                market_context=None,
                jitter_min=0.5,
                jitter_max=1.5,
            )


# ---------------------------------------------------------------------------
# KeyboardInterrupt propagation (review concern #2)
# ---------------------------------------------------------------------------


async def test_keyboard_interrupt_propagates(
    governor: ResourceGovernor,
) -> None:
    """KeyboardInterrupt is NOT caught as PARSE_ERROR -- propagates out."""
    from alphaswarm.batch_dispatcher import _safe_agent_inference

    persona = WorkerPersonaConfig(
        agent_id="test_01", bracket="quants", influence_weight=0.7,
        temperature=0.3, system_prompt="test", risk_profile="0.4",
    )

    provider = _fake_provider(n=1)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=KeyboardInterrupt()
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(KeyboardInterrupt),
        ):
            await _safe_agent_inference(
                persona=persona,
                governor=governor,
                provider=provider,
                user_message="test",
                peer_context=None,
                market_context=None,
                jitter_min=0.5,
                jitter_max=1.5,
            )


# ---------------------------------------------------------------------------
# TaskGroup usage verification
# ---------------------------------------------------------------------------


async def test_dispatch_wave_uses_task_group(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """dispatch_wave uses asyncio.TaskGroup (verified via source inspection)."""
    import inspect

    from alphaswarm.batch_dispatcher import dispatch_wave

    source = inspect.getsource(dispatch_wave)
    assert "TaskGroup" in source
    assert "tg.create_task" in source


# ---------------------------------------------------------------------------
# Phase 07 Task 1: Per-agent peer_contexts tests
# ---------------------------------------------------------------------------


async def test_dispatch_wave_per_agent_peer_contexts(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """dispatch_wave called with peer_contexts sends ctx_i to persona i."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    received_contexts: list[str | None] = []

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        received_contexts.append(peer_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)
        peer_contexts = ["ctx_0", "ctx_1", "ctx_2", "ctx_3"]

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
                peer_contexts=peer_contexts,
            )

    assert len(results) == 4
    # Each agent received its specific peer context
    assert set(received_contexts) == {"ctx_0", "ctx_1", "ctx_2", "ctx_3"}


async def test_dispatch_wave_peer_contexts_length_mismatch(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """peer_contexts list with wrong length raises ValueError (not assert)."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=2)
    settings = GovernorSettings(baseline_parallel=16)
    wrong_length_contexts = ["ctx_0", "ctx_1"]  # 2 != 4 personas

    with pytest.raises(ValueError, match="peer_contexts length"):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=settings,
            peer_contexts=wrong_length_contexts,
        )


async def test_dispatch_wave_peer_contexts_none_falls_back_to_scalar(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """When peer_contexts=None, uses peer_context scalar as before."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    received_contexts: list[str | None] = []

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        received_contexts.append(peer_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
                peer_context="shared_context",
                peer_contexts=None,
            )

    # All agents should have received the scalar peer_context
    assert all(c == "shared_context" for c in received_contexts)


# ---------------------------------------------------------------------------
# Phase 40 Plan 01: market_context plumbing tests (D-07 — same scalar for all)
# ---------------------------------------------------------------------------


async def test_dispatch_wave_forwards_market_context(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """Phase 40 D-07: dispatch_wave forwards the same market_context scalar to every agent."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    received_market_contexts: list[str | None] = []

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        received_market_contexts.append(market_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
                market_context="SHARED_MKT",
            )

    assert len(results) == 4
    # D-07: every agent gets the exact same market_context scalar
    assert len(received_market_contexts) == 4
    assert all(c == "SHARED_MKT" for c in received_market_contexts)


async def test_dispatch_wave_market_context_default_none(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """When market_context kwarg is omitted, dispatch_wave forwards None to every agent.

    Backward compatibility: callers that don't pass market_context should see None.
    """
    from alphaswarm.batch_dispatcher import dispatch_wave

    received_market_contexts: list[str | None] = []

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        received_market_contexts.append(market_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
            )

    assert len(results) == 4
    assert len(received_market_contexts) == 4
    assert all(c is None for c in received_market_contexts)


# ---------------------------------------------------------------------------
# Streaming per-agent state writes (debug session
# ws-agent-states-not-emitted-mid-sim, R2 fix)
# ---------------------------------------------------------------------------


async def test_safe_agent_inference_streams_state_on_success(
    governor: ResourceGovernor,
) -> None:
    """_safe_agent_inference writes agent state immediately upon success.

    Regression for debug session ws-agent-states-not-emitted-mid-sim (R2):
    per-agent state writes used to happen in a post-dispatch for-loop in
    simulation.py, leaving the WS broadcaster's agent_states dict empty for
    the entire 14-18min round window. The streaming write hook lives inside
    _safe_agent_inference so each agent's state lands the instant its
    inference resolves.
    """
    from alphaswarm.batch_dispatcher import _safe_agent_inference
    from alphaswarm.state import StateStore

    persona = WorkerPersonaConfig(
        agent_id="quants_42", bracket="quants", influence_weight=0.7,
        temperature=0.3, system_prompt="test", risk_profile="0.4",
    )
    store = StateStore()
    provider = _fake_provider(n=1)

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        return AgentDecision(signal=SignalType.BUY, confidence=0.84)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            decision = await _safe_agent_inference(
                persona=persona,
                governor=governor,
                provider=provider,
                user_message="test",
                peer_context=None,
                market_context=None,
                jitter_min=0.0,
                jitter_max=0.0,
                state_store=store,
            )

    # Decision returned correctly
    assert decision.signal == SignalType.BUY
    assert decision.confidence == 0.84

    # State was streamed to the store DURING _safe_agent_inference, not
    # after dispatch_wave returns.
    snap = store.snapshot()
    assert "quants_42" in snap.agent_states
    assert snap.agent_states["quants_42"].signal == SignalType.BUY
    assert snap.agent_states["quants_42"].confidence == 0.84


async def test_safe_agent_inference_streams_parse_error_on_inference_failure(
    governor: ResourceGovernor,
) -> None:
    """A failed agent is written as PARSE_ERROR at once.

    Keeping the prior round's signal (or the "thinking" placeholder) made
    failed agents pulse forever and counted them in the previous tally.
    """
    from alphaswarm.batch_dispatcher import _safe_agent_inference
    from alphaswarm.state import StateStore

    persona = WorkerPersonaConfig(
        agent_id="degens_07", bracket="degens", influence_weight=0.3,
        temperature=1.2, system_prompt="test", risk_profile="0.95",
    )
    store = StateStore()
    await store.update_agent_state("degens_07", SignalType.SELL, 0.6)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=OllamaInferenceError("boom", model="test")
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            decision = await _safe_agent_inference(
                persona=persona,
                governor=governor,
                provider=_fake_provider(n=1),
                user_message="test",
                peer_context=None,
                market_context=None,
                jitter_min=0.0,
                jitter_max=0.0,
                state_store=store,
            )

    assert decision.signal == SignalType.PARSE_ERROR
    state = store.snapshot().agent_states["degens_07"]
    assert state.signal == SignalType.PARSE_ERROR
    assert state.confidence == 0.0


async def test_safe_agent_inference_streams_parse_error_from_parse_fallback(
    governor: ResourceGovernor,
) -> None:
    """A tier-3 parse fallback (no exception) is written as PARSE_ERROR too."""
    from alphaswarm.batch_dispatcher import _safe_agent_inference
    from alphaswarm.state import StateStore

    persona = WorkerPersonaConfig(
        agent_id="macro_03", bracket="macro", influence_weight=0.5,
        temperature=0.5, system_prompt="test", risk_profile="0.5",
    )
    store = StateStore()

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        return AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            await _safe_agent_inference(
                persona=persona,
                governor=governor,
                provider=_fake_provider(n=1),
                user_message="test",
                peer_context=None,
                market_context=None,
                jitter_min=0.0,
                jitter_max=0.0,
                state_store=store,
            )

    assert store.snapshot().agent_states["macro_03"].signal == SignalType.PARSE_ERROR
    assert store.peek_rationales() == ()


async def test_dispatch_wave_streams_state_progressively(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """dispatch_wave (via _safe_agent_inference) writes per-agent state as
    each inference resolves — not in a post-dispatch batch loop.

    End-to-end check: after dispatch_wave returns, every successful agent's
    state is in the StateStore, sourced from the streaming hook inside
    _safe_agent_inference (the post-dispatch for-loop in simulation.py is
    intentionally removed by this fix).
    """
    from alphaswarm.batch_dispatcher import dispatch_wave
    from alphaswarm.state import StateStore

    store = StateStore()
    provider = _fake_provider(n=len(sample_personas))

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
        **_: object,
    ) -> AgentDecision:
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
                state_store=store,
            )

    snap = store.snapshot()
    # All 4 sample personas should have been streamed into the store
    expected_ids = {p["agent_id"] for p in sample_personas}
    assert set(snap.agent_states.keys()) == expected_ids
    for aid in expected_ids:
        assert snap.agent_states[aid].signal == SignalType.BUY
        assert snap.agent_states[aid].confidence == 0.8


# ITEM 4 of quick task 260512-jqn — streaming push_rationale per-agent
# ---------------------------------------------------------------------------


async def test_safe_agent_inference_streams_rationale_push_on_success(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """ITEM 4: after a successful inference, one RationaleEntry must land
    in state_store.push_rationale BEFORE _safe_agent_inference returns.

    Without this, the rationale feed would only populate at end of round —
    the streaming path inside batch_dispatcher avoids that mid-round blackout.
    """
    from alphaswarm.batch_dispatcher import dispatch_wave
    from alphaswarm.state import RationaleEntry, StateStore

    store = StateStore()
    provider = _fake_provider_with_metadata()
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="seed",
            settings=settings,
            state_store=store,
            round_num=2,
        )

    # One success per persona → one rationale per agent in the window.
    successful = [r for r in results if r.signal is not SignalType.PARSE_ERROR]
    rationales = store.peek_rationales()
    assert len(rationales) == len(successful)

    # All pushed entries must be RationaleEntry objects with round_num=2.
    assert all(isinstance(e, RationaleEntry) for e in rationales)
    assert all(e.round_num == 2 for e in rationales)

    # Each successful agent has exactly one entry; no duplicates.
    pushed_ids = sorted(e.agent_id for e in rationales)
    expected_ids = sorted(p["agent_id"] for p in sample_personas)
    assert pushed_ids == expected_ids


async def test_safe_agent_inference_skips_rationale_on_parse_error(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """ITEM 4: PARSE_ERROR decisions must NOT push a rationale entry.

    The error case is the fallback AgentDecision returned by the exception
    handler — pushing its placeholder rationale would pollute the feed with
    'Inference failed for…' noise. Streaming push is gated on
    `decision.signal is not SignalType.PARSE_ERROR`.
    """
    from alphaswarm.batch_dispatcher import dispatch_wave
    from alphaswarm.state import StateStore

    store = StateStore()
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=OllamaInferenceError("simulated failure", model="fake-model")
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=_fake_provider(n=len(sample_personas)),
                user_message="seed",
                settings=settings,
                state_store=store,
                round_num=1,
            )

    # All decisions failed.
    assert all(r.signal is SignalType.PARSE_ERROR for r in results)
    # ⇒ ZERO rationale entries pushed.
    assert store.peek_rationales() == ()
    # ⇒ but every failed agent IS visible in state as PARSE_ERROR.
    states = store.snapshot().agent_states
    assert {aid for aid, s in states.items() if s.signal == SignalType.PARSE_ERROR} == {
        p["agent_id"] for p in sample_personas
    }


async def test_safe_agent_inference_no_push_when_state_store_none(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """When state_store is None, streaming is a silent no-op (no crash)."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="seed",
            settings=settings,
            state_store=None,
            round_num=1,
        )

    assert len(results) == len(sample_personas)


# ---------------------------------------------------------------------------
# Task 14: BudgetExceededError propagation
# ---------------------------------------------------------------------------


async def test_budget_exceeded_error_propagates(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """BudgetExceededError is NOT caught by _safe_agent_inference -- propagates out.

    When the spend cap trips, dispatch_wave must halt cleanly (completed rounds
    already persisted) rather than silently converting agents into PARSE_ERRORs.
    Matches the GovernorCrisisError propagation pattern: dispatch_wave raises it
    bare (unwrapped from the TaskGroup's ExceptionGroup).
    """
    from decimal import Decimal

    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=BudgetExceededError(Decimal("5"), Decimal("4"))
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(BudgetExceededError) as exc_info,
        ):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
            )

    # Unwrapped to the bare error; the TaskGroup group is kept as __cause__.
    assert isinstance(exc_info.value.__cause__, ExceptionGroup)


# ---------------------------------------------------------------------------
# AuthError fail-fast propagation
# ---------------------------------------------------------------------------


async def test_auth_error_is_inference_error_subclass() -> None:
    """Confirm AuthError IS-A InferenceError so the bug (being swallowed) is
    reproducible pre-fix and the fix is non-trivial."""
    assert issubclass(AuthError, InferenceError)


async def test_auth_error_propagates_not_parse_error(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """AuthError raised by an InferenceProvider must propagate out of
    dispatch_wave bare (unwrapped from the TaskGroup's ExceptionGroup), NOT be silently
    swallowed into PARSE_ERROR decisions.

    Pre-fix: AuthError was caught by `except Exception` (it IS-A InferenceError
    IS-A Exception) and all agents became PARSE_ERROR, burning every wave.
    Post-fix: AuthError is in the never-catch tuple and propagates immediately.
    """
    from alphaswarm.batch_dispatcher import dispatch_wave

    provider = _fake_provider(n=len(sample_personas))

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=AuthError(
                "Invalid API key — 401 Unauthorized",
                provider="openai",
                model="gpt-4o",
            )
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = GovernorSettings(baseline_parallel=16)

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(AuthError) as exc_info,
        ):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                provider=provider,
                user_message="test",
                settings=settings,
            )

    # Unwrapped to the bare error; the TaskGroup group is kept as __cause__.
    assert isinstance(exc_info.value.__cause__, ExceptionGroup)


# ---------------------------------------------------------------------------
# T1.1: a dead memory monitor stops the wave instead of yielding PARSE_ERRORs
# ---------------------------------------------------------------------------


async def test_dead_monitor_aborts_the_wave_with_governor_crisis(
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """Every agent hits GovernorCrisisError in acquire(); none reaches the model.

    dispatch_wave unwraps the TaskGroup's ExceptionGroup and raises the first
    GovernorCrisisError bare (docs/DECISIONS.md#adr-taskgroup-dispatch).
    """
    from alphaswarm.batch_dispatcher import dispatch_wave

    settings = GovernorSettings(baseline_parallel=4, check_interval_seconds=0.5)
    governor = ResourceGovernor(settings)
    governor._monitor = MagicMock()
    governor._monitor.read_combined = AsyncMock(side_effect=RuntimeError("sysctl died"))
    await governor.start_monitoring()
    assert governor._monitor_task is not None
    await asyncio.wait({governor._monitor_task})
    provider = _fake_provider(n=len(sample_personas))

    with (
        patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(GovernorCrisisError) as exc_info,
    ):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=settings,
        )

    group = exc_info.value.__cause__
    assert isinstance(group, ExceptionGroup)
    assert all(isinstance(e, GovernorCrisisError) for e in group.exceptions)
    assert provider.calls == []
    await governor.stop_monitoring()


async def test_inference_exception_becomes_inference_error_kind(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    from alphaswarm.batch_dispatcher import dispatch_wave

    def _boom(**_: object) -> InferenceResult:
        raise RuntimeError("connection refused by the model server")

    provider = FakeInferenceProvider(
        role=ProviderRole.WORKER, model="fake-model", scripted=_boom,
    )
    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=GovernorSettings(baseline_parallel=16),
        )
    assert {r.signal for r in results} == {SignalType.PARSE_ERROR}
    assert {r.error_kind for r in results} == {"inference"}


async def test_several_hard_stops_raise_only_the_first_bare(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    from decimal import Decimal

    from alphaswarm.batch_dispatcher import dispatch_wave

    def _over_budget(**_: object) -> InferenceResult:
        raise BudgetExceededError(Decimal("5"), Decimal("4"))

    provider = FakeInferenceProvider(
        role=ProviderRole.WORKER, model="fake-model", scripted=_over_budget,
    )
    with (
        patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(BudgetExceededError) as exc_info,
    ):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            provider=provider,
            user_message="test",
            settings=GovernorSettings(baseline_parallel=16),
        )
    group = exc_info.value.__cause__
    assert isinstance(group, ExceptionGroup)
    assert all(isinstance(e, BudgetExceededError) for e in group.exceptions)


# ---------------------------------------------------------------------------
# Own priors per agent, fast track (docs/DECISIONS.md#adr-diverse-peer-context)
# ---------------------------------------------------------------------------


def _ft_personas(ids: list[str]) -> list[WorkerPersonaConfig]:
    return [
        WorkerPersonaConfig(
            agent_id=agent_id,
            bracket="quants",
            influence_weight=0.7,
            temperature=0.3,
            system_prompt=f"persona {agent_id}",
            risk_profile="0.4",
        )
        for agent_id in ids
    ]


def _ft_recording_provider(seen: dict[str, str]) -> FakeInferenceProvider:
    def respond(*, messages: list[dict[str, str]], **_: object) -> InferenceResult:
        persona = next(m["content"] for m in messages if m["role"] == "system")
        seen[persona.removeprefix("persona ")] = messages[-1]["content"]
        return InferenceResult(content=_VALID_BUY_JSON, model="fake-model")

    return FakeInferenceProvider(role=ProviderRole.WORKER, model="fake-model", scripted=respond)


async def test_ft_dispatch_wave_routes_own_priors(governor: ResourceGovernor) -> None:
    from alphaswarm.batch_dispatcher import dispatch_wave

    seen: dict[str, str] = {}
    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        await dispatch_wave(
            personas=_ft_personas(["quants_01", "quants_02"]),
            governor=governor,
            provider=_ft_recording_provider(seen),
            user_message="shared rumor",
            settings=GovernorSettings(baseline_parallel=16),
            own_priors=["prior A", None],
        )

    assert seen == {"quants_01": "prior A\n\nshared rumor", "quants_02": "shared rumor"}


async def test_ft_dispatch_wave_rejects_misaligned_own_priors(governor: ResourceGovernor) -> None:
    from alphaswarm.batch_dispatcher import dispatch_wave

    with pytest.raises(ValueError, match="own_priors length 1 != personas length 2"):
        await dispatch_wave(
            personas=_ft_personas(["quants_01", "quants_02"]),
            governor=governor,
            provider=_ft_recording_provider({}),
            user_message="shared rumor",
            settings=GovernorSettings(baseline_parallel=16),
            own_priors=[None],
        )
