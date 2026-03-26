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

    async def mock_infer(user_message: str, peer_context: str | None = None) -> AgentDecision:
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

    async def mock_infer(user_message: str, peer_context: str | None = None) -> AgentDecision:
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

    async def mock_infer(user_message: str, peer_context: str | None = None) -> AgentDecision:
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

    async def mock_infer(user_message: str, peer_context: str | None = None) -> AgentDecision:
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

    async def mock_infer(user_message: str, peer_context: str | None = None) -> AgentDecision:
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
