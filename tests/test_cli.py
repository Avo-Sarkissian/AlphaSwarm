"""Unit tests for CLI module (argparse routing, inject subcommand, run subcommand, banner, report)."""

from __future__ import annotations

import argparse
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.inference.types import ProviderRole
from alphaswarm.settings import AppSettings
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
from tests.inference.fakes import FakeInferenceProvider


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

    with (
        patch("alphaswarm.cli.AppSettings", return_value=mock_settings),
        patch("alphaswarm.cli.load_bracket_configs") as mock_brackets,
        patch("alphaswarm.cli.generate_personas") as mock_personas,
    ):
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

    def _close(coro: Coroutine[Any, Any, None]) -> None:
        coro.close()  # the mocked asyncio.run never awaits it

    with patch("alphaswarm.cli.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock(side_effect=_close)
        main()

    mock_asyncio.run.assert_called_once()


def test_main_inject_failure_prints_error_to_stderr(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() with inject args prints 'Error:' to stderr when asyncio.run raises."""
    from alphaswarm.cli import main

    monkeypatch.setattr("sys.argv", ["alphaswarm", "inject", "bad rumor"])

    def _close_then_fail(coro: Coroutine[Any, Any, None]) -> None:
        coro.close()
        raise Exception("Connection failed")

    with patch("alphaswarm.cli.asyncio") as mock_asyncio, patch("alphaswarm.cli.logger"):
        mock_asyncio.run.side_effect = _close_then_fail
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


async def test_handle_inject_marks_the_seed_only_cycle_failed(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    fallback_parsed_result: ParsedSeedResult,
) -> None:
    """No run ever follows inject, so its cycle must not read as running (docs/DECISIONS.md#adr-cycle-metrics)."""
    from alphaswarm.cli import _handle_inject

    graph = AsyncMock()
    app = MagicMock(graph_manager=graph)
    built = MagicMock()
    built.orchestrator.aclose = AsyncMock()
    inject = AsyncMock(return_value=("c-seed-only", fallback_parsed_result, None))
    monkeypatch.setattr("alphaswarm.app.create_app_state", MagicMock(return_value=app))
    monkeypatch.setattr("alphaswarm.inference.config.load_inference_config", MagicMock())
    monkeypatch.setattr("alphaswarm.inference.factory.build_providers", MagicMock(return_value=built))
    monkeypatch.setattr("alphaswarm.seed.inject_seed", inject)

    await _handle_inject("ZZZT Holdings is in late-stage talks to acquire QQQX Robotics.")

    assert inject.await_args.kwargs["orchestrator"] is built.orchestrator
    graph.set_cycle_status.assert_awaited_once_with("c-seed-only", "failed")
    graph.close.assert_awaited_once()
    assert "c-seed-only" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Phase 06: Run subcommand and report tests
# ---------------------------------------------------------------------------


# Shared test data for the round report tests

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
        id="quants_01",
        name="Quants 1",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="quants_02",
        name="Quants 2",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="degens_01",
        name="Degens 1",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test",
        influence_weight_base=0.3,
    ),
    AgentPersona(
        id="degens_02",
        name="Degens 2",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test",
        influence_weight_base=0.3,
    ),
]

_TEST_BRACKETS = [
    BracketConfig(
        bracket_type=BracketType.QUANTS,
        display_name="Quants",
        count=2,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt_template="test",
        influence_weight_base=0.7,
    ),
    BracketConfig(
        bracket_type=BracketType.DEGENS,
        display_name="Degens",
        count=2,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt_template="test",
        influence_weight_base=0.3,
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


def test_print_round_report_header_counts_parse_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A partly failed round shows 'X/Y (Z PARSE_ERROR)'; a clean round shows 'N/N' only."""
    from alphaswarm.cli import _print_round_report

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="ok")),
        ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="x")),
        ("degens_01", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="ok")),
        ("degens_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="x")),
    ]

    _print_round_report(2, "test-cycle", agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)
    assert "  Agents:   2/4 (2 PARSE_ERROR)\n" in capsys.readouterr().out

    clean = [(aid, d) for aid, d in agent_decisions if d.signal != SignalType.PARSE_ERROR]
    _print_round_report(2, "test-cycle", clean, _TEST_PERSONAS, _TEST_BRACKETS)
    out = capsys.readouterr().out
    assert "  Agents:   2/2\n" in out
    assert "PARSE_ERROR" not in out


def test_print_round_report_truncates_long_rationale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Notable Decisions cut a rationale at 80 characters and append '...'."""
    from alphaswarm.cli import _print_round_report

    agent_decisions: list[tuple[str, AgentDecision]] = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.99, rationale="A" * 120)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="short")),
    ]

    _print_round_report(3, "test-cycle", agent_decisions, _TEST_PERSONAS, _TEST_BRACKETS)

    out = capsys.readouterr().out
    assert "A" * 80 + "..." in out
    assert "A" * 81 not in out
    assert "short" in out


def test_shift_analysis_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_shift_analysis prints transition counts in two-column layout."""
    from alphaswarm.cli import _print_shift_analysis
    from alphaswarm.rounds import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 3), ("SELL->BUY", 2)),
        total_flips=5,
        bracket_confidence_delta=(("quants", 0.05), ("degens", -0.12)),
        agents_shifted=5,
    )

    _print_shift_analysis(shift, 1, 2, agent_count=4)

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
    from alphaswarm.rounds import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(),
        total_flips=0,
        bracket_confidence_delta=(("quants", 0.01),),
        agents_shifted=0,
    )

    _print_shift_analysis(shift, 1, 2, agent_count=4)

    captured = capsys.readouterr()
    assert "No agents changed signal between rounds." in captured.out


def test_shift_analysis_confidence_drift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_shift_analysis prints confidence drift with signed delta values."""
    from alphaswarm.cli import _print_shift_analysis
    from alphaswarm.rounds import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 1),),
        total_flips=1,
        bracket_confidence_delta=(("quants", 0.05), ("degens", -0.12)),
        agents_shifted=1,
    )

    _print_shift_analysis(shift, 2, 3, agent_count=4)

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
    from alphaswarm.rounds import ShiftMetrics

    r2_shifts = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 3),),
        total_flips=3,
        bracket_confidence_delta=(),
        agents_shifted=3,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(("SELL->BUY", 1),),
        total_flips=1,
        bracket_confidence_delta=(),
        agents_shifted=1,
    )

    result = _result_from_round_fields(
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

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)

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
    from alphaswarm.rounds import ShiftMetrics

    r2_shifts = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 5),),
        total_flips=5,
        bracket_confidence_delta=(),
        agents_shifted=5,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(("SELL->BUY", 2),),
        total_flips=2,
        bracket_confidence_delta=(),
        agents_shifted=2,
    )

    result = _result_from_round_fields(
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

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)

    captured = capsys.readouterr()
    assert "Convergence:" in captured.out
    assert "Yes" in captured.out
    assert "flips decreased between rounds" in captured.out


def test_simulation_summary_convergence_no_increased(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When round2 flips < round3 flips, convergence = 'No (flips increased between rounds)'."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.rounds import ShiftMetrics

    r2_shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=2,
        bracket_confidence_delta=(),
        agents_shifted=2,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=5,
        bracket_confidence_delta=(),
        agents_shifted=5,
    )

    result = _result_from_round_fields(
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

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)

    captured = capsys.readouterr()
    assert "Convergence:" in captured.out
    assert "No" in captured.out
    assert "flips increased between rounds" in captured.out


def test_simulation_summary_convergence_no_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When round2 flips == round3 flips, convergence = 'No (flips unchanged between rounds)'."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.rounds import ShiftMetrics

    r2_shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=3,
        bracket_confidence_delta=(),
        agents_shifted=3,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=3,
        bracket_confidence_delta=(),
        agents_shifted=3,
    )

    result = _result_from_round_fields(
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

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)

    captured = capsys.readouterr()
    assert "Convergence:" in captured.out
    assert "No" in captured.out
    assert "flips unchanged between rounds" in captured.out


def test_simulation_summary_final_bracket_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_simulation_summary prints 'Final Consensus Distribution' bracket table from Round 3."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.rounds import ShiftMetrics

    r2_shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=1,
        bracket_confidence_delta=(),
        agents_shifted=1,
    )
    r3_shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=0,
        bracket_confidence_delta=(),
        agents_shifted=0,
    )

    result = _result_from_round_fields(
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

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)

    captured = capsys.readouterr()
    assert "Final Consensus Distribution" in captured.out
    assert "Quants" in captured.out
    assert "Degens" in captured.out


# ---------------------------------------------------------------------------
# Phase 07: Progressive callback wiring tests
# ---------------------------------------------------------------------------


async def test_round_complete_handler_prints_report_and_shift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The on_round_complete handler prints round report + shift analysis."""
    from alphaswarm.cli import _make_round_complete_handler
    from alphaswarm.rounds import RoundCompleteEvent, ShiftMetrics

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


async def test_round_complete_handler_round1_no_shift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Round 1 handler prints report but no shift analysis."""
    from alphaswarm.cli import _make_round_complete_handler
    from alphaswarm.rounds import RoundCompleteEvent

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


def _empty_simulation_result() -> Any:
    from alphaswarm.simulation import SimulationResult
    from alphaswarm.types import ParsedSeedResult, SeedEvent

    seed = SeedEvent(raw_rumor="test rumor", entities=[], overall_sentiment=0.0)
    return SimulationResult(
        cycle_id="test-cycle",
        parsed_result=ParsedSeedResult(seed_event=seed, parse_tier=1),
        rounds=(),
    )


def _pipeline_app() -> MagicMock:
    app = MagicMock()
    app.graph_manager = AsyncMock()
    return app


def _fake_provider(role: ProviderRole) -> FakeInferenceProvider:
    return FakeInferenceProvider(role, f"fake-{role.value}", scripted=[])


async def test_run_pipeline_calls_run_simulation_with_callback() -> None:
    """_run_pipeline passes an on_round_complete handler (docs/DECISIONS.md#p7-d-14)."""
    mock_sim = AsyncMock(return_value=_empty_simulation_result())
    with patch("alphaswarm.simulation.run_simulation", mock_sim):
        from alphaswarm.cli import _run_pipeline

        await _run_pipeline(
            "test rumor",
            AppSettings(_env_file=None),  # type: ignore[call-arg]
            _pipeline_app(),
            _TEST_PERSONAS,
            _TEST_BRACKETS,
            orchestrator_provider=_fake_provider(ProviderRole.ORCHESTRATOR),
            worker_provider=_fake_provider(ProviderRole.WORKER),
            controller=MagicMock(),
        )

    assert callable(mock_sim.call_args.kwargs["on_round_complete"])


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


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 40 Plan 03 Task 2: CLI provider construction (D-11)
# ---------------------------------------------------------------------------


async def test_run_pipeline_constructs_providers() -> None:
    """The CLI builds SimulationDeps with real yfinance and RSS providers
    (docs/DECISIONS.md#adr-market-context)."""
    from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider

    orchestrator = _fake_provider(ProviderRole.ORCHESTRATOR)
    worker = _fake_provider(ProviderRole.WORKER)
    controller = MagicMock()
    mock_sim = AsyncMock(return_value=_empty_simulation_result())
    with patch("alphaswarm.simulation.run_simulation", mock_sim):
        from alphaswarm.cli import _run_pipeline

        await _run_pipeline(
            "test rumor",
            AppSettings(_env_file=None),  # type: ignore[call-arg]
            _pipeline_app(),
            _TEST_PERSONAS,
            _TEST_BRACKETS,
            orchestrator_provider=orchestrator,
            worker_provider=worker,
            controller=controller,
        )

    deps = mock_sim.call_args.kwargs["deps"]
    assert isinstance(deps.market, YFinanceMarketDataProvider)
    assert isinstance(deps.news, RSSNewsProvider)
    assert (deps.orchestrator, deps.worker, deps.controller) == (orchestrator, worker, controller)


@pytest.mark.parametrize("mode", ["context_fixture", "no_market_context"])
async def test_run_pipeline_point_in_time_runs_build_no_live_providers(mode: str) -> None:
    """A fixture or --no-market-context run builds no YFinance/RSS provider, and the
    fixture is what reaches run_simulation (docs/DECISIONS.md#adr-eval-harness)."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from alphaswarm.ingestion.fixture import build_fixture_packet

    packet = build_fixture_packet(
        event_id="evt-001",
        as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
        ticker="ZZZT",
        close=Decimal("123.45"),
        volume=1_000_000,
    )
    run_kwargs: dict[str, Any] = {"context_fixture": packet} if mode == "context_fixture" else {"market_context": False}
    mock_sim = AsyncMock(return_value=_empty_simulation_result())

    with (
        patch("alphaswarm.simulation.run_simulation", mock_sim),
        patch("alphaswarm.cli.YFinanceMarketDataProvider") as market_cls,
        patch("alphaswarm.cli.RSSNewsProvider") as news_cls,
    ):
        from alphaswarm.cli import _run_pipeline

        await _run_pipeline(
            "test rumor",
            AppSettings(_env_file=None),  # type: ignore[call-arg]
            _pipeline_app(),
            _TEST_PERSONAS,
            _TEST_BRACKETS,
            orchestrator_provider=_fake_provider(ProviderRole.ORCHESTRATOR),
            worker_provider=_fake_provider(ProviderRole.WORKER),
            controller=MagicMock(),
            **run_kwargs,
        )

    market_cls.assert_not_called()
    news_cls.assert_not_called()
    deps = mock_sim.call_args.kwargs["deps"]
    assert (deps.market, deps.news) == (None, None)
    assert deps.context_fixture is (packet if mode == "context_fixture" else None)


def test_shift_analysis_uses_actual_agent_count(capsys: pytest.CaptureFixture[str]) -> None:
    from alphaswarm.cli import _print_shift_analysis
    from alphaswarm.rounds import ShiftMetrics

    shift = ShiftMetrics(
        signal_transitions=(("BUY->SELL", 2),),
        total_flips=2,
        bracket_confidence_delta=(),
        agents_shifted=2,
    )
    _print_shift_analysis(shift, 1, 2, agent_count=4)

    out = capsys.readouterr().out
    assert "Total agents shifted: 2/4" in out
    assert "/100" not in out


def test_simulation_summary_for_two_rounds(capsys: pytest.CaptureFixture[str]) -> None:
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.rounds import ShiftMetrics

    empty = ShiftMetrics(signal_transitions=(), total_flips=0, bracket_confidence_delta=(), agents_shifted=0)
    result = _result_from_round_fields(
        cycle_id="test-cycle",
        parsed_result=_MOCK_PARSED_RESULT,
        round1_decisions=(),
        round2_decisions=(
            ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="r")),
            ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="r")),
        ),
        round3_decisions=(),
        round2_shifts=ShiftMetrics(
            signal_transitions=(("BUY->SELL", 1),), total_flips=1, bracket_confidence_delta=(), agents_shifted=1
        ),
        round3_shifts=empty,
        round1_summaries=(),
        round2_summaries=(),
        round3_summaries=(),
    )

    _print_simulation_summary(result, _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=2)

    out = capsys.readouterr().out
    assert "Total Rounds:   2" in out
    assert "1 (R1->R2) = 1 total" in out
    assert "R2->R3" not in out
    assert "Convergence:    n/a (needs 3 rounds)" in out
    assert "Final Consensus Distribution (Round 2)" in out
    assert "Quants" in out and "Degens" in out


# ---------------------------------------------------------------------------
# Bracket tables come from compute_bracket_summaries in every path
# ---------------------------------------------------------------------------

_MIXED_DECISIONS: list[tuple[str, AgentDecision]] = [
    ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.9, rationale="ok")),
    ("quants_02", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="x")),
    ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="ok")),
    ("degens_02", AgentDecision(signal=SignalType.HOLD, confidence=0.6, rationale="ok")),
]


def test_round_report_fallback_table_matches_engine_summaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without precomputed summaries the round table equals the engine's summaries."""
    from alphaswarm.cli import _print_round_report
    from alphaswarm.rounds import compute_bracket_summaries

    _print_round_report(2, "c1", _MIXED_DECISIONS, _TEST_PERSONAS, _TEST_BRACKETS)
    fallback = capsys.readouterr().out
    summaries = compute_bracket_summaries(_MIXED_DECISIONS, _TEST_PERSONAS, _TEST_BRACKETS)
    _print_round_report(
        2,
        "c1",
        _MIXED_DECISIONS,
        _TEST_PERSONAS,
        _TEST_BRACKETS,
        bracket_summaries=summaries,
    )
    assert capsys.readouterr().out == fallback


def test_simulation_summary_fallback_table_matches_engine_summaries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty round3_summaries tuple renders the same table as computed summaries."""
    from alphaswarm.cli import _print_simulation_summary
    from alphaswarm.rounds import ShiftMetrics, compute_bracket_summaries
    from alphaswarm.simulation import SimulationResult

    shifts = ShiftMetrics(
        signal_transitions=(),
        total_flips=0,
        bracket_confidence_delta=(),
        agents_shifted=0,
    )

    def _result(summaries: tuple[object, ...]) -> SimulationResult:
        return _result_from_round_fields(
            cycle_id="c1",
            parsed_result=_MOCK_PARSED_RESULT,
            round1_decisions=(),
            round2_decisions=(),
            round3_decisions=tuple(_MIXED_DECISIONS),
            round2_shifts=shifts,
            round3_shifts=shifts,
            round1_summaries=(),
            round2_summaries=(),
            round3_summaries=summaries,  # type: ignore[arg-type]
        )

    _print_simulation_summary(_result(()), _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)
    fallback = capsys.readouterr().out
    computed = compute_bracket_summaries(_MIXED_DECISIONS, _TEST_PERSONAS, _TEST_BRACKETS)
    _print_simulation_summary(_result(computed), _TEST_PERSONAS, _TEST_BRACKETS, num_rounds=3)
    assert capsys.readouterr().out == fallback


def _result_from_round_fields(
    *,
    cycle_id: str,
    parsed_result: Any,
    round1_decisions: Any = (),
    round2_decisions: Any = (),
    round3_decisions: Any = (),
    round2_shifts: Any = None,
    round3_shifts: Any = None,
    round1_summaries: Any = (),
    round2_summaries: Any = (),
    round3_summaries: Any = (),
) -> Any:
    """A SimulationResult from per-round fields: one RoundOutcome per round
    (docs/DECISIONS.md#p7-d-08). Keeps the printer tests independent of the result shape."""
    from alphaswarm.rounds import RoundOutcome
    from alphaswarm.simulation import SimulationResult

    per_round = {
        1: (round1_decisions, None, round1_summaries),
        2: (round2_decisions, round2_shifts, round2_summaries),
        3: (round3_decisions, round3_shifts, round3_summaries),
    }
    rounds = tuple(
        RoundOutcome(
            round_num=n,
            decisions=tuple(decisions),
            decision_ids=(),
            exposures=(),
            shift=shift,
            bracket_summaries=tuple(summaries),
            influence_weights={},
            applied_shocks=(),
            seconds=0.0,
            metrics={},
        )
        for n, (decisions, shift, summaries) in per_round.items()
    )
    return SimulationResult(cycle_id=cycle_id, parsed_result=parsed_result, rounds=rounds)
