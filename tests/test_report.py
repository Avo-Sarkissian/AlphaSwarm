"""Unit tests for ReportEngine, parser, and graph query tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.report import MAX_ITERATIONS, _parse_action_input


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_ollama_response(content: str) -> MagicMock:
    """Create a mock OllamaClient response with the given message content."""
    mock_resp = MagicMock()
    mock_resp.message.content = content
    return mock_resp


# ---------------------------------------------------------------------------
# Task 15-01-01: TestParseActionInput
# ---------------------------------------------------------------------------


class TestParseActionInput:
    def test_basic_extraction(self) -> None:
        """Standard ACTION/INPUT block returns correct tuple."""
        content = (
            "THOUGHT: I need consensus data.\n"
            'ACTION: consensus_summary\n'
            'INPUT: {"cycle_id": "abc123"}'
        )
        action, input_json = _parse_action_input(content)
        assert action == "consensus_summary"
        assert input_json == '{"cycle_id": "abc123"}'

    def test_no_action_returns_none(self) -> None:
        """Prose with no ACTION: returns (None, None)."""
        content = "I think the market is bullish based on strong fundamentals."
        action, input_json = _parse_action_input(content)
        assert action is None
        assert input_json is None

    def test_action_without_input_defaults_empty_json(self) -> None:
        """ACTION present, no INPUT line returns (action, '{}')."""
        content = "THOUGHT: Done.\nACTION: FINAL_ANSWER"
        action, input_json = _parse_action_input(content)
        assert action == "FINAL_ANSWER"
        assert input_json == "{}"

    def test_thought_before_action_parsed_correctly(self) -> None:
        """THOUGHT text before ACTION block still extracts correctly."""
        content = (
            "THOUGHT: I need to look at bracket breakdowns.\n"
            "Some additional reasoning here.\n"
            'ACTION: bracket_narratives\n'
            'INPUT: {"cycle_id": "xyz"}'
        )
        action, input_json = _parse_action_input(content)
        assert action == "bracket_narratives"
        assert input_json == '{"cycle_id": "xyz"}'


# ---------------------------------------------------------------------------
# Task 15-01-02: TestReportEngine (stubs filled in Task 15-01-02)
# ---------------------------------------------------------------------------


class TestReportEngine:
    async def test_terminates_on_final_answer(self) -> None:
        """Engine terminates immediately when LLM outputs FINAL_ANSWER."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100})
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(return_value=_mock_ollama_response(
            "THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}"
        ))

        engine = ReportEngine(
            ollama_client=mock_client,
            model="test",
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        # FINAL_ANSWER produces no observation
        assert result == []
        # Chat called once
        assert mock_client.chat.call_count == 1

    async def test_hard_cap_termination(self) -> None:
        """Engine exits at MAX_ITERATIONS when no FINAL_ANSWER."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100})
        mock_client = AsyncMock()

        # Return incrementing inputs to avoid duplicate detection
        def make_response(i: int) -> MagicMock:
            return _mock_ollama_response(
                f'ACTION: bracket_summary\nINPUT: {{"cycle_id": "abc", "n": {i}}}'
            )

        mock_client.chat = AsyncMock(side_effect=[make_response(i) for i in range(MAX_ITERATIONS + 5)])

        engine = ReportEngine(
            ollama_client=mock_client,
            model="test",
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        assert len(result) == MAX_ITERATIONS
        assert mock_client.chat.call_count == MAX_ITERATIONS

    async def test_duplicate_call_terminates(self) -> None:
        """Engine exits on duplicate (tool, input) pair after 1 successful call."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100})
        mock_client = AsyncMock()
        # Always return the same response -> duplicate on second call
        mock_client.chat = AsyncMock(return_value=_mock_ollama_response(
            'ACTION: bracket_summary\nINPUT: {"cycle_id": "abc"}'
        ))

        engine = ReportEngine(
            ollama_client=mock_client,
            model="test",
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        # First call succeeds, second is duplicate -> exit
        assert len(result) == 1
        # First call dispatched, second detected as duplicate
        assert mock_client.chat.call_count == 2


# ---------------------------------------------------------------------------
# Task 15-01-03: TestGraphQueryTools (stubs filled in Task 15-01-03)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_driver() -> MagicMock:
    """Mock AsyncDriver with session context manager support."""
    driver = MagicMock()
    driver.close = AsyncMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = session
    return driver


@pytest.fixture()
def mock_personas() -> list:
    """Empty personas list — report queries don't use personas."""
    return []


class TestGraphQueryTools:
    async def test_read_consensus_summary(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        """read_consensus_summary returns dict with correct keys and values."""
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value={
            "buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100,
        })

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_consensus_summary("cycle1")

        assert result["buy_count"] == 50
        assert result["sell_count"] == 30
        assert result["hold_count"] == 20
        assert result["total"] == 100

    async def test_influence_leaders_round_filter(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        """read_influence_leaders returns list with correct field structure."""
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[{
            "agent_id": "a1",
            "name": "Agent 1",
            "bracket": "Quants",
            "total_influence_weight": 0.9,
            "citation_count": 5,
        }])

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_influence_leaders("cycle1")

        assert len(result) == 1
        assert result[0]["agent_id"] == "a1"
        assert result[0]["name"] == "Agent 1"
        assert result[0]["bracket"] == "Quants"
        assert result[0]["total_influence_weight"] == 0.9
        assert result[0]["citation_count"] == 5

    async def test_signal_flip_none_filter(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        """read_signal_flips returns list; NONE flip_types excluded by Cypher."""
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[{
            "agent_id": "a1",
            "name": "Agent 1",
            "bracket": "Quants",
            "round_num": 2,
            "flip_type": "HOLD_TO_BUY",
            "final_signal": "BUY",
        }])

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_signal_flips("cycle1")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["flip_type"] == "HOLD_TO_BUY"


# ---------------------------------------------------------------------------
# Task Plan 02: TestReportAssembler (stubs — filled in Plan 02)
# ---------------------------------------------------------------------------


class TestReportAssembler:
    def test_renders_section(self) -> None:
        """ReportAssembler.render_section returns markdown with section heading and data values."""
        from alphaswarm.report import ReportAssembler

        assembler = ReportAssembler()
        data = {"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100}
        result = assembler.render_section("01_consensus_summary.j2", data=data, cycle_id="test-cycle")

        assert "Consensus Summary" in result
        assert "50" in result
        assert "30" in result

    async def test_async_file_write(self, tmp_path: pytest.TempdirFactory) -> None:
        """write_report creates file with correct content using aiofiles."""
        from alphaswarm.report import write_report

        report_path = tmp_path / "test_report.md"  # type: ignore[operator]
        await write_report(report_path, "# Report Content")

        assert report_path.exists()
        assert report_path.read_text() == "# Report Content"

    async def test_sentinel_file_schema(self, tmp_path: pytest.TempdirFactory) -> None:
        """write_sentinel creates JSON with cycle_id, path, and generated_at ISO timestamp."""
        import json
        from datetime import datetime
        from alphaswarm.report import write_sentinel

        await write_sentinel("cycle1", "./reports/cycle1_report.md", sentinel_dir=tmp_path)  # type: ignore[arg-type]

        sentinel_file = tmp_path / "last_report.json"  # type: ignore[operator]
        assert sentinel_file.exists()

        data = json.loads(sentinel_file.read_text())
        assert set(data.keys()) == {"cycle_id", "path", "generated_at"}
        assert data["cycle_id"] == "cycle1"
        assert data["path"] == "./reports/cycle1_report.md"
        # Validate ISO timestamp
        datetime.fromisoformat(data["generated_at"])


# ---------------------------------------------------------------------------
# Phase 24: HTML Report Tests
# ---------------------------------------------------------------------------

# Shared test data for HTML tests

_CONSENSUS_OBS = None  # defined below after import guard
_TIMELINE_OBS = None
_BRACKET_OBS = None
_DISSENTERS_OBS = None
_FULL_MARKET_ROW: dict = {
    "ticker": "AAPL",
    "company_name": "Apple Inc.",
    "last_close": 189.50,
    "majority_signal": "BUY",
    "majority_pct": 0.65,
    "consensus_score": 0.72,
    "pe_ratio": 28.5,
}

from alphaswarm.report import ReportAssembler, ToolObservation  # noqa: E402

_CONSENSUS_OBS = ToolObservation(
    tool_name="bracket_summary",
    tool_input={"cycle_id": "test-html"},
    result={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
)
_TIMELINE_OBS = ToolObservation(
    tool_name="round_timeline",
    tool_input={"cycle_id": "test-html"},
    result=[
        {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 20, "total": 100},
        {"round_num": 2, "buy_count": 48, "sell_count": 32, "hold_count": 20, "total": 100},
        {"round_num": 3, "buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
    ],
)
_BRACKET_OBS = ToolObservation(
    tool_name="bracket_narratives",
    tool_input={"cycle_id": "test-html"},
    result=[
        {"bracket": "Quants", "buy_count": 8, "sell_count": 1, "hold_count": 1,
         "avg_confidence": 0.85, "avg_sentiment": 0.72},
    ],
)
_DISSENTERS_OBS = ToolObservation(
    tool_name="key_dissenters",
    tool_input={"cycle_id": "test-html"},
    result=[
        {"agent_id": "a1", "bracket": "Quants", "signal": "SELL", "bracket_majority": "BUY"},
    ],
)


class TestHtmlAssembler:
    """EXPORT-01: assemble_html() produces valid HTML with all sections."""

    def test_produces_html_document(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "test-cycle")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_contains_cycle_id(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "abc-123")
        assert "abc-123" in html

    def test_contains_page_title(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "AlphaSwarm Post-Simulation Report" in html

    def test_contains_consensus_svg(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "test-cycle")
        assert "<svg" in html

    def test_contains_timeline_svg(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_TIMELINE_OBS], "test-cycle")
        assert "<svg" in html

    def test_contains_bracket_table(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_BRACKET_OBS], "test-cycle")
        assert "Quants" in html
        assert "Bracket Analysis" in html

    def test_contains_dissenters_table(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_DISSENTERS_OBS], "test-cycle")
        assert "Key Dissenters" in html

    def test_existing_markdown_assemble_still_works(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_CONSENSUS_OBS], "test-cycle")
        assert "## Consensus Summary" in md
        assert "50" in md

    def test_empty_observations_produces_valid_html(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "<!DOCTYPE html>" in html
        assert "Insufficient data to render chart." in html


class TestHtmlSelfContained:
    """EXPORT-01: HTML contains no external resource references."""

    def test_no_external_http_refs(self) -> None:
        """No external resource-loading URLs (CDN fonts, stylesheets, scripts).

        SVG inline markup legitimately contains http://www.w3.org/2000/svg as
        an XML namespace declaration and pygal comment URLs — neither causes a
        network request.  We check for actual resource-loading patterns instead.
        """
        assembler = ReportAssembler()
        html = assembler.assemble_html(
            [_CONSENSUS_OBS, _TIMELINE_OBS, _BRACKET_OBS],
            "test-cycle",
            market_context_data=[_FULL_MARKET_ROW],
        )
        # No external stylesheet, font, or script URLs that would break offline
        assert 'href="http' not in html
        assert 'href="https' not in html
        assert 'src="http' not in html
        assert 'src="https' not in html
        assert 'url(http' not in html
        assert 'url(https' not in html

    def test_no_external_link_tags(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "test-cycle")
        assert '<link ' not in html.lower()

    def test_no_external_script_src(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "test-cycle")
        assert '<script src=' not in html.lower()
        assert 'kozea.github.io' not in html


class TestHtmlFileSize:
    """EXPORT-01: Generated HTML under 1MB."""

    def test_full_report_under_1mb(self) -> None:
        all_obs = [_CONSENSUS_OBS, _TIMELINE_OBS, _BRACKET_OBS, _DISSENTERS_OBS]
        assembler = ReportAssembler()
        html = assembler.assemble_html(
            all_obs, "test-cycle",
            market_context_data=[_FULL_MARKET_ROW],
        )
        size_bytes = len(html.encode("utf-8"))
        assert size_bytes < 1_000_000, f"HTML size {size_bytes} exceeds 1MB limit"


class TestHtmlDarkTheme:
    """EXPORT-03: HTML uses dark theme matching TUI aesthetic."""

    def test_body_dark_background(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "background: #121212" in html

    def test_accent_color_in_headings(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "color: #4FC3F7" in html

    def test_foreground_text_color(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "color: #E0E0E0" in html

    def test_signal_buy_color(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "color: #66BB6A" in html

    def test_signal_sell_color(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([], "test-cycle")
        assert "color: #EF5350" in html


class TestChartStyleInSvg:
    """EXPORT-03: SVG charts embed dark theme colors."""

    def test_consensus_svg_dark_background(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "test-cycle")
        assert "#121212" in html
        assert "#1E1E1E" in html

    def test_no_xml_declaration_in_output(self) -> None:
        assembler = ReportAssembler()
        html = assembler.assemble_html([_CONSENSUS_OBS], "test-cycle")
        assert "<?xml" not in html


# ---------------------------------------------------------------------------
# Phase 27: Shock impact report section (Plan 02)
# ---------------------------------------------------------------------------


def test_tool_to_template_contains_shock_impact() -> None:
    """Phase 27 SHOCK-05 — TOOL_TO_TEMPLATE['shock_impact'] == '11_shock_impact.j2'."""
    from alphaswarm.report import TOOL_TO_TEMPLATE

    assert TOOL_TO_TEMPLATE.get("shock_impact") == "11_shock_impact.j2"


def test_section_order_contains_shock_impact_after_portfolio() -> None:
    """Phase 27 SHOCK-05 — SECTION_ORDER ends with 'shock_impact' after 'portfolio_impact'."""
    from alphaswarm.report import SECTION_ORDER

    assert "shock_impact" in SECTION_ORDER
    assert "portfolio_impact" in SECTION_ORDER
    assert SECTION_ORDER.index("shock_impact") > SECTION_ORDER.index("portfolio_impact")


def test_assemble_includes_shock_section_when_observation_present() -> None:
    """Phase 27 SHOCK-05 — assemble() includes Shock Impact Analysis when observation present."""
    from alphaswarm.report import ReportAssembler, ToolObservation

    shock_obs = ToolObservation(
        tool_name="shock_impact",
        tool_input={"cycle_id": "test-cycle"},
        result={
            "shock_text": "Fed raises rates by 75bps",
            "injected_before_round": 2,
            "comparable_agents": 95,
            "pivot_count": 40,
            "held_firm_count": 55,
            "pivot_rate_pct": 42.1,
            "held_firm_rate_pct": 57.9,
            "pivot_agents": [],
            "bracket_deltas": [],
            "largest_shift": {"bracket": "Quants", "direction": "BUY", "delta": 20.0},
            "notable_held_firm_agents": [],
        },
    )
    assembler = ReportAssembler()
    result = assembler.assemble([shock_obs], "test-cycle")

    assert "Shock Impact Analysis" in result
    assert "Fed raises rates by 75bps" in result


def test_assemble_skips_shock_section_when_no_observation() -> None:
    """Phase 27 SHOCK-05 — assemble() does not include shock section when observation absent."""
    from alphaswarm.report import ReportAssembler

    assembler = ReportAssembler()
    result = assembler.assemble([], "test-cycle")

    assert "Shock Impact Analysis" not in result


# Shared fixture data for template rendering tests
_SHOCK_IMPACT_DATA: dict = {
    "shock_text": "Surprise CPI print: 9.1% YoY",
    "injected_before_round": 2,
    "comparable_agents": 88,
    "pivot_count": 33,
    "held_firm_count": 55,
    "pivot_rate_pct": 37.5,
    "held_firm_rate_pct": 62.5,
    "bracket_deltas": [
        {
            "bracket": "Quants",
            "pre_dominant": "BUY",
            "dominant_post": "SELL",
            "dominant_arrow": "▼",
            "delta_buy_pct": -30.0,
        },
        {
            "bracket": "Degens",
            "pre_dominant": "HOLD",
            "dominant_post": "BUY",
            "dominant_arrow": "▲",
            "delta_buy_pct": 15.0,
        },
    ],
    "pivot_agents": [
        {"bracket": "Quants", "agent_id": "a01", "pre_signal": "BUY", "post_signal": "SELL"},
        {"bracket": "Quants", "agent_id": "a02", "pre_signal": "BUY", "post_signal": "SELL"},
    ],
    "largest_shift": {"bracket": "Quants", "direction": "SELL", "delta": -30.0},
    "notable_held_firm_agents": [],
}


def test_shock_impact_template_renders_bracket_delta_table() -> None:
    """Phase 27 SHOCK-05 — 11_shock_impact.j2 renders Bracket Signal Shift heading + table."""
    from alphaswarm.report import ReportAssembler

    assembler = ReportAssembler()
    result = assembler.render_section(
        "11_shock_impact.j2", data=_SHOCK_IMPACT_DATA, cycle_id="test-cycle"
    )

    assert "Bracket Signal Shift" in result
    assert "Quants" in result
    assert "Degens" in result


def test_shock_impact_template_renders_pivot_list() -> None:
    """Phase 27 SHOCK-05 — 11_shock_impact.j2 renders Agent Pivot List heading when pivots exist."""
    from alphaswarm.report import ReportAssembler

    assembler = ReportAssembler()
    result = assembler.render_section(
        "11_shock_impact.j2", data=_SHOCK_IMPACT_DATA, cycle_id="test-cycle"
    )

    assert "Agent Pivot List" in result
    assert "a01" in result
    assert "a02" in result
