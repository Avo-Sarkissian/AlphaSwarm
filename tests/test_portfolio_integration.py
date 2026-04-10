"""Integration tests for Phase 25 wiring — CLI + HTML + system prompt + deterministic pre-seeding."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.report import (
    REACT_SYSTEM_PROMPT,
    ReportEngine,
    ToolObservation,
    build_react_system_prompt,
)


class TestReactSystemPromptBuilder:
    def test_default_excludes_portfolio(self) -> None:
        prompt = build_react_system_prompt()
        assert "portfolio_impact" not in prompt

    def test_default_excludes_portfolio_mandate(self) -> None:
        prompt = build_react_system_prompt()
        assert "PORTFOLIO REPORTING CONTRACT" not in prompt
        assert "MUST call it" not in prompt

    def test_include_portfolio_true_adds_tool_line(self) -> None:
        prompt = build_react_system_prompt(include_portfolio=True)
        assert "portfolio_impact" in prompt
        assert "Map user's Schwab portfolio" in prompt

    def test_include_portfolio_true_contains_mandatory_clause(self) -> None:
        """REVIEWS HIGH concern: mandatory MUST-call instruction."""
        prompt = build_react_system_prompt(include_portfolio=True)
        assert "PORTFOLIO REPORTING CONTRACT" in prompt
        assert "you MUST call it at least once" in prompt
        assert "MUST include a paragraph in your FINAL ANSWER" in prompt

    def test_include_portfolio_true_contains_context_awareness_clause(self) -> None:
        """REPLAN-7: explicit CONTEXT AWARENESS clause so the LLM knows the
        pre-seeded observation is already in its conversation context."""
        prompt = build_react_system_prompt(include_portfolio=True)
        assert "CONTEXT AWARENESS" in prompt
        assert "You already have a portfolio_impact observation" in prompt

    def test_default_matches_module_constant(self) -> None:
        assert build_react_system_prompt() == REACT_SYSTEM_PROMPT

    def test_default_still_mentions_all_8_existing_tools(self) -> None:
        prompt = build_react_system_prompt()
        for tool in [
            "consensus_summary",
            "round_timeline",
            "bracket_narratives",
            "key_dissenters",
            "influence_leaders",
            "signal_flips",
            "entity_impact",
            "social_post_reach",
            "FINAL_ANSWER",
        ]:
            assert tool in prompt, f"Missing tool: {tool}"

    def test_portfolio_variant_still_mentions_all_existing_tools(self) -> None:
        prompt = build_react_system_prompt(include_portfolio=True)
        for tool in [
            "consensus_summary",
            "round_timeline",
            "bracket_narratives",
            "key_dissenters",
            "influence_leaders",
            "signal_flips",
            "entity_impact",
            "social_post_reach",
            "FINAL_ANSWER",
        ]:
            assert tool in prompt, f"Missing tool: {tool}"


class TestReportEnginePreSeededObservations:
    """Deterministic portfolio delivery: engine must include pre-seeded observations
    in its result even if the ReACT loop never calls the corresponding tool."""

    def _make_engine(
        self,
        *,
        tools: dict[str, Any] | None = None,
        pre_seeded: list[ToolObservation] | None = None,
        system_prompt: str | None = None,
    ) -> ReportEngine:
        fake_ollama = MagicMock()
        return ReportEngine(
            ollama_client=fake_ollama,
            model="qwen3.5:35b",
            tools=tools or {},
            system_prompt=system_prompt,
            pre_seeded_observations=pre_seeded,
        )

    def test_default_pre_seeded_is_empty(self) -> None:
        engine = self._make_engine()
        assert engine._pre_seeded == []

    def test_pre_seeded_accepted(self) -> None:
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={"matched_tickers": [], "gap_tickers": [], "coverage_summary": {}},
        )
        engine = self._make_engine(pre_seeded=[obs])
        assert len(engine._pre_seeded) == 1
        assert engine._pre_seeded[0].tool_name == "portfolio_impact"

    @pytest.mark.asyncio
    async def test_run_returns_pre_seeded_even_when_llm_exits_immediately(
        self,
    ) -> None:
        """If the LLM returns FINAL_ANSWER without calling any tool, pre-seeded
        observations must still appear in the returned list."""
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 0,
                    "total_equity_holdings": 0,
                    "coverage_pct": 0.0,
                },
            },
        )

        # Real ollama_client mock — returns FINAL_ANSWER so run() exits on first iteration.
        fake_ollama = MagicMock()

        async def fake_chat(*, model, messages, think=False, **kwargs):
            response = MagicMock()
            response.message.content = "THOUGHT: done\nACTION: FINAL_ANSWER\nINPUT: {}"
            return response

        fake_ollama.chat = fake_chat

        engine = ReportEngine(
            ollama_client=fake_ollama,
            model="qwen3.5:35b",
            tools={},
            pre_seeded_observations=[obs],
        )
        result = await engine.run("c1")
        assert len(result) == 1
        assert result[0].tool_name == "portfolio_impact"

    @pytest.mark.asyncio
    async def test_pre_seeded_observations_appear_in_llm_messages(
        self,
    ) -> None:
        """REPLAN-3/REPLAN-7: pre-seeded observations must be injected into the
        `messages` list (LLM conversation) BEFORE the first chat() call, so the
        model can see the pre-computed data in its context window."""
        import json as _json

        from alphaswarm import report as report_module

        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [{"ticker": "AAPL", "signal": "BUY"}],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 1,
                    "total_equity_holdings": 1,
                    "coverage_pct": 100.0,
                },
            },
        )

        captured_messages: list[list[dict]] = []

        async def fake_chat(*, model, messages, think=False, **kwargs):
            # Snapshot the messages on each call so we can assert the very first
            # call already has the pre-seeded observation in the context.
            captured_messages.append([dict(m) for m in messages])
            response = MagicMock()
            response.message.content = "THOUGHT: done\nACTION: FINAL_ANSWER\nINPUT: {}"
            return response

        fake_ollama = MagicMock()
        fake_ollama.chat = fake_chat

        engine = ReportEngine(
            ollama_client=fake_ollama,
            model="qwen3.5:35b",
            tools={},
            system_prompt=report_module.build_react_system_prompt(include_portfolio=True),
            pre_seeded_observations=[obs],
        )
        await engine.run("c1")

        assert len(captured_messages) >= 1, "ollama_client.chat was never called"
        first_call_messages = captured_messages[0]

        # The first message must be the system prompt
        assert first_call_messages[0]["role"] == "system"
        assert "portfolio_impact" in first_call_messages[0]["content"]
        assert "CONTEXT AWARENESS" in first_call_messages[0]["content"]

        # Find the injected OBSERVATION user message
        observation_messages = [
            m
            for m in first_call_messages
            if m["role"] == "user"
            and m["content"].startswith("OBSERVATION: portfolio_impact:")
        ]
        assert len(observation_messages) == 1, (
            "pre-seeded portfolio_impact observation must be injected as a "
            "user message BEFORE the first chat() call (REPLAN-3/REPLAN-7)"
        )
        # The JSON payload must round-trip the result dict
        payload = observation_messages[0]["content"].split(
            "OBSERVATION: portfolio_impact: ", 1
        )[1]
        parsed = _json.loads(payload)
        assert parsed["coverage_summary"]["covered"] == 1
        assert parsed["matched_tickers"][0]["ticker"] == "AAPL"


# -----------------------------------------------------------------------------
# CLI integration (Task 2)
# -----------------------------------------------------------------------------

import argparse
from pathlib import Path


class TestReportSubparserPortfolioFlag:
    def test_subparser_accepts_portfolio_flag(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        rp = subparsers.add_parser("report")
        rp.add_argument("--cycle", type=str, default=None)
        rp.add_argument("--output", type=str, default=None)
        rp.add_argument(
            "--format",
            type=str,
            choices=["md", "html"],
            default="md",
            dest="report_format",
        )
        rp.add_argument("--portfolio", type=str, default=None)
        args = parser.parse_args(["report", "--portfolio", "/tmp/x.csv"])
        assert args.portfolio == "/tmp/x.csv"

    def test_cli_source_contains_portfolio_help_text(self) -> None:
        from alphaswarm import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        assert "--portfolio" in source
        assert "Schwab Individual-Positions CSV" in source
        assert "loaded in-memory only" in source


def _make_fake_app() -> MagicMock:
    """Build a fake AppState with async stubs for the graph + model layers.

    Mirrors the minimal surface of AppState that _handle_report touches:
    ollama_client, graph_manager (with read_latest_cycle_id, read_entity_impact,
    close), model_manager (with load_model / unload_model).
    """
    fake_app = MagicMock()
    fake_app.ollama_client = MagicMock()
    fake_app.graph_manager = AsyncMock()
    fake_app.graph_manager.read_latest_cycle_id = AsyncMock(return_value="cycle-xyz")
    fake_app.graph_manager.read_entity_impact = AsyncMock(
        return_value=[
            {
                "entity_name": "Apple Inc",
                "mention_count": 10,
                "avg_sentiment": 0.5,
                "dominant_signal": "BUY",
                "signal_confidence": 0.8,
            },
        ]
    )
    fake_app.graph_manager.close = AsyncMock()
    fake_app.model_manager = AsyncMock()
    fake_app.model_manager.load_model = AsyncMock()
    fake_app.model_manager.unload_model = AsyncMock()
    return fake_app


def _patch_app_factory(monkeypatch: pytest.MonkeyPatch, fake_app: MagicMock) -> None:
    """Patch the factory + config helpers used by _handle_report.

    _handle_report imports create_app_state from alphaswarm.app inside the
    function body, so we must patch it where it is DEFINED (alphaswarm.app),
    not where it is referenced (alphaswarm.cli). The config helpers are
    imported at module level in cli.py, so those are patched on cli directly.
    """
    from alphaswarm import app as app_module
    from alphaswarm import cli as cli_module

    monkeypatch.setattr(app_module, "create_app_state", lambda *a, **k: fake_app)
    monkeypatch.setattr(cli_module, "load_bracket_configs", lambda: {})
    monkeypatch.setattr(cli_module, "generate_personas", lambda b: [])


@pytest.mark.asyncio
async def test_handle_report_missing_portfolio_path_raises_system_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REVIEWS HIGH (Codex): explicit --portfolio with bad path must fail-fast."""
    from alphaswarm import cli as cli_module

    _patch_app_factory(monkeypatch, _make_fake_app())

    with pytest.raises(SystemExit) as excinfo:
        await cli_module._handle_report(
            cycle_id=None,
            output=str(tmp_path / "out.md"),
            fmt="md",
            portfolio_path="/definitely/does/not/exist.csv",
        )
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "--portfolio file not found" in captured.err


@pytest.mark.asyncio
async def test_handle_report_portfolio_path_is_directory_raises(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REVIEWS HIGH (Codex): path that exists but is not a regular file fails fast."""
    from alphaswarm import cli as cli_module

    _patch_app_factory(monkeypatch, _make_fake_app())

    with pytest.raises(SystemExit) as excinfo:
        await cli_module._handle_report(
            cycle_id=None,
            output=str(tmp_path / "out.md"),
            fmt="md",
            portfolio_path=str(tmp_path),  # directory, not a file
        )
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "not a regular file" in captured.err


@pytest.mark.asyncio
async def test_handle_report_empty_equity_holdings_raises(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REVIEWS HIGH (Codex): zero parseable equity holdings fails fast, does not skip silently."""
    from alphaswarm import cli as cli_module

    # CSV with only non-equity rows.
    csv_path = tmp_path / "nonequity.csv"
    csv_path.write_text(
        '"Positions for account Individual",,,,,,,,,,,,,,,,,\n'
        "\n"
        '"Symbol","Description","Qty (Quantity)","Price","Price Chng %","Price Chng $","Mkt Val (Market Value)","Day Chng %","Day Chng $","Cost Basis","Gain $","Gain %","Ratings","Reinvest Dividends?","Capital Gains?","% Of Account","Security Type","Asset Type"\n'
        '"VMFXX","MONEY MARKET","1000","1.00","--","--","$1,000.00","--","--","$1000","$0","0%","--","Yes","Yes","10%","Money Market","Cash and Money Market"\n',
        encoding="utf-8",
    )

    _patch_app_factory(monkeypatch, _make_fake_app())

    with pytest.raises(SystemExit) as excinfo:
        await cli_module._handle_report(
            cycle_id=None,
            output=str(tmp_path / "out.md"),
            fmt="md",
            portfolio_path=str(csv_path),
        )
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "zero parseable equity holdings" in captured.err


@pytest.mark.asyncio
async def test_handle_report_malformed_csv_raises(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REVIEWS HIGH (Codex): malformed CSV fails fast with clear error."""
    from alphaswarm import cli as cli_module

    # CSV missing required Symbol/Asset Type header row.
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("garbage\nno,header,here\n", encoding="utf-8")

    _patch_app_factory(monkeypatch, _make_fake_app())

    with pytest.raises(SystemExit) as excinfo:
        await cli_module._handle_report(
            cycle_id=None,
            output=str(tmp_path / "out.md"),
            fmt="md",
            portfolio_path=str(csv_path),
        )
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "malformed" in captured.err or "failed to read" in captured.err


@pytest.mark.asyncio
async def test_handle_report_without_portfolio_flag_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-16: no --portfolio => identical behavior to pre-Phase-25.
    Portfolio tool not in registry, system prompt clean, no pre-seeded observations."""
    from alphaswarm import cli as cli_module
    from alphaswarm import report as report_module

    captured: dict = {}
    original_init = report_module.ReportEngine.__init__

    def capture_init(self, *args, **kwargs):
        captured["tools"] = kwargs.get("tools", {})
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        captured["pre_seeded_observations"] = kwargs.get("pre_seeded_observations")
        original_init(self, *args, **kwargs)

    async def fake_run(self, cycle_id: str):
        return list(self._pre_seeded)

    _patch_app_factory(monkeypatch, _make_fake_app())
    monkeypatch.setattr(report_module.ReportEngine, "__init__", capture_init)
    monkeypatch.setattr(report_module.ReportEngine, "run", fake_run)

    await cli_module._handle_report(
        cycle_id=None,
        output=str(tmp_path / "out.md"),
        fmt="md",
        portfolio_path=None,
    )

    assert "portfolio_impact" not in captured["tools"]
    system_prompt = captured["system_prompt"] or ""
    assert "portfolio_impact" not in system_prompt
    assert "PORTFOLIO REPORTING CONTRACT" not in system_prompt
    assert captured["pre_seeded_observations"] is None


@pytest.mark.asyncio
async def test_handle_report_with_portfolio_pre_seeds_observation_and_registers_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REVIEWS HIGH consensus: deterministic pre-call must inject a ToolObservation
    into pre_seeded_observations AND register the tool AND include the mandate."""
    from alphaswarm import cli as cli_module
    from alphaswarm import report as report_module

    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        '"Positions for account Individual",,,,,,,,,,,,,,,,,\n'
        "\n"
        '"Symbol","Description","Qty (Quantity)","Price","Price Chng %","Price Chng $","Mkt Val (Market Value)","Day Chng %","Day Chng $","Cost Basis","Gain $","Gain %","Ratings","Reinvest Dividends?","Capital Gains?","% Of Account","Security Type","Asset Type"\n'
        '"AAPL","APPLE INC","10","260.00","--","--","$2,600.00","--","--","$2000","$600","30%","--","Yes","Yes","50%","Stock","Equity"\n',
        encoding="utf-8",
    )

    captured: dict = {}
    original_init = report_module.ReportEngine.__init__

    def capture_init(self, *args, **kwargs):
        captured["tools"] = kwargs.get("tools", {})
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        captured["pre_seeded_observations"] = kwargs.get("pre_seeded_observations")
        original_init(self, *args, **kwargs)

    async def fake_run(self, cycle_id: str):
        return list(self._pre_seeded)

    _patch_app_factory(monkeypatch, _make_fake_app())
    monkeypatch.setattr(report_module.ReportEngine, "__init__", capture_init)
    monkeypatch.setattr(report_module.ReportEngine, "run", fake_run)

    await cli_module._handle_report(
        cycle_id=None,
        output=str(tmp_path / "out.md"),
        fmt="md",
        portfolio_path=str(csv_path),
    )

    # Tool registered
    assert "portfolio_impact" in captured["tools"]
    # Prompt contains both line and mandate
    assert "portfolio_impact" in captured["system_prompt"]
    assert "PORTFOLIO REPORTING CONTRACT" in captured["system_prompt"]
    assert "MUST include a paragraph" in captured["system_prompt"]
    # Deterministic pre-seed: exactly one portfolio_impact observation
    pre_seeded = captured["pre_seeded_observations"]
    assert pre_seeded is not None
    assert len(pre_seeded) == 1
    assert pre_seeded[0].tool_name == "portfolio_impact"
    result = pre_seeded[0].result
    assert "matched_tickers" in result
    assert "gap_tickers" in result
    assert "coverage_summary" in result


@pytest.mark.asyncio
async def test_idempotent_tool_closure_returns_same_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered tool closure must return the pre-computed result regardless of input."""
    from alphaswarm import cli as cli_module
    from alphaswarm import report as report_module

    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        '"Positions for account Individual",,,,,,,,,,,,,,,,,\n'
        "\n"
        '"Symbol","Description","Qty (Quantity)","Price","Price Chng %","Price Chng $","Mkt Val (Market Value)","Day Chng %","Day Chng $","Cost Basis","Gain $","Gain %","Ratings","Reinvest Dividends?","Capital Gains?","% Of Account","Security Type","Asset Type"\n'
        '"AAPL","APPLE INC","10","260.00","--","--","$2,600.00","--","--","$2000","$600","30%","--","Yes","Yes","50%","Stock","Equity"\n',
        encoding="utf-8",
    )

    captured: dict = {}
    original_init = report_module.ReportEngine.__init__

    def capture_init(self, *args, **kwargs):
        captured["tools"] = kwargs.get("tools", {})
        captured["pre_seeded_observations"] = kwargs.get("pre_seeded_observations")
        original_init(self, *args, **kwargs)

    async def fake_run(self, cycle_id: str):
        return list(self._pre_seeded)

    _patch_app_factory(monkeypatch, _make_fake_app())
    monkeypatch.setattr(report_module.ReportEngine, "__init__", capture_init)
    monkeypatch.setattr(report_module.ReportEngine, "run", fake_run)

    await cli_module._handle_report(
        cycle_id=None,
        output=str(tmp_path / "out.md"),
        fmt="md",
        portfolio_path=str(csv_path),
    )

    tool_fn = captured["tools"]["portfolio_impact"]
    result_1 = await tool_fn(cycle_id="c1")
    result_2 = await tool_fn(cycle_id="different-cycle")
    result_3 = await tool_fn()  # no kwargs
    pre_seeded_result = captured["pre_seeded_observations"][0].result
    assert result_1 is pre_seeded_result
    assert result_2 is pre_seeded_result
    assert result_3 is pre_seeded_result


@pytest.mark.asyncio
async def test_logging_never_contains_holdings_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REVIEWS MEDIUM (Codex): privacy-safe logging — no ticker symbols or values in logs."""
    import logging

    from alphaswarm import cli as cli_module
    from alphaswarm import report as report_module

    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        '"Positions for account Individual",,,,,,,,,,,,,,,,,\n'
        "\n"
        '"Symbol","Description","Qty (Quantity)","Price","Price Chng %","Price Chng $","Mkt Val (Market Value)","Day Chng %","Day Chng $","Cost Basis","Gain $","Gain %","Ratings","Reinvest Dividends?","Capital Gains?","% Of Account","Security Type","Asset Type"\n'
        '"AAPL","APPLE INC","10","260.00","--","--","$2,600.00","--","--","$2000","$600","30%","--","Yes","Yes","50%","Stock","Equity"\n'
        '"NVDA","NVIDIA CORP","5","500.00","--","--","$2,500.00","--","--","$2000","$500","25%","--","Yes","Yes","50%","Stock","Equity"\n',
        encoding="utf-8",
    )

    async def fake_run(self, cycle_id: str):
        return list(self._pre_seeded)

    _patch_app_factory(monkeypatch, _make_fake_app())
    monkeypatch.setattr(report_module.ReportEngine, "run", fake_run)

    with caplog.at_level(logging.DEBUG):
        await cli_module._handle_report(
            cycle_id=None,
            output=str(tmp_path / "out.md"),
            fmt="md",
            portfolio_path=str(csv_path),
        )

    log_text = caplog.text
    # Privacy assertions: ticker symbols and currency values must never appear in logs.
    assert "AAPL" not in log_text
    assert "NVDA" not in log_text
    assert "APPLE" not in log_text
    assert "NVIDIA" not in log_text
    assert "$2,600" not in log_text
    assert "$2,500" not in log_text


# -----------------------------------------------------------------------------
# HTML rendering (Task 3)
# -----------------------------------------------------------------------------

from alphaswarm.report import ReportAssembler


class TestHtmlPortfolioSection:
    def _matched_observation(self) -> ToolObservation:
        return ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [
                    {
                        "ticker": "AAPL",
                        "shares": 101.3071,
                        "market_value": 26416.56,
                        "market_value_display": "$26,416.56",
                        "signal": "BUY",
                        "confidence": 0.82,
                        "entity_name": "Apple Inc",
                        "avg_sentiment": 0.43,
                        "mention_count": 45,
                    },
                    {
                        "ticker": "NVDA",
                        "shares": 50.0,
                        "market_value": 5000.0,
                        "market_value_display": "$5,000.00",
                        "signal": "SELL",
                        "confidence": 0.61,
                        "entity_name": "NVIDIA Corp",
                        "avg_sentiment": -0.22,
                        "mention_count": 33,
                    },
                ],
                "gap_tickers": [
                    {
                        "ticker": "COHR",
                        "shares": 25.0,
                        "market_value": 1800.0,
                        "market_value_display": "$1,800.00",
                        "reason": "no_simulation_coverage",
                        "asset_type": "Equity",
                    },
                    {
                        "ticker": "VOO",
                        "shares": 10.0,
                        "market_value": 5000.0,
                        "market_value_display": "$5,000.00",
                        "reason": "non_equity",
                        "asset_type": "ETFs & Closed End Funds",
                    },
                ],
                "coverage_summary": {
                    "covered": 2,
                    "total_equity_holdings": 3,
                    "coverage_pct": 66.7,
                },
            },
        )

    def test_html_contains_matched_heading(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert "Portfolio Impact - Matched Positions" in html

    def test_html_contains_coverage_gaps_heading(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert "Portfolio Impact - Coverage Gaps" in html

    def test_html_renders_matched_ticker_rows(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert "AAPL" in html
        assert "Apple Inc" in html
        assert "$26,416.56" in html
        assert "NVDA" in html
        assert "NVIDIA Corp" in html

    def test_html_uses_signal_class_for_buy(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert 'class="signal-buy"' in html

    def test_html_uses_signal_class_for_sell(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert 'class="signal-sell"' in html

    def test_html_renders_no_simulation_coverage_gap(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert "COHR" in html
        assert "$1,800.00" in html
        assert "No simulation coverage" in html

    def test_html_renders_non_equity_gap_with_asset_type(self) -> None:
        """REVIEWS HIGH (Codex): non-equity holdings must appear as gaps with reason label."""
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert "VOO" in html
        assert (
            "Non-equity (ETFs &amp; Closed End Funds)" in html
            or "Non-equity (ETFs & Closed End Funds)" in html
        )

    def test_html_renders_coverage_summary_text(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert (
            "Coverage: 2/3 equity holdings matched to swarm consensus (66.7%)"
            in html
        )

    def test_html_renders_integer_agreement_percent(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        assert "82%" in html
        assert "61%" in html

    def test_html_omits_portfolio_section_when_observation_absent(self) -> None:
        asm = ReportAssembler()
        html = asm.assemble_html([], cycle_id="c1")
        assert "Portfolio Impact" not in html

    def test_html_all_covered_shows_empty_gaps_copy(self) -> None:
        asm = ReportAssembler()
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={},
            result={
                "matched_tickers": [
                    {
                        "ticker": "AAPL",
                        "shares": 1.0,
                        "market_value": 260.0,
                        "market_value_display": "$260.00",
                        "signal": "BUY",
                        "confidence": 0.9,
                        "entity_name": "Apple",
                        "avg_sentiment": 0.5,
                        "mention_count": 10,
                    }
                ],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 1,
                    "total_equity_holdings": 1,
                    "coverage_pct": 100.0,
                },
            },
        )
        html = asm.assemble_html([obs], cycle_id="c1")
        assert "All equity holdings have swarm coverage in this simulation." in html

    def test_html_no_matches_shows_empty_matched_copy(self) -> None:
        asm = ReportAssembler()
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={},
            result={
                "matched_tickers": [],
                "gap_tickers": [
                    {
                        "ticker": "COHR",
                        "shares": 5.0,
                        "market_value": 500.0,
                        "market_value_display": "$500.00",
                        "reason": "no_simulation_coverage",
                        "asset_type": "Equity",
                    }
                ],
                "coverage_summary": {
                    "covered": 0,
                    "total_equity_holdings": 1,
                    "coverage_pct": 0.0,
                },
            },
        )
        html = asm.assemble_html([obs], cycle_id="c1")
        assert "No held tickers match entities the swarm analyzed this cycle." in html

    def test_html_escapes_entity_name_with_html_chars(self) -> None:
        """REVIEWS LOW (Codex): user-controlled fields must go through Jinja autoescape."""
        asm = ReportAssembler()
        obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={},
            result={
                "matched_tickers": [
                    {
                        "ticker": "XYZ",
                        "shares": 1.0,
                        "market_value": 100.0,
                        "market_value_display": "$100.00",
                        "signal": "BUY",
                        "confidence": 0.5,
                        "entity_name": "<script>alert(1)</script>",
                        "avg_sentiment": 0.1,
                        "mention_count": 1,
                    }
                ],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 1,
                    "total_equity_holdings": 1,
                    "coverage_pct": 100.0,
                },
            },
        )
        html = asm.assemble_html([obs], cycle_id="c1")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_no_new_css_classes_introduced(self) -> None:
        """Phase 25 must not add new CSS classes. Verify by checking template source."""
        template_path = Path("src/alphaswarm/templates/report/report.html.j2")
        src = template_path.read_text(encoding="utf-8")
        assert ".portfolio-" not in src
        assert ".matched-" not in src
        assert ".gap-" not in src

    def test_html_report_still_self_contained(self) -> None:
        """Phase 24 constraint: HTML report must work offline."""
        asm = ReportAssembler()
        html = asm.assemble_html([self._matched_observation()], cycle_id="c1")
        if "Portfolio Impact" in html:
            portfolio_section = html.split("Portfolio Impact")[1]
            assert "https://" not in portfolio_section
            assert "http://" not in portfolio_section


class TestDeterministicEndToEnd:
    """REVIEWS HIGH consensus: the complete pipeline must render the Portfolio
    Impact section in markdown AND HTML even if the ReACT loop never calls the tool."""

    @pytest.mark.asyncio
    async def test_lazy_llm_still_produces_portfolio_markdown_section(self) -> None:
        """Simulates a 'lazy' LLM that ignores portfolio_impact. The pre-seeded
        observation must still flow through ReportAssembler.assemble()."""
        portfolio_obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [
                    {
                        "ticker": "AAPL",
                        "shares": 10.0,
                        "market_value": 2600.0,
                        "market_value_display": "$2,600.00",
                        "signal": "BUY",
                        "confidence": 0.8,
                        "entity_name": "Apple Inc",
                        "avg_sentiment": 0.4,
                        "mention_count": 20,
                    }
                ],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 1,
                    "total_equity_holdings": 1,
                    "coverage_pct": 100.0,
                },
            },
        )
        # Render via ReportAssembler directly (ReACT loop not needed — we simulate
        # the end state after ReportEngine.run() returns pre_seeded observations).
        asm = ReportAssembler()
        md = asm.assemble([portfolio_obs], cycle_id="c1")
        assert "Portfolio Impact" in md
        assert "AAPL" in md

    @pytest.mark.asyncio
    async def test_lazy_llm_still_produces_portfolio_html_section(self) -> None:
        portfolio_obs = ToolObservation(
            tool_name="portfolio_impact",
            tool_input={"cycle_id": "c1"},
            result={
                "matched_tickers": [
                    {
                        "ticker": "AAPL",
                        "shares": 10.0,
                        "market_value": 2600.0,
                        "market_value_display": "$2,600.00",
                        "signal": "BUY",
                        "confidence": 0.8,
                        "entity_name": "Apple Inc",
                        "avg_sentiment": 0.4,
                        "mention_count": 20,
                    }
                ],
                "gap_tickers": [],
                "coverage_summary": {
                    "covered": 1,
                    "total_equity_holdings": 1,
                    "coverage_pct": 100.0,
                },
            },
        )
        asm = ReportAssembler()
        html = asm.assemble_html([portfolio_obs], cycle_id="c1")
        assert "Portfolio Impact - Matched Positions" in html
        assert "AAPL" in html
