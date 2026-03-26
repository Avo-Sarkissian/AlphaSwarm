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


# ---------------------------------------------------------------------------
# Phase 07 Task 2 Tests: _dispatch_round and run_simulation
# ---------------------------------------------------------------------------


# Helper to build a Round1Result for mocking run_round1

def _mock_round1_result() -> "Round1Result":
    from alphaswarm.simulation import Round1Result
    return Round1Result(
        cycle_id="test-cycle-id",
        parsed_result=MOCK_PARSED_RESULT,
        agent_decisions=[
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
            ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.7)),
            ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6)),
            ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.5)),
        ],
    )


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
async def test_dispatch_round_reads_peers_per_agent(
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
    mock_ollama_client: MagicMock,
) -> None:
    """_dispatch_round calls graph_manager.read_peer_decisions once per persona."""
    from alphaswarm.simulation import _dispatch_round

    mock_graph_manager.read_peer_decisions = AsyncMock(return_value=[])
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await _dispatch_round(
        personas=TEST_PERSONAS,
        cycle_id="test-cycle",
        source_round=1,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        client=mock_ollama_client,
        model="test-model",
        rumor=MOCK_RUMOR,
        settings=mock_settings.governor,
    )

    assert mock_graph_manager.read_peer_decisions.await_count == len(TEST_PERSONAS)
    # Verify each persona's agent_id was queried
    called_agent_ids = [
        call.args[0] for call in mock_graph_manager.read_peer_decisions.await_args_list
    ]
    expected_ids = [p.id for p in TEST_PERSONAS]
    assert sorted(called_agent_ids) == sorted(expected_ids)


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
async def test_dispatch_round_formats_and_passes_peer_contexts(
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
    mock_ollama_client: MagicMock,
) -> None:
    """_dispatch_round passes a peer_contexts list to dispatch_wave (not scalar)."""
    from alphaswarm.graph import PeerDecision
    from alphaswarm.simulation import _dispatch_round

    mock_graph_manager.read_peer_decisions = AsyncMock(return_value=[
        PeerDecision(
            agent_id="other_01", bracket="quants", signal="buy",
            confidence=0.9, sentiment=0.5, rationale="peer reasoning",
        ),
    ])
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await _dispatch_round(
        personas=TEST_PERSONAS,
        cycle_id="test-cycle",
        source_round=1,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        client=mock_ollama_client,
        model="test-model",
        rumor=MOCK_RUMOR,
        settings=mock_settings.governor,
    )

    # dispatch_wave should be called with peer_contexts kwarg
    assert "peer_contexts" in mock_dispatch.call_args.kwargs
    peer_contexts = mock_dispatch.call_args.kwargs["peer_contexts"]
    assert isinstance(peer_contexts, list)
    assert len(peer_contexts) == len(TEST_PERSONAS)


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
async def test_dispatch_round_length_mismatch_raises_value_error(
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
    mock_ollama_client: MagicMock,
) -> None:
    """dispatch_wave returning wrong number of results raises ValueError."""
    from alphaswarm.simulation import _dispatch_round

    mock_graph_manager.read_peer_decisions = AsyncMock(return_value=[])
    # Return fewer results than personas
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS) - 1)

    with pytest.raises(ValueError, match="dispatch_wave returned"):
        await _dispatch_round(
            personas=TEST_PERSONAS,
            cycle_id="test-cycle",
            source_round=1,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            client=mock_ollama_client,
            model="test-model",
            rumor=MOCK_RUMOR,
            settings=mock_settings.governor,
        )


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_calls_run_round1(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_simulation calls run_round1 as first step."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_round1.assert_awaited_once()


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_round2_uses_round1_peers(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_simulation calls _dispatch_round for Round 2 with source_round=1."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    # _dispatch_round called twice (Round 2 and Round 3)
    assert mock_dispatch_round.await_count == 2
    # First call is Round 2 with source_round=1
    r2_call = mock_dispatch_round.await_args_list[0]
    assert r2_call.kwargs["source_round"] == 1


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_round3_uses_round2_peers(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_simulation calls _dispatch_round for Round 3 with source_round=2."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    # Second call is Round 3 with source_round=2
    r3_call = mock_dispatch_round.await_args_list[1]
    assert r3_call.kwargs["source_round"] == 2


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_returns_complete_result(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_simulation returns SimulationResult with all 3 rounds and 2 ShiftMetrics."""
    from alphaswarm.simulation import SimulationResult, run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    result = await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert isinstance(result, SimulationResult)
    assert result.cycle_id == "test-cycle-id"
    assert isinstance(result.round1_decisions, tuple)
    assert isinstance(result.round2_decisions, tuple)
    assert isinstance(result.round3_decisions, tuple)
    assert result.round2_shifts is not None
    assert result.round3_shifts is not None


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_persists_all_rounds(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """write_decisions called for round 2 and round 3 (round 1 via run_round1)."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    # write_decisions called twice by run_simulation (round 2, round 3)
    # round 1 is done inside run_round1 which is mocked
    assert mock_graph_manager.write_decisions.await_count == 2
    round_nums = [
        call.kwargs.get("round_num", call.args[2] if len(call.args) > 2 else None)
        for call in mock_graph_manager.write_decisions.await_args_list
    ]
    assert 2 in round_nums
    assert 3 in round_nums


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_worker_reload_once_for_rounds_2_3(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """ensure_clean_state + load_model called once for Rounds 2-3 block."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    # ensure_clean_state called once (for Rounds 2-3 prep)
    mock_model_manager.ensure_clean_state.assert_awaited_once()
    # load_model called once (for Rounds 2-3)
    mock_model_manager.load_model.assert_awaited_once()
    # unload_model called once (after Rounds 2-3)
    mock_model_manager.unload_model.assert_awaited_once()


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_governor_fresh_session_rounds_2_3(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """governor.start_monitoring and stop_monitoring called for Rounds 2-3 block."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    # run_simulation's own governor session (separate from run_round1's)
    mock_governor.start_monitoring.assert_awaited_once()
    mock_governor.stop_monitoring.assert_awaited_once()


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_simulation_phase_transitions(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """Phase transitions are logged in correct order."""
    import structlog
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    logged_phases: list[str] = []
    original_logger = structlog.get_logger

    with patch("alphaswarm.simulation.logger") as mock_logger:
        # Capture phase transitions from structlog info calls
        def capture_info(event: str, **kwargs: object) -> None:
            if "phase" in kwargs:
                logged_phases.append(str(kwargs["phase"]))

        mock_logger.info = capture_info
        mock_logger.warning = MagicMock()

        await run_simulation(
            rumor=MOCK_RUMOR,
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            personas=TEST_PERSONAS,
        )

    # Verify phase order: idle, seeding, round_1, round_2, round_3, complete
    assert "idle" in logged_phases
    assert "seeding" in logged_phases
    assert "round_1" in logged_phases
    assert "round_2" in logged_phases
    assert "round_3" in logged_phases
    assert "complete" in logged_phases


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_cleanup_on_error(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """If dispatch_wave raises during Round 2, worker is unloaded and governor stopped."""
    from alphaswarm.simulation import run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.side_effect = Exception("round2_boom")

    with pytest.raises(Exception, match="round2_boom"):
        await run_simulation(
            rumor=MOCK_RUMOR,
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            personas=TEST_PERSONAS,
        )

    # Cleanup must still happen
    mock_model_manager.unload_model.assert_awaited_once()
    mock_governor.stop_monitoring.assert_awaited_once()


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_fires_on_round_complete_round1(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """on_round_complete called after Round 1 with round_num=1, shift=None."""
    from alphaswarm.simulation import RoundCompleteEvent, run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    callback = AsyncMock()

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
        on_round_complete=callback,
    )

    # First call should be for Round 1
    r1_event = callback.await_args_list[0].args[0]
    assert isinstance(r1_event, RoundCompleteEvent)
    assert r1_event.round_num == 1
    assert r1_event.shift is None


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_fires_on_round_complete_round2(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """on_round_complete called after Round 2 with round_num=2, shift=ShiftMetrics."""
    from alphaswarm.simulation import RoundCompleteEvent, ShiftMetrics, run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    callback = AsyncMock()

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
        on_round_complete=callback,
    )

    # Second call should be for Round 2
    r2_event = callback.await_args_list[1].args[0]
    assert isinstance(r2_event, RoundCompleteEvent)
    assert r2_event.round_num == 2
    assert isinstance(r2_event.shift, ShiftMetrics)


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_fires_on_round_complete_round3(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """on_round_complete called after Round 3 with round_num=3, shift=ShiftMetrics."""
    from alphaswarm.simulation import RoundCompleteEvent, ShiftMetrics, run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    callback = AsyncMock()

    await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
        on_round_complete=callback,
    )

    # Third call should be for Round 3
    assert callback.await_count == 3
    r3_event = callback.await_args_list[2].args[0]
    assert isinstance(r3_event, RoundCompleteEvent)
    assert r3_event.round_num == 3
    assert isinstance(r3_event.shift, ShiftMetrics)


@patch("alphaswarm.simulation._dispatch_round", new_callable=AsyncMock)
@patch("alphaswarm.simulation.run_round1", new_callable=AsyncMock)
async def test_run_simulation_no_callback(
    mock_round1: AsyncMock,
    mock_dispatch_round: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_simulation works correctly when on_round_complete=None (no crash)."""
    from alphaswarm.simulation import SimulationResult, run_simulation

    mock_round1.return_value = _mock_round1_result()
    mock_dispatch_round.return_value = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.8))
        for p in TEST_PERSONAS
    ]

    result = await run_simulation(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
        on_round_complete=None,
    )

    assert isinstance(result, SimulationResult)


# ---------------------------------------------------------------------------
# Phase 8: BracketSummary tests
# ---------------------------------------------------------------------------


def test_bracket_summary_is_frozen() -> None:
    """BracketSummary is a frozen dataclass."""
    from alphaswarm.simulation import BracketSummary

    bs = BracketSummary(
        bracket="quants",
        display_name="Quants",
        buy_count=5,
        sell_count=3,
        hold_count=2,
        total=10,
        avg_confidence=0.75,
        avg_sentiment=0.3,
    )
    assert dataclasses.is_dataclass(bs)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bs.bracket = "changed"  # type: ignore[misc]


def test_compute_bracket_summaries_signal_counts() -> None:
    """compute_bracket_summaries correctly counts signals per bracket."""
    from alphaswarm.config import BracketConfig
    from alphaswarm.simulation import compute_bracket_summaries

    # 2 BUY quants, 1 SELL degens
    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, sentiment=0.5)),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.6, sentiment=0.3)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, sentiment=-0.4)),
    ]
    personas = [
        AgentPersona(
            id="quants_01", name="Q1", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02", name="Q2", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01", name="D1", bracket=BracketType.DEGENS,
            risk_profile=0.9, temperature=1.2, system_prompt="t", influence_weight_base=0.3,
        ),
    ]
    brackets = [
        BracketConfig(
            bracket_type=BracketType.QUANTS, display_name="Quants", count=2,
            risk_profile=0.4, temperature=0.3, system_prompt_template="t", influence_weight_base=0.7,
        ),
        BracketConfig(
            bracket_type=BracketType.DEGENS, display_name="Degens", count=1,
            risk_profile=0.9, temperature=1.2, system_prompt_template="t", influence_weight_base=0.3,
        ),
    ]
    result = compute_bracket_summaries(decisions, personas, brackets)
    quants_summary = result[0]
    assert quants_summary.bracket == "quants"
    assert quants_summary.buy_count == 2
    assert quants_summary.sell_count == 0
    assert quants_summary.hold_count == 0
    assert quants_summary.total == 2


def test_compute_bracket_summaries_excludes_parse_error() -> None:
    """compute_bracket_summaries excludes PARSE_ERROR agents."""
    from alphaswarm.config import BracketConfig
    from alphaswarm.simulation import compute_bracket_summaries

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
        ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0)),
    ]
    personas = [
        AgentPersona(
            id="quants_01", name="Q1", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02", name="Q2", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        ),
    ]
    brackets = [
        BracketConfig(
            bracket_type=BracketType.QUANTS, display_name="Quants", count=2,
            risk_profile=0.4, temperature=0.3, system_prompt_template="t", influence_weight_base=0.7,
        ),
    ]
    result = compute_bracket_summaries(decisions, personas, brackets)
    assert result[0].total == 1  # Only 1 valid decision
    assert result[0].buy_count == 1


def test_compute_bracket_summaries_avg_confidence() -> None:
    """compute_bracket_summaries computes correct avg_confidence."""
    from alphaswarm.config import BracketConfig
    from alphaswarm.simulation import compute_bracket_summaries

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, sentiment=0.4)),
        ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.6, sentiment=-0.2)),
    ]
    personas = [
        AgentPersona(
            id="quants_01", name="Q1", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02", name="Q2", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        ),
    ]
    brackets = [
        BracketConfig(
            bracket_type=BracketType.QUANTS, display_name="Quants", count=2,
            risk_profile=0.4, temperature=0.3, system_prompt_template="t", influence_weight_base=0.7,
        ),
    ]
    result = compute_bracket_summaries(decisions, personas, brackets)
    assert result[0].avg_confidence == pytest.approx(0.7)   # (0.8 + 0.6) / 2
    assert result[0].avg_sentiment == pytest.approx(0.1)    # (0.4 + -0.2) / 2


# ---------------------------------------------------------------------------
# Phase 8: Bracket-diverse peer selection tests
# ---------------------------------------------------------------------------


def test_bracket_diverse_peer_selection() -> None:
    """select_diverse_peers returns 5 agents from at least 3 brackets."""
    from alphaswarm.simulation import select_diverse_peers

    personas = []
    for bt in [BracketType.QUANTS, BracketType.DEGENS, BracketType.MACRO, BracketType.WHALES]:
        for j in range(3):
            personas.append(
                AgentPersona(
                    id=f"{bt.value}_{j:02d}",
                    name=f"{bt.value} {j}",
                    bracket=bt,
                    risk_profile=0.5,
                    temperature=0.5,
                    system_prompt="t",
                    influence_weight_base=0.5,
                )
            )
    weights = {
        "quants_00": 0.5, "degens_00": 0.4, "macro_00": 0.3, "whales_00": 0.2,
        "quants_01": 0.15, "degens_01": 0.1,
    }
    result = select_diverse_peers("quants_02", weights, personas, limit=5, min_brackets=3)
    assert len(result) == 5
    brackets_in_result = {p.bracket.value for p in personas if p.id in result}
    assert len(brackets_in_result) >= 3


def test_select_diverse_peers_excludes_self() -> None:
    """select_diverse_peers never includes the calling agent."""
    from alphaswarm.simulation import select_diverse_peers

    personas = [
        AgentPersona(
            id=f"quants_{i:02d}", name=f"Q{i}", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        )
        for i in range(6)
    ]
    weights = {f"quants_{i:02d}": 0.5 - i * 0.05 for i in range(6)}
    result = select_diverse_peers("quants_00", weights, personas, limit=5, min_brackets=3)
    assert "quants_00" not in result


def test_select_diverse_peers_excludes_parse_error_agents() -> None:
    """select_diverse_peers excludes agents with PARSE_ERROR decisions from candidates."""
    # Rev: [Codex HIGH] PARSE_ERROR agents must not appear as peers
    from alphaswarm.simulation import select_diverse_peers

    personas = [
        AgentPersona(
            id=f"quants_{i:02d}", name=f"Q{i}", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        )
        for i in range(6)
    ]
    weights = {f"quants_{i:02d}": 0.5 - i * 0.05 for i in range(6)}
    prev_decisions = {
        "quants_01": AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0),
        "quants_02": AgentDecision(signal=SignalType.BUY, confidence=0.8),
    }
    result = select_diverse_peers(
        "quants_00", weights, personas,
        prev_decisions=prev_decisions, limit=5, min_brackets=3,
    )
    assert "quants_01" not in result  # PARSE_ERROR agent excluded


def test_select_diverse_peers_fills_by_weight() -> None:
    """After bracket diversity, remaining slots go to highest weight."""
    from alphaswarm.simulation import select_diverse_peers

    personas = [
        AgentPersona(id="quants_00", name="Q0", bracket=BracketType.QUANTS, risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7),
        AgentPersona(id="degens_00", name="D0", bracket=BracketType.DEGENS, risk_profile=0.9, temperature=1.2, system_prompt="t", influence_weight_base=0.3),
        AgentPersona(id="macro_00", name="M0", bracket=BracketType.MACRO, risk_profile=0.5, temperature=0.5, system_prompt="t", influence_weight_base=0.5),
        AgentPersona(id="quants_01", name="Q1", bracket=BracketType.QUANTS, risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7),
        AgentPersona(id="quants_02", name="Q2", bracket=BracketType.QUANTS, risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7),
        AgentPersona(id="degens_01", name="D1", bracket=BracketType.DEGENS, risk_profile=0.9, temperature=1.2, system_prompt="t", influence_weight_base=0.3),
    ]
    # quants_01 has very high weight, should be picked in Phase 2
    weights = {
        "quants_00": 0.9, "degens_00": 0.7, "macro_00": 0.5,
        "quants_01": 0.8, "quants_02": 0.1, "degens_01": 0.2,
    }
    result = select_diverse_peers(
        "self_00",
        weights,
        personas + [
            AgentPersona(id="self_00", name="Self", bracket=BracketType.WHALES, risk_profile=0.5, temperature=0.5, system_prompt="t", influence_weight_base=0.5),
        ],
        limit=5,
        min_brackets=3,
    )
    # quants_01 (weight 0.8) should be in the result as a Phase 2 fill
    assert "quants_01" in result


def test_select_diverse_peers_graceful_with_few_brackets() -> None:
    """With only 2 brackets available, still returns 5 peers."""
    from alphaswarm.simulation import select_diverse_peers

    personas = [
        AgentPersona(
            id=f"quants_{i:02d}", name=f"Q{i}", bracket=BracketType.QUANTS,
            risk_profile=0.4, temperature=0.3, system_prompt="t", influence_weight_base=0.7,
        )
        for i in range(4)
    ] + [
        AgentPersona(
            id=f"degens_{i:02d}", name=f"D{i}", bracket=BracketType.DEGENS,
            risk_profile=0.9, temperature=1.2, system_prompt="t", influence_weight_base=0.3,
        )
        for i in range(3)
    ]
    weights = {p.id: 0.5 for p in personas}
    result = select_diverse_peers("quants_00", weights, personas, limit=5, min_brackets=3)
    assert len(result) == 5  # Still returns 5 even though < 3 brackets
