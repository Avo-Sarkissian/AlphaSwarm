"""Unit tests for CLI module (argparse routing, inject subcommand, banner)."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.types import EntityType, ParsedSeedResult, SeedEntity, SeedEvent


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
