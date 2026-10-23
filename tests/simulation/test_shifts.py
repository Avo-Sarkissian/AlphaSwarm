"""Round-to-round shift metrics, bracket summaries and result containers."""

from __future__ import annotations

import dataclasses

import pytest

from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketType,
    SignalType,
)
from tests.simulation.support import (
    MOCK_PARSED_RESULT,
)


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


def test_compute_shifts_signal_flips() -> None:
    """2 agents BUY->SELL and 1 SELL->HOLD produces correct ShiftMetrics."""
    from alphaswarm.rounds import compute_shifts

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
            id="quants_01",
            name="Q1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02",
            name="Q2",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01",
            name="D1",
            bracket=BracketType.DEGENS,
            risk_profile=0.95,
            temperature=1.2,
            system_prompt="t",
            influence_weight_base=0.3,
        ),
    ]

    shifts = compute_shifts(prev, curr, personas)

    assert shifts.total_flips == 3
    assert shifts.agents_shifted == 3
    transitions = dict(shifts.signal_transitions)
    assert transitions["BUY->SELL"] == 2
    assert transitions["SELL->HOLD"] == 1


def test_compute_shifts_no_flips() -> None:
    """Identical decisions across rounds produces total_flips=0."""
    from alphaswarm.rounds import compute_shifts

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ]

    personas = [
        AgentPersona(
            id="quants_01",
            name="Q1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01",
            name="D1",
            bracket=BracketType.DEGENS,
            risk_profile=0.95,
            temperature=1.2,
            system_prompt="t",
            influence_weight_base=0.3,
        ),
    ]

    shifts = compute_shifts(decisions, decisions, personas)

    assert shifts.total_flips == 0
    assert shifts.agents_shifted == 0


def test_compute_shifts_bracket_confidence() -> None:
    """Bracket-grouped confidence delta is computed correctly (mean of per-agent deltas)."""
    from alphaswarm.rounds import compute_shifts

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
            id="quants_01",
            name="Q1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02",
            name="Q2",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
    ]

    shifts = compute_shifts(prev, curr, personas)

    bracket_deltas = dict(shifts.bracket_confidence_delta)
    # Both agents shifted +0.1, so mean delta = +0.1
    assert abs(bracket_deltas["quants"] - 0.1) < 1e-6


def test_shift_metrics_is_frozen() -> None:
    """ShiftMetrics is frozen dataclass with tuple fields."""
    from alphaswarm.rounds import ShiftMetrics

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
    from alphaswarm.rounds import ShiftMetrics
    from alphaswarm.simulation import SimulationResult

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
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cycle_id = "mutated"  # type: ignore[misc]

    # Verify tuple fields
    fields = {f.name: f for f in dataclasses.fields(SimulationResult)}
    assert "round1_decisions" in fields
    assert "round2_decisions" in fields
    assert "round3_decisions" in fields


# ---------------------------------------------------------------------------
# Phase 8: BracketSummary tests
# ---------------------------------------------------------------------------


def test_bracket_summary_is_frozen() -> None:
    """BracketSummary is a frozen dataclass."""
    from alphaswarm.state import BracketSummary

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
    from alphaswarm.rounds import compute_bracket_summaries
    from alphaswarm.types import BracketConfig

    # 2 BUY quants, 1 SELL degens
    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, sentiment=0.5)),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.6, sentiment=0.3)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, sentiment=-0.4)),
    ]
    personas = [
        AgentPersona(
            id="quants_01",
            name="Q1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02",
            name="Q2",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="degens_01",
            name="D1",
            bracket=BracketType.DEGENS,
            risk_profile=0.9,
            temperature=1.2,
            system_prompt="t",
            influence_weight_base=0.3,
        ),
    ]
    brackets = [
        BracketConfig(
            bracket_type=BracketType.QUANTS,
            display_name="Quants",
            count=2,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt_template="t",
            influence_weight_base=0.7,
        ),
        BracketConfig(
            bracket_type=BracketType.DEGENS,
            display_name="Degens",
            count=1,
            risk_profile=0.9,
            temperature=1.2,
            system_prompt_template="t",
            influence_weight_base=0.3,
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
    from alphaswarm.rounds import compute_bracket_summaries
    from alphaswarm.types import BracketConfig

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
        ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0)),
    ]
    personas = [
        AgentPersona(
            id="quants_01",
            name="Q1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02",
            name="Q2",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
    ]
    brackets = [
        BracketConfig(
            bracket_type=BracketType.QUANTS,
            display_name="Quants",
            count=2,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt_template="t",
            influence_weight_base=0.7,
        ),
    ]
    result = compute_bracket_summaries(decisions, personas, brackets)
    assert result[0].total == 1  # Only 1 valid decision
    assert result[0].buy_count == 1


def test_compute_bracket_summaries_avg_confidence() -> None:
    """compute_bracket_summaries computes correct avg_confidence."""
    from alphaswarm.rounds import compute_bracket_summaries
    from alphaswarm.types import BracketConfig

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, sentiment=0.4)),
        ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.6, sentiment=-0.2)),
    ]
    personas = [
        AgentPersona(
            id="quants_01",
            name="Q1",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
        AgentPersona(
            id="quants_02",
            name="Q2",
            bracket=BracketType.QUANTS,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt="t",
            influence_weight_base=0.7,
        ),
    ]
    brackets = [
        BracketConfig(
            bracket_type=BracketType.QUANTS,
            display_name="Quants",
            count=2,
            risk_profile=0.4,
            temperature=0.3,
            system_prompt_template="t",
            influence_weight_base=0.7,
        ),
    ]
    result = compute_bracket_summaries(decisions, personas, brackets)
    assert result[0].avg_confidence == pytest.approx(0.7)  # (0.8 + 0.6) / 2
    assert result[0].avg_sentiment == pytest.approx(0.1)  # (0.4 + -0.2) / 2


# ---------------------------------------------------------------------------
# Peer selection tests live in tests/test_peer_selection.py
# (docs/DECISIONS.md#adr-diverse-peer-context).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 08 Plan 02: New integration tests for wiring
# ---------------------------------------------------------------------------


def test_simulation_result_has_bracket_summaries() -> None:
    """SimulationResult contains round1_summaries, round2_summaries, round3_summaries fields."""
    from alphaswarm.rounds import ShiftMetrics
    from alphaswarm.simulation import SimulationResult
    from alphaswarm.state import BracketSummary

    dummy_shift = ShiftMetrics(
        signal_transitions=(),
        total_flips=0,
        bracket_confidence_delta=(),
        agents_shifted=0,
    )
    dummy_summary = BracketSummary(
        bracket="quants",
        display_name="Quants",
        buy_count=1,
        sell_count=0,
        hold_count=0,
        total=1,
        avg_confidence=0.8,
        avg_sentiment=0.4,
    )

    result = SimulationResult(
        cycle_id="test",
        parsed_result=MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(),
        round3_decisions=(),
        round2_shifts=dummy_shift,
        round3_shifts=dummy_shift,
        round1_summaries=(dummy_summary,),
        round2_summaries=(dummy_summary,),
        round3_summaries=(dummy_summary,),
    )

    assert isinstance(result.round1_summaries, tuple)
    assert isinstance(result.round2_summaries, tuple)
    assert isinstance(result.round3_summaries, tuple)
    assert len(result.round1_summaries) == 1
    assert isinstance(result.round1_summaries[0], BracketSummary)


def test_round_complete_event_has_bracket_summaries() -> None:
    """RoundCompleteEvent contains bracket_summaries field of type tuple[BracketSummary, ...]."""
    from alphaswarm.rounds import RoundCompleteEvent
    from alphaswarm.state import BracketSummary

    dummy_summary = BracketSummary(
        bracket="degens",
        display_name="Degens",
        buy_count=0,
        sell_count=2,
        hold_count=0,
        total=2,
        avg_confidence=0.65,
        avg_sentiment=-0.3,
    )

    event = RoundCompleteEvent(
        round_num=2,
        cycle_id="test-cycle",
        agent_decisions=(),
        shift=None,
        bracket_summaries=(dummy_summary,),
    )

    assert isinstance(event.bracket_summaries, tuple)
    assert len(event.bracket_summaries) == 1
    assert isinstance(event.bracket_summaries[0], BracketSummary)
    assert event.bracket_summaries[0].bracket == "degens"
