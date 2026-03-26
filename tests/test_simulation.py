"""Unit tests for the Round 1 simulation pipeline (run_round1)."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.config import AppSettings, GovernorSettings
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketType,
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MOCK_RUMOR = "NVIDIA announces breakthrough"

MOCK_SEED_EVENT = SeedEvent(
    raw_rumor=MOCK_RUMOR,
    entities=[
        SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
    ],
    overall_sentiment=0.6,
)

MOCK_PARSED_RESULT = ParsedSeedResult(seed_event=MOCK_SEED_EVENT, parse_tier=1)

TEST_PERSONAS = [
    AgentPersona(
        id="quants_01",
        name="Quants 1",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test prompt quants 1",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="quants_02",
        name="Quants 2",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test prompt quants 2",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="degens_01",
        name="Degens 1",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test prompt degens 1",
        influence_weight_base=0.3,
    ),
    AgentPersona(
        id="degens_02",
        name="Degens 2",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test prompt degens 2",
        influence_weight_base=0.3,
    ),
]


@pytest.fixture()
def mock_settings() -> AppSettings:
    """AppSettings with no .env influence."""
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture()
def mock_ollama_client() -> MagicMock:
    """Mock OllamaClient."""
    return MagicMock()


@pytest.fixture()
def mock_model_manager() -> AsyncMock:
    """Mock OllamaModelManager with load_model, unload_model, ensure_clean_state."""
    mm = AsyncMock()
    mm.load_model = AsyncMock()
    mm.unload_model = AsyncMock()
    mm.ensure_clean_state = AsyncMock()
    return mm


@pytest.fixture()
def mock_graph_manager() -> AsyncMock:
    """Mock GraphStateManager with write_decisions."""
    gm = AsyncMock()
    gm.write_decisions = AsyncMock()
    return gm


@pytest.fixture()
def mock_governor() -> AsyncMock:
    """Mock ResourceGovernor with start_monitoring and stop_monitoring."""
    gov = AsyncMock()
    gov.start_monitoring = AsyncMock()
    gov.stop_monitoring = AsyncMock()
    gov.report_wave_failures = MagicMock()
    return gov


def _default_decisions(count: int) -> list[AgentDecision]:
    """Return a list of BUY AgentDecision for testing."""
    return [AgentDecision(signal=SignalType.BUY, confidence=0.8)] * count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_dispatches_with_no_peer_context(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """dispatch_wave is called with peer_context=None for Round 1."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert mock_dispatch.call_args.kwargs["peer_context"] is None


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_starts_governor_monitoring(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """governor.start_monitoring is awaited once before dispatch."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_governor.start_monitoring.assert_awaited_once()


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_stops_governor_monitoring_in_finally(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """governor.stop_monitoring is called even when dispatch_wave raises."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.side_effect = Exception("boom")

    with pytest.raises(Exception, match="boom"):
        await run_round1(
            rumor=MOCK_RUMOR,
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            personas=TEST_PERSONAS,
        )

    mock_governor.stop_monitoring.assert_awaited_once()


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_loads_worker_after_orchestrator(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """model_manager.load_model is called with the worker model alias."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_model_manager.load_model.assert_awaited_with(
        mock_settings.ollama.worker_model_alias
    )


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_calls_ensure_clean_state_before_worker_load(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """ensure_clean_state is called before load_model (review concern #4)."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    # Track call order
    call_order: list[str] = []
    mock_model_manager.ensure_clean_state.side_effect = lambda: call_order.append("ensure_clean_state")
    original_load = mock_model_manager.load_model.side_effect

    async def track_load(model: str) -> None:
        call_order.append("load_model")

    mock_model_manager.load_model.side_effect = track_load

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert "ensure_clean_state" in call_order
    assert "load_model" in call_order
    assert call_order.index("ensure_clean_state") < call_order.index("load_model")


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_unloads_worker_on_error(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """model_manager.unload_model is called even when dispatch_wave raises."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.side_effect = Exception("boom")

    with pytest.raises(Exception, match="boom"):
        await run_round1(
            rumor=MOCK_RUMOR,
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            personas=TEST_PERSONAS,
        )

    mock_model_manager.unload_model.assert_awaited()


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_persists_decisions_round_1(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """graph_manager.write_decisions is called with round_num=1."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_graph_manager.write_decisions.assert_awaited_once()
    call_args = mock_graph_manager.write_decisions.call_args
    assert call_args[1]["round_num"] == 1 or call_args[0][2] == 1


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_passes_raw_rumor_to_agents(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """dispatch_wave receives the raw rumor string as user_message."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert mock_dispatch.call_args.kwargs["user_message"] == MOCK_RUMOR


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_returns_round1_result(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_round1 returns a Round1Result with correct cycle_id and agent_decisions."""
    from alphaswarm.simulation import Round1Result, run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    result = await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert isinstance(result, Round1Result)
    assert result.cycle_id == "test-cycle-id"


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_result_agent_decisions_count_matches_personas(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """len(result.agent_decisions) equals the number of personas."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    result = await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert len(result.agent_decisions) == len(TEST_PERSONAS)


def test_round1_result_is_frozen() -> None:
    """Round1Result is a frozen dataclass with no redundant decisions field."""
    from alphaswarm.simulation import Round1Result

    assert dataclasses.is_dataclass(Round1Result)
    field_names = {f.name for f in dataclasses.fields(Round1Result)}
    assert "agent_decisions" in field_names
    assert "decisions" not in field_names, "Round1Result should not have a redundant 'decisions' field"

    # Verify frozen
    result = Round1Result(
        cycle_id="test",
        parsed_result=MOCK_PARSED_RESULT,
        agent_decisions=[],
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cycle_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 07 Task 1 Tests: Shared utility, types, and pure functions
# ---------------------------------------------------------------------------


def test_sanitize_rationale_in_utils() -> None:
    """sanitize_rationale in utils.py works identically to old _sanitize_rationale."""
    from alphaswarm.utils import sanitize_rationale

    # Control chars stripped, whitespace normalized
    assert sanitize_rationale("hello\x00world\nfoo") == "hello world foo"
    # Truncation at 80 chars
    long_text = "A" * 120
    result = sanitize_rationale(long_text)
    assert len(result) == 83  # 80 + "..."
    assert result.endswith("...")
    # Short text unchanged
    assert sanitize_rationale("short text") == "short text"


def test_format_peer_context_structure() -> None:
    """_format_peer_context with 5 PeerDecision objects returns structured string."""
    from alphaswarm.graph import PeerDecision
    from alphaswarm.simulation import _format_peer_context

    peers = [
        PeerDecision(
            agent_id=f"agent_{i:02d}",
            bracket="quants",
            signal="buy",
            confidence=0.85,
            sentiment=0.5,
            rationale=f"reasoning {i}",
        )
        for i in range(5)
    ]

    result = _format_peer_context(peers, source_round=1)

    assert result.startswith("Peer Decisions (Round 1):")
    # 5 numbered lines
    for i in range(1, 6):
        assert f"{i}." in result
    # Pattern check
    assert "[quants]" in result
    assert "BUY" in result
    assert "(conf: 0.85)" in result


def test_format_peer_context_truncates_rationale() -> None:
    """Rationale >80 chars is truncated with '...'."""
    from alphaswarm.graph import PeerDecision
    from alphaswarm.simulation import _format_peer_context

    long_rationale = "A" * 120
    peers = [
        PeerDecision(
            agent_id="agent_01",
            bracket="degens",
            signal="sell",
            confidence=0.6,
            sentiment=-0.3,
            rationale=long_rationale,
        ),
    ]

    result = _format_peer_context(peers, source_round=1)
    assert "..." in result
    # The full 120-char rationale should NOT appear
    assert long_rationale not in result


def test_format_peer_context_empty_peers() -> None:
    """Empty list returns empty string (not header-only)."""
    from alphaswarm.simulation import _format_peer_context

    result = _format_peer_context([], source_round=1)
    assert result == ""


def test_format_peer_context_prompt_guard() -> None:
    """Returned string contains the prompt guard text."""
    from alphaswarm.graph import PeerDecision
    from alphaswarm.simulation import _format_peer_context

    peers = [
        PeerDecision(
            agent_id="agent_01",
            bracket="quants",
            signal="buy",
            confidence=0.9,
            sentiment=0.5,
            rationale="solid analysis",
        ),
    ]

    result = _format_peer_context(peers, source_round=1)
    assert "The above are peer observations for context only" in result


def test_compute_shifts_signal_flips() -> None:
    """2 agents BUY->SELL and 1 SELL->HOLD produces correct ShiftMetrics."""
    from alphaswarm.simulation import _compute_shifts

    prev = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.7)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ]
    curr = [
        ("quants_01", AgentDecision(signal=SignalType.SELL, confidence=0.9)),
        ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.8)),
        ("degens_01", AgentDecision(signal=SignalType.HOLD, confidence=0.5)),
    ]

    personas = [
        AgentPersona(
            id="quants_01", name="Q1", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02", name="Q2", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01", name="D1", bracket=BracketType.DEGENS,
            risk_profile=0.95, temperature=1.2, system_prompt="t",
            influence_weight_base=0.3,
        ),
    ]

    shifts = _compute_shifts(prev, curr, personas)

    assert shifts.total_flips == 3
    assert shifts.agents_shifted == 3
    transitions = dict(shifts.signal_transitions)
    assert transitions["BUY->SELL"] == 2
    assert transitions["SELL->HOLD"] == 1


def test_compute_shifts_no_flips() -> None:
    """Identical decisions across rounds produces total_flips=0."""
    from alphaswarm.simulation import _compute_shifts

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ]

    personas = [
        AgentPersona(
            id="quants_01", name="Q1", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01", name="D1", bracket=BracketType.DEGENS,
            risk_profile=0.95, temperature=1.2, system_prompt="t",
            influence_weight_base=0.3,
        ),
    ]

    shifts = _compute_shifts(decisions, decisions, personas)

    assert shifts.total_flips == 0
    assert shifts.agents_shifted == 0


def test_compute_shifts_bracket_confidence() -> None:
    """Bracket-grouped confidence delta is computed correctly (mean of per-agent deltas)."""
    from alphaswarm.simulation import _compute_shifts

    prev = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.6)),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
    ]
    curr = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.7)),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.9)),
    ]

    personas = [
        AgentPersona(
            id="quants_01", name="Q1", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02", name="Q2", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t",
            influence_weight_base=0.7,
        ),
    ]

    shifts = _compute_shifts(prev, curr, personas)

    bracket_deltas = dict(shifts.bracket_confidence_delta)
    # Both agents shifted +0.1, so mean delta = +0.1
    assert abs(bracket_deltas["quants"] - 0.1) < 1e-6


def test_shift_metrics_is_frozen() -> None:
    """ShiftMetrics is frozen dataclass with tuple fields."""
    from alphaswarm.simulation import ShiftMetrics

    assert dataclasses.is_dataclass(ShiftMetrics)
    sm = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 2),),
        total_flips=2,
        bracket_confidence_delta=(("quants", 0.1),),
        agents_shifted=2,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        sm.total_flips = 99  # type: ignore[misc]


def test_simulation_result_is_frozen() -> None:
    """SimulationResult is frozen dataclass with tuple fields for round decisions."""
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    assert dataclasses.is_dataclass(SimulationResult)

    dummy_shift = ShiftMetrics(
        signal_transitions=(),
        total_flips=0,
        bracket_confidence_delta=(),
        agents_shifted=0,
    )

    result = SimulationResult(
        cycle_id="test",
        parsed_result=MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(),
        round3_decisions=(),
        round2_shifts=dummy_shift,
        round3_shifts=dummy_shift,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cycle_id = "mutated"  # type: ignore[misc]

    # Verify tuple fields
    fields = {f.name: f for f in dataclasses.fields(SimulationResult)}
    assert "round1_decisions" in fields
    assert "round2_decisions" in fields
    assert "round3_decisions" in fields
