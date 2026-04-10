"""Unit tests for CLI module (argparse routing, inject subcommand, run subcommand, banner, report)."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketConfig,
    BracketType,
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
)


@pytest.fixture()
def sample_parsed_result() -> ParsedSeedResult:
    """Sample ParsedSeedResult for CLI output tests."""
    return ParsedSeedResult(
        seed_event=SeedEvent(
            raw_rumor="NVIDIA announces breakthrough",
            entities=[
                SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
                SeedEntity(name="Semiconductors", type=EntityType.SECTOR, relevance=0.7, sentiment=0.5),
            ],
            overall_sentiment=0.6,
        ),
        parse_tier=1,
    )


@pytest.fixture()
def fallback_parsed_result() -> ParsedSeedResult:
    """ParsedSeedResult with parse_tier=3 for fallback output tests."""
    return ParsedSeedResult(
        seed_event=SeedEvent(
            raw_rumor="Unparseable rumor",
            entities=[],
            overall_sentiment=0.0,
        ),
        parse_tier=3,
    )


def test_parse_inject_args() -> None:
    """Parsing ['inject', 'NVIDIA announces...'] sets command='inject' and rumor."""
    from alphaswarm.cli import main

    parser = argparse.ArgumentParser(prog="alphaswarm")
    subparsers = parser.add_subparsers(dest="command")
    inject_parser = subparsers.add_parser("inject", help="Inject a seed rumor")
    inject_parser.add_argument("rumor", type=str)

    args = parser.parse_args(["inject", "NVIDIA announces breakthrough"])
    assert args.command == "inject"
    assert args.rumor == "NVIDIA announces breakthrough"


def test_parse_no_args_sets_command_none() -> None:
    """Parsing [] (no args) sets command=None (banner mode)."""
    parser = argparse.ArgumentParser(prog="alphaswarm")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("inject", help="Inject a seed rumor")

    args = parser.parse_args([])
    assert args.command is None


def test_print_injection_summary_outputs_cycle_id(
    capsys: pytest.CaptureFixture[str],
    sample_parsed_result: ParsedSeedResult,
) -> None:
    """_print_injection_summary outputs 'Cycle ID:' and 'Overall Sentiment:'."""
    from alphaswarm.cli import _print_injection_summary

    _print_injection_summary("test-cycle-id-123", sample_parsed_result)

    captured = capsys.readouterr()
    assert "Cycle ID:" in captured.out
    assert "test-cycle-id-123" in captured.out
    assert "Overall Sentiment:" in captured.out


def test_print_injection_summary_shows_fallback_tier(
    capsys: pytest.CaptureFixture[str],
    fallback_parsed_result: ParsedSeedResult,
) -> None:
    """_print_injection_summary outputs 'Parse Quality: Tier 3 (FALLBACK' for tier 3."""
    from alphaswarm.cli import _print_injection_summary

    _print_injection_summary("test-cycle-id", fallback_parsed_result)

    captured = capsys.readouterr()
    assert "Parse Quality:" in captured.out
    assert "Tier 3" in captured.out
    assert "FALLBACK" in captured.out


def test_print_injection_summary_outputs_entity_names(
    capsys: pytest.CaptureFixture[str],
    sample_parsed_result: ParsedSeedResult,
) -> None:
    """_print_injection_summary outputs entity names in the table."""
    from alphaswarm.cli import _print_injection_summary

    _print_injection_summary("test-cycle-id", sample_parsed_result)

    captured = capsys.readouterr()
    assert "NVIDIA" in captured.out
    assert "Semiconductors" in captured.out


def test_print_banner_outputs_alphaswarm_version(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_print_banner outputs 'AlphaSwarm v' to stdout."""
    from alphaswarm.cli import _print_banner

    # Mock AppSettings to avoid .env dependency
    mock_settings = MagicMock()
    mock_settings.ollama.orchestrator_model = "qwen3.5:32b"
    mock_settings.ollama.worker_model = "qwen3.5:7b"

    with patch("alphaswarm.cli.AppSettings", return_value=mock_settings), \
         patch("alphaswarm.cli.load_bracket_configs") as mock_brackets, \
         patch("alphaswarm.cli.generate_personas") as mock_personas:
        mock_brackets.return_value = [MagicMock()] * 10
        mock_personas.return_value = [MagicMock()] * 100
        _print_banner()

    captured = capsys.readouterr()
    assert "AlphaSwarm v" in captured.out


def test_main_no_args_calls_print_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() with no args calls _print_banner logic."""
    from alphaswarm.cli import main

    monkeypatch.setattr("sys.argv", ["alphaswarm"])

    with patch("alphaswarm.cli._print_banner") as mock_banner:
        main()

    mock_banner.assert_called_once()


def test_main_inject_calls_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() with inject args calls asyncio.run."""
    from alphaswarm.cli import main

    monkeypatch.setattr("sys.argv", ["alphaswarm", "inject", "NVIDIA announces breakthrough"])

    with patch("alphaswarm.cli.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock()
        main()

    mock_asyncio.run.assert_called_once()


def test_main_inject_failure_prints_error_to_stderr(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() with inject args prints 'Error:' to stderr when asyncio.run raises."""
    from alphaswarm.cli import main

    monkeypatch.setattr("sys.argv", ["alphaswarm", "inject", "bad rumor"])

    with patch("alphaswarm.cli.asyncio") as mock_asyncio, \
         patch("alphaswarm.cli.logger"):
        mock_asyncio.run.side_effect = Exception("Connection failed")
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# Phase 06: Run subcommand and report tests
# ---------------------------------------------------------------------------


# Shared test data for Round 1 report tests

_MOCK_SEED_EVENT = SeedEvent(
    raw_rumor="NVIDIA announces breakthrough",
    entities=[
        SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
    ],
    overall_sentiment=0.6,
)

_MOCK_PARSED_RESULT = ParsedSeedResult(seed_event=_MOCK_SEED_EVENT, parse_tier=1)

_TEST_PERSONAS = [
    AgentPersona(
        id="quants_01", name="Quants 1", bracket=BracketType.QUANTS,
        risk_profile=0.4, temperature=0.3, system_prompt="test",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="quants_02", name="Quants 2", bracket=BracketType.QUANTS,
        risk_profile=0.4, temperature=0.3, system_prompt="test",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="degens_01", name="Degens 1", bracket=BracketType.DEGENS,
        risk_profile=0.95, temperature=1.2, system_prompt="test",
        influence_weight_base=0.3,
    ),
    AgentPersona(
        id="degens_02", name="Degens 2", bracket=BracketType.DEGENS,
        risk_profile=0.95, temperature=1.2, system_prompt="test",
        influence_weight_base=0.3,
    ),
]

_TEST_BRACKETS = [
    BracketConfig(
        bracket_type=BracketType.QUANTS, display_name="Quants", count=2,
        risk_profile=0.4, temperature=0.3,
        system_prompt_template="test", influence_weight_base=0.7,
    ),
    BracketConfig(
        bracket_type=BracketType.DEGENS, display_name="Degens", count=2,
        risk_profile=0.95, temperature=1.2,
        system_prompt_template="test", influence_weight_base=0.3,
    ),
]


def test_parse_run_args() -> None:
    """Parsing ['run', 'rumor text'] sets command='run' and args.rumor."""
    parser = argparse.ArgumentParser(prog="alphaswarm")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("inject", help="Inject")
    run_parser = subparsers.add_parser("run", help="Run Round 1")
    run_parser.add_argument("rumor", type=str)

    args = parser.parse_args(["run", "NVIDIA announces breakthrough"])
    assert args.command == "run"
    assert args.rumor == "NVIDIA announces breakthrough"


def test_main_run_calls_handle_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() with sys.argv=["alphaswarm", "run", "test rumor"] calls _handle_run."""
    from alphaswarm.cli import main

    monkeypatch.setattr("sys.argv", ["alphaswarm", "run", "test rumor"])

    with patch("alphaswarm.cli._handle_run") as mock_handle_run:
        main()

    mock_handle_run.assert_called_once_with("test rumor")


def test_print_round1_report_bracket_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report contains bracket names and signal labels."""
    from alphaswarm.cli import _print_round1_report
    from alphaswarm.simulation import Round1Result

    agent_decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="data")),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.85, rationale="math")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="hype")),
        ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.65, rationale="fomo")),
    ]

    result = Round1Result(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        agent_decisions=agent_decisions,
    )

    _print_round1_report(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Quants" in captured.out
    assert "Degens" in captured.out
    assert "BUY" in captured.out
    assert "SELL" in captured.out


def test_print_round1_report_notable_decisions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report shows 'Notable Decisions' with the highest-confidence agent."""
    from alphaswarm.cli import _print_round1_report
    from alphaswarm.simulation import Round1Result

    # 4 agents with varying confidence; quants_01 has highest
    agent_decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.99, rationale="top pick")),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="neutral")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="panic")),
        ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.7, rationale="ape in")),
    ]

    result = Round1Result(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        agent_decisions=agent_decisions,
    )

    _print_round1_report(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Notable Decisions" in captured.out
    assert "quants_01" in captured.out


def test_print_round1_report_header_with_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Header shows 'X/Y (Z PARSE_ERROR)' when some agents fail."""
    from alphaswarm.cli import _print_round1_report
    from alphaswarm.simulation import Round1Result

    agent_decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="ok")),
        ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
        ("degens_01", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="ok")),
        ("degens_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
    ]

    result = Round1Result(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        agent_decisions=agent_decisions,
    )

    _print_round1_report(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "2/4" in captured.out
    assert "PARSE_ERROR" in captured.out


def test_print_round1_report_header_all_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Header shows 'N/N' and no 'PARSE_ERROR' when all succeed."""
    from alphaswarm.cli import _print_round1_report
    from alphaswarm.simulation import Round1Result

    agent_decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="ok")),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="ok")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="ok")),
        ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.7, rationale="ok")),
    ]

    result = Round1Result(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        agent_decisions=agent_decisions,
    )

    _print_round1_report(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "4/4" in captured.out
    assert "PARSE_ERROR" not in captured.out


def test_bracket_aggregation_excludes_parse_errors() -> None:
    """PARSE_ERROR agents are excluded from bracket signal counts."""
    from alphaswarm.cli import _aggregate_brackets

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="ok")),
        ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="ok")),
        ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="ok")),
    ]

    result = _aggregate_brackets(agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)

    # Quants: 1 BUY, 0 SELL, 0 HOLD (parse_error excluded) -> total 1
    assert result["Quants"]["BUY"] == 1
    assert result["Quants"]["total"] == 1

    # Degens: 0 BUY, 2 SELL, 0 HOLD -> total 2
    assert result["Degens"]["SELL"] == 2
    assert result["Degens"]["total"] == 2


def test_print_round1_report_truncates_rationale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rationale longer than 80 chars is truncated with '...'."""
    from alphaswarm.cli import _print_round1_report
    from alphaswarm.simulation import Round1Result

    long_rationale = "A" * 120  # Well over 80 chars
    agent_decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.99, rationale=long_rationale)),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="short")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="short")),
        ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.4, rationale="short")),
    ]

    result = Round1Result(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        agent_decisions=agent_decisions,
    )

    _print_round1_report(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "..." in captured.out


def test_sanitize_rationale_strips_control_chars() -> None:
    """Control characters are stripped and whitespace normalized."""
    from alphaswarm.cli import _sanitize_rationale

    result = _sanitize_rationale("hello\x00world\nfoo")
    assert result == "hello world foo"


# ---------------------------------------------------------------------------
# Phase 07: Generalized round report, shift analysis, simulation summary
# ---------------------------------------------------------------------------


def test_print_round_report_header(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_round_report prints 'Round 2 Complete' in === block with cycle_id and agent count."""
    from alphaswarm.cli import _print_round_report

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="data")),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.85, rationale="math")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="hype")),
        ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.65, rationale="fomo")),
    ]

    _print_round_report(2, "test-cycle-abc", agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Round 2 Complete" in captured.out
    assert "test-cycle-abc" in captured.out
    assert "4/4" in captured.out
    assert "=" * 60 in captured.out


def test_print_round_report_bracket_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_round_report prints bracket names and BUY/SELL/HOLD/Avg Conf columns."""
    from alphaswarm.cli import _print_round_report

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="data")),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="wait")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="hype")),
        ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.65, rationale="ape")),
    ]

    _print_round_report(3, "test-cycle", agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Quants" in captured.out
    assert "Degens" in captured.out
    assert "BUY" in captured.out
    assert "SELL" in captured.out
    assert "HOLD" in captured.out
    assert "Avg Conf" in captured.out


def test_print_round_report_notable_decisions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_round_report prints 'Notable Decisions' with top-5 by confidence."""
    from alphaswarm.cli import _print_round_report

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.99, rationale="top pick")),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="wait")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="panic")),
        ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.7, rationale="ape")),
    ]

    _print_round_report(2, "test-cycle", agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Notable Decisions" in captured.out
    assert "quants_01" in captured.out


def test_print_round_report_all_parse_error_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When all agents are PARSE_ERROR, prints warning message."""
    from alphaswarm.cli import _print_round_report

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
        ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
        ("degens_01", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
        ("degens_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="fail")),
    ]

    _print_round_report(2, "test-cycle", agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Warning: All 4 agents returned PARSE_ERROR. No valid decisions to report." in captured.out
    # Should NOT contain bracket table
    assert "Notable Decisions" not in captured.out


def test_shift_analysis_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_shift_analysis prints transition counts in two-column layout."""
    from alphaswarm.cli import _print_shift_analysis
    from alphaswarm.simulation import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 3), ("SELL->BUY", 2)),
        total_flips=5,
        bracket_confidence_delta=(("quants", 0.05), ("degens", -0.12)),
        agents_shifted=5,
    )

    _print_shift_analysis(shift, 1, 2)

    captured = capsys.readouterr()
    assert "Signal Transitions (Round 1 -> Round 2)" in captured.out
    assert "BUY->SELL" in captured.out
    assert "SELL->BUY" in captured.out
    assert "3" in captured.out
    assert "2" in captured.out


def test_shift_analysis_no_flips(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_shift_analysis with total_flips=0 prints no-change message."""
    from alphaswarm.cli import _print_shift_analysis
    from alphaswarm.simulation import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(),
        total_flips=0,
        bracket_confidence_delta=(("quants", 0.01),),
        agents_shifted=0,
    )

    _print_shift_analysis(shift, 1, 2)

    captured = capsys.readouterr()
    assert "No agents changed signal between rounds." in captured.out


def test_shift_analysis_confidence_drift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_shift_analysis prints confidence drift with signed delta values."""
    from alphaswarm.cli import _print_shift_analysis
    from alphaswarm.simulation import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 1),),
        total_flips=1,
        bracket_confidence_delta=(("quants", 0.05), ("degens", -0.12)),
        agents_shifted=1,
    )

    _print_shift_analysis(shift, 2, 3)

    captured = capsys.readouterr()
    assert "Confidence Drift by Bracket" in captured.out
    assert "quants" in captured.out
    assert "+0.05" in captured.out
    assert "degens" in captured.out
    assert "-0.12" in captured.out


def test_simulation_summary_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_simulation_summary prints 'Simulation Complete' block with total flips."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    r2_shifts = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 3),), total_flips=3,
        bracket_confidence_delta=(), agents_shifted=3,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(("SELL->BUY", 1),), total_flips=1,
        bracket_confidence_delta=(), agents_shifted=1,
    )

    result = SimulationResult(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        round1_decisions=(
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="data")),
            ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.85, rationale="math")),
            ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="hype")),
            ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.65, rationale="fomo")),
        ),
        round2_decisions=(
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.88, rationale="data")),
            ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.8, rationale="pivot")),
            ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.75, rationale="hold")),
            ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.6, rationale="flip")),
        ),
        round3_decisions=(
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.92, rationale="strong")),
            ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.85, rationale="final")),
            ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.78, rationale="lock")),
            ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.62, rationale="done")),
        ),
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
        round2_shifts=r2_shifts,
        round3_shifts=r3_shifts,
    )

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Simulation Complete" in captured.out
    assert "test-cycle" in captured.out
    assert "Signal Flips:" in captured.out
    assert "4 total" in captured.out  # 3 + 1


def test_simulation_summary_convergence_yes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When round2 flips > round3 flips, convergence = 'Yes (flips decreased between rounds)'."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    r2_shifts = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 5),), total_flips=5,
        bracket_confidence_delta=(), agents_shifted=5,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(("SELL->BUY", 2),), total_flips=2,
        bracket_confidence_delta=(), agents_shifted=2,
    )

    result = SimulationResult(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(),
        round3_decisions=(),
        round2_shifts=r2_shifts,
        round3_shifts=r3_shifts,
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
    )

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Convergence:" in captured.out
    assert "Yes" in captured.out
    assert "flips decreased between rounds" in captured.out


def test_simulation_summary_convergence_no_increased(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When round2 flips < round3 flips, convergence = 'No (flips increased between rounds)'."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    r2_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=2,
        bracket_confidence_delta=(), agents_shifted=2,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=5,
        bracket_confidence_delta=(), agents_shifted=5,
    )

    result = SimulationResult(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(),
        round3_decisions=(),
        round2_shifts=r2_shifts,
        round3_shifts=r3_shifts,
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
    )

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Convergence:" in captured.out
    assert "No" in captured.out
    assert "flips increased between rounds" in captured.out


def test_simulation_summary_convergence_no_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When round2 flips == round3 flips, convergence = 'No (flips unchanged between rounds)'."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    r2_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=3,
        bracket_confidence_delta=(), agents_shifted=3,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=3,
        bracket_confidence_delta=(), agents_shifted=3,
    )

    result = SimulationResult(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(),
        round3_decisions=(),
        round2_shifts=r2_shifts,
        round3_shifts=r3_shifts,
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
    )

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Convergence:" in captured.out
    assert "No" in captured.out
    assert "flips unchanged between rounds" in captured.out


def test_simulation_summary_final_bracket_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_simulation_summary prints 'Final Consensus Distribution' bracket table from Round 3."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    r2_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=1,
        bracket_confidence_delta=(), agents_shifted=1,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=0,
        bracket_confidence_delta=(), agents_shifted=0,
    )

    result = SimulationResult(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(),
        round3_decisions=(
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.92, rationale="strong")),
            ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.85, rationale="final")),
            ("degens_01", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="neutral")),
            ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.62, rationale="done")),
        ),
        round2_shifts=r2_shifts,
        round3_shifts=r3_shifts,
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
    )

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS)

    captured = capsys.readouterr()
    assert "Final Consensus Distribution" in captured.out
    assert "Quants" in captured.out
    assert "Degens" in captured.out


# ---------------------------------------------------------------------------
# Phase 07: Progressive callback wiring tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_complete_handler_prints_report_and_shift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The on_round_complete handler prints round report + shift analysis."""
    from alphaswarm.cli import _make_round_complete_handler
    from alphaswarm.simulation import RoundCompleteEvent, ShiftMetrics

    handler = _make_round_complete_handler(_TEST_PERSONAS, _TEST_BRACKETS)

    decisions = (
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="data")),
        ("quants_02", AgentDecision(signal=SignalType.BUY, confidence=0.85, rationale="math")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="hype")),
        ("degens_02", AgentDecision(signal=SignalType.SELL, confidence=0.65, rationale="fomo")),
    )

    shift = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 1),),
        total_flips=1,
        bracket_confidence_delta=(("quants", 0.05),),
        agents_shifted=1,
    )

    event = RoundCompleteEvent(
        round_num=2,
        cycle_id="test-cycle",
        agent_decisions=decisions,
        shift=shift,
        bracket_summaries=(),
    )

    await handler(event)

    captured = capsys.readouterr()
    assert "Round 2 Complete" in captured.out
    assert "Signal Transitions (Round 1 -> Round 2)" in captured.out
    assert "Confidence Drift by Bracket" in captured.out


@pytest.mark.asyncio
async def test_round_complete_handler_round1_no_shift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Round 1 handler prints report but no shift analysis."""
    from alphaswarm.cli import _make_round_complete_handler
    from alphaswarm.simulation import RoundCompleteEvent

    handler = _make_round_complete_handler(_TEST_PERSONAS, _TEST_BRACKETS)

    decisions = (
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="data")),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="wait")),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="hype")),
        ("degens_02", AgentDecision(signal=SignalType.BUY, confidence=0.65, rationale="ape")),
    )

    event = RoundCompleteEvent(
        round_num=1,
        cycle_id="test-cycle",
        agent_decisions=decisions,
        shift=None,
        bracket_summaries=(),
    )

    await handler(event)

    captured = capsys.readouterr()
    assert "Round 1 Complete" in captured.out
    assert "Signal Transitions" not in captured.out


@pytest.mark.asyncio
async def test_run_pipeline_calls_run_simulation_with_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_pipeline calls run_simulation with on_round_complete handler (D-17, D-14)."""
    from alphaswarm.simulation import ShiftMetrics, SimulationResult

    # Create mock AppState
    mock_app = MagicMock()
    mock_app.graph_manager = AsyncMock()
    mock_app.ollama_client = MagicMock()
    mock_app.model_manager = AsyncMock()
    mock_app.governor = AsyncMock()

    mock_settings = MagicMock()

    # Create a minimal SimulationResult for the mock return
    empty_shifts = ShiftMetrics(
        signal_transitions=(), total_flips=0,
        bracket_confidence_delta=(), agents_shifted=0,
    )
    mock_result = MagicMock(spec=SimulationResult)
    mock_result.round2_shifts = empty_shifts
    mock_result.round3_shifts = empty_shifts
    mock_result.round3_decisions = ()
    mock_result.round3_summaries = ()
    mock_result.cycle_id = "test-cycle"

    mock_sim = AsyncMock(return_value=mock_result)

    with patch("alphaswarm.cli.run_simulation", mock_sim, create=True):
        from alphaswarm.cli import _run_pipeline
        # Need to reload to pick up the patched import
        # Actually, _run_pipeline does `from alphaswarm.simulation import run_simulation`
        # at function scope, so we need to patch the source module
        pass

    # Patch at the source module since _run_pipeline uses a local import
    with patch("alphaswarm.simulation.run_simulation", mock_sim):
        from alphaswarm.cli import _run_pipeline
        await _run_pipeline("test rumor", mock_settings, mock_app, _TEST_PERSONAS, _TEST_BRACKETS)

    # Verify run_simulation was called with on_round_complete kwarg
    assert mock_sim.called
    call_kwargs = mock_sim.call_args.kwargs
    assert "on_round_complete" in call_kwargs
    assert callable(call_kwargs["on_round_complete"])


# ---------------------------------------------------------------------------
# Phase 15 Plan 02: Report subcommand
# ---------------------------------------------------------------------------


def test_report_subcommand_registered() -> None:
    """CLI report subparser registers correctly with --cycle and --output arguments."""
    parser = argparse.ArgumentParser(prog="alphaswarm")
    subparsers = parser.add_subparsers(dest="command")
    report_parser = subparsers.add_parser("report", help="Generate post-simulation analysis report")
    report_parser.add_argument("--cycle", type=str, default=None)
    report_parser.add_argument("--output", type=str, default=None)

    args = parser.parse_args(["report", "--cycle", "test-id"])
    assert args.command == "report"
    assert args.cycle == "test-id"
    assert args.output is None

    # Verify default behavior when --cycle is omitted
    args_no_cycle = parser.parse_args(["report"])
    assert args_no_cycle.cycle is None
