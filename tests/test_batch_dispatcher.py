"""Tests for batch dispatch via asyncio.TaskGroup with jitter and failure tracking."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.config import GovernorSettings
from alphaswarm.errors import GovernorCrisisError, OllamaInferenceError
from alphaswarm.governor import ResourceGovernor
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import WorkerPersonaConfig


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


def _make_mock_client() -> MagicMock:
    """Create a mock OllamaClient with a chat() that returns valid JSON."""
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.message.content = '{"signal": "buy", "confidence": 0.8}'
    client.chat = AsyncMock(return_value=mock_response)
    return client


# ---------------------------------------------------------------------------
# dispatch_wave returns correct results
# ---------------------------------------------------------------------------


async def test_dispatch_wave_returns_list_of_decisions(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """dispatch_wave returns a list of AgentDecision, one per persona."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    client = _make_mock_client()
    settings = GovernorSettings(baseline_parallel=16)

    results = await dispatch_wave(
        personas=sample_personas,
        governor=governor,
        client=client,
        model="test-model",
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

    client = _make_mock_client()
    settings = GovernorSettings(baseline_parallel=16)

    results = await dispatch_wave(
        personas=sample_personas,
        governor=governor,
        client=client,
        model="test-model",
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

    client = _make_mock_client()
    settings = GovernorSettings(baseline_parallel=16)
    sleep_values: list[float] = []

    original_sleep = asyncio.sleep

    async def capture_sleep(duration: float) -> None:
        sleep_values.append(duration)
        # Don't actually sleep in tests

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", side_effect=capture_sleep):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            client=client,
            model="test-model",
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

    client = _make_mock_client()
    settings = GovernorSettings(baseline_parallel=16, jitter_min_seconds=0.5, jitter_max_seconds=0.8)
    sleep_values: list[float] = []

    async def capture_sleep(duration: float) -> None:
        sleep_values.append(duration)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", side_effect=capture_sleep):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            client=client,
            model="test-model",
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

    async def mock_infer(user_message: str, peer_context: str | None = None, market_context: str | None = None) -> AgentDecision:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OllamaInferenceError("test error", model="test")
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=personas,
                governor=governor,
                client=client,
                model="test-model",
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

    async def mock_infer(user_message: str, peer_context: str | None = None, market_context: str | None = None) -> AgentDecision:
        nonlocal call_idx
        call_idx += 1
        if call_idx <= 3:
            raise OllamaInferenceError("fail", model="test")
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(governor, "report_wave_failures") as mock_report:
            client = _make_mock_client()
            settings = GovernorSettings(baseline_parallel=16)

            with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
                await dispatch_wave(
                    personas=personas,
                    governor=governor,
                    client=client,
                    model="test-model",
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

    async def mock_infer(user_message: str, peer_context: str | None = None, market_context: str | None = None) -> AgentDecision:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            raise OllamaInferenceError("fail", model="test")
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(governor, "report_wave_failures") as mock_report:
            client = _make_mock_client()
            settings = GovernorSettings(baseline_parallel=16)

            with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
                await dispatch_wave(
                    personas=personas,
                    governor=governor,
                    client=client,
                    model="test-model",
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

    with patch.object(governor, "report_wave_failures") as mock_report:
        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
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

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=GovernorCrisisError("crisis", duration_seconds=300.0)
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ExceptionGroup) as exc_info,
        ):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
                user_message="test",
                settings=settings,
            )

        # GovernorCrisisError should be in the ExceptionGroup from TaskGroup
        crisis_errors = [
            e for e in exc_info.value.exceptions
            if isinstance(e, GovernorCrisisError)
        ]
        assert len(crisis_errors) > 0


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

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=asyncio.CancelledError()
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(asyncio.CancelledError),
        ):
            await _safe_agent_inference(
                persona=persona,
                governor=governor,
                client=client,
                model="test-model",
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

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=KeyboardInterrupt()
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()

        with (
            patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(KeyboardInterrupt),
        ):
            await _safe_agent_inference(
                persona=persona,
                governor=governor,
                client=client,
                model="test-model",
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

    async def mock_infer(user_message: str, peer_context: str | None = None, market_context: str | None = None) -> AgentDecision:
        received_contexts.append(peer_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)
        peer_contexts = ["ctx_0", "ctx_1", "ctx_2", "ctx_3"]

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
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

    client = _make_mock_client()
    settings = GovernorSettings(baseline_parallel=16)
    wrong_length_contexts = ["ctx_0", "ctx_1"]  # 2 != 4 personas

    with pytest.raises(ValueError, match="peer_contexts length"):
        await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            client=client,
            model="test-model",
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

    async def mock_infer(user_message: str, peer_context: str | None = None, market_context: str | None = None) -> AgentDecision:
        received_contexts.append(peer_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
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
    ) -> AgentDecision:
        received_market_contexts.append(market_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
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
    """When market_context kwarg is omitted, dispatch_wave forwards None to every agent (backward compat)."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    received_market_contexts: list[str | None] = []

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
    ) -> AgentDecision:
        received_market_contexts.append(market_context)
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            results = await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
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

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
    ) -> AgentDecision:
        return AgentDecision(signal=SignalType.BUY, confidence=0.84)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            decision = await _safe_agent_inference(
                persona=persona,
                governor=governor,
                client=client,
                model="test-model",
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


async def test_safe_agent_inference_does_not_stream_on_parse_error(
    governor: ResourceGovernor,
) -> None:
    """PARSE_ERROR results MUST NOT overwrite a prior signal in StateStore.

    If an agent's inference fails, we keep whatever was there before (the
    "thinking" placeholder from set_phase, or the prior round's signal) so
    the WS frame doesn't flip a failed agent into a misleading state.
    """
    from alphaswarm.batch_dispatcher import _safe_agent_inference
    from alphaswarm.state import StateStore

    persona = WorkerPersonaConfig(
        agent_id="degens_07", bracket="degens", influence_weight=0.3,
        temperature=1.2, system_prompt="test", risk_profile="0.95",
    )
    store = StateStore()
    # Pre-seed with a known prior-round signal
    await store.update_agent_state("degens_07", SignalType.SELL, 0.6)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_aw.return_value.__aenter__ = AsyncMock(
            side_effect=OllamaInferenceError("boom", model="test")
        )
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            decision = await _safe_agent_inference(
                persona=persona,
                governor=governor,
                client=client,
                model="test-model",
                user_message="test",
                peer_context=None,
                market_context=None,
                jitter_min=0.0,
                jitter_max=0.0,
                state_store=store,
            )

    assert decision.signal == SignalType.PARSE_ERROR

    # Prior-round signal must be preserved (not overwritten by PARSE_ERROR)
    snap = store.snapshot()
    assert snap.agent_states["degens_07"].signal == SignalType.SELL
    assert snap.agent_states["degens_07"].confidence == 0.6


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

    async def mock_infer(
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
    ) -> AgentDecision:
        return AgentDecision(signal=SignalType.BUY, confidence=0.8)

    with patch("alphaswarm.batch_dispatcher.agent_worker") as mock_aw:
        mock_worker = AsyncMock()
        mock_worker.infer = mock_infer
        mock_aw.return_value.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_aw.return_value.__aexit__ = AsyncMock(return_value=False)

        client = _make_mock_client()
        settings = GovernorSettings(baseline_parallel=16)

        with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
            await dispatch_wave(
                personas=sample_personas,
                governor=governor,
                client=client,
                model="test-model",
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


def _make_mock_client_with_metadata() -> MagicMock:
    """Like _make_mock_client but provides numeric eval_count/eval_duration so
    the worker.infer TPS code path doesn't crash on MagicMock comparison.

    ITEM 4 streams require state_store; worker.infer reads response.eval_count
    and response.eval_duration when state_store is non-None.
    """
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.message.content = (
        '{"signal": "buy", "confidence": 0.8, "rationale": "strong buy"}'
    )
    mock_response.eval_count = 50
    mock_response.eval_duration = 1_000_000_000  # 1 second in ns
    client.chat = AsyncMock(return_value=mock_response)
    return client


async def test_safe_agent_inference_streams_rationale_push_on_success(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """ITEM 4: after a successful inference, one RationaleEntry must land
    in state_store.push_rationale BEFORE _safe_agent_inference returns.

    Without this, the rationale feed only populates at end-of-round when
    simulation.py used to call _push_top_rationales — the new streaming
    path inside batch_dispatcher avoids that mid-round blackout.
    """
    from alphaswarm.batch_dispatcher import dispatch_wave
    from alphaswarm.state import RationaleEntry, StateStore

    store = StateStore()
    client = _make_mock_client_with_metadata()
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            client=client,
            model="test-model",
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

    # Build a client whose chat() always raises — _safe_agent_inference will
    # catch and return PARSE_ERROR AgentDecisions for every persona.
    failing_client = MagicMock()
    failing_client.chat = AsyncMock(
        side_effect=OllamaInferenceError("simulated failure", model="test-model")
    )

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            client=failing_client,
            model="test-model",
            user_message="seed",
            settings=settings,
            state_store=store,
            round_num=1,
        )

    # All decisions failed.
    assert all(r.signal is SignalType.PARSE_ERROR for r in results)
    # ⇒ ZERO rationale entries pushed.
    assert store.peek_rationales() == ()


async def test_safe_agent_inference_no_push_when_state_store_none(
    governor: ResourceGovernor,
    sample_personas: list[WorkerPersonaConfig],
) -> None:
    """When state_store is None, streaming is a silent no-op (no crash)."""
    from alphaswarm.batch_dispatcher import dispatch_wave

    client = _make_mock_client()
    settings = GovernorSettings(baseline_parallel=16)

    with patch("alphaswarm.batch_dispatcher.asyncio.sleep", new_callable=AsyncMock):
        results = await dispatch_wave(
            personas=sample_personas,
            governor=governor,
            client=client,
            model="test-model",
            user_message="seed",
            settings=settings,
            state_store=None,
            round_num=1,
        )

    assert len(results) == len(sample_personas)
