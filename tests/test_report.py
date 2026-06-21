"""Unit tests for ReportEngine, parser, and graph query tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.report import MAX_ITERATIONS, _parse_action_input
from tests.inference.fakes import FakeInferenceProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(content: str | list[str]) -> FakeInferenceProvider:
    """Create a FakeInferenceProvider scripted with one or more responses."""
    if isinstance(content, str):
        scripted = [InferenceResult(content=content, model="test")]
    else:
        scripted = [InferenceResult(content=c, model="test") for c in content]
    return FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR, model="test", scripted=scripted,
    )


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

        mock_tool = AsyncMock(
            return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
        )
        provider = _make_provider("THOUGHT: Done\nACTION: FINAL_ANSWER\nINPUT: {}")

        engine = ReportEngine(
            provider=provider,
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        # FINAL_ANSWER produces no observation
        assert result == []
        # Provider called once
        assert len(provider.calls) == 1

    async def test_hard_cap_termination(self) -> None:
        """Engine exits at MAX_ITERATIONS when no FINAL_ANSWER."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(
            return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
        )

        # Return incrementing inputs to avoid duplicate detection
        scripted = [
            InferenceResult(
                content=f'ACTION: bracket_summary\nINPUT: {{"cycle_id": "abc", "n": {i}}}',
                model="test",
            )
            for i in range(MAX_ITERATIONS + 5)
        ]
        provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR, model="test", scripted=scripted,
        )

        engine = ReportEngine(
            provider=provider,
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        assert len(result) == MAX_ITERATIONS
        assert len(provider.calls) == MAX_ITERATIONS

    async def test_duplicate_call_terminates(self) -> None:
        """Engine exits on duplicate (tool, input) pair after 1 successful call."""
        from alphaswarm.report import ReportEngine

        mock_tool = AsyncMock(
            return_value={"buy_count": 50, "sell_count": 30, "hold_count": 20, "total": 100},
        )

        # Scripted with the same response twice to trigger duplicate detection
        scripted = [
            InferenceResult(
                content='ACTION: bracket_summary\nINPUT: {"cycle_id": "abc"}', model="test",
            ),
            InferenceResult(
                content='ACTION: bracket_summary\nINPUT: {"cycle_id": "abc"}', model="test",
            ),
        ]
        provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR, model="test", scripted=scripted,
        )

        engine = ReportEngine(
            provider=provider,
            tools={"bracket_summary": mock_tool},
        )
        result = await engine.run("cycle1")

        # First call succeeds, second is duplicate -> exit
        assert len(result) == 1
        # First call dispatched, second detected as duplicate
        assert len(provider.calls) == 2


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
        result = assembler.render_section(
            "01_consensus_summary.j2", data=data, cycle_id="test-cycle",
        )

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


class TestMarkdownAssembler:
    """assemble() produces a valid markdown report with the expected sections.

    The HTML report path was removed (v4.0 → v6.0 migration): reports are now
    markdown that the frontend renders via marked.js. These tests target the
    surviving `ReportAssembler.assemble()` method (SWEEP-260528 B-1).
    """

    def test_produces_markdown_document(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_CONSENSUS_OBS], "test-cycle")
        # Header is always emitted, even with no observations
        assert md.startswith("# Post-Simulation Analysis Report")
        # Section heading from 01_consensus_summary.j2
        assert "## Consensus Summary" in md

    def test_contains_cycle_id(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_CONSENSUS_OBS], "abc-123")
        assert "abc-123" in md

    def test_contains_page_title(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([], "test-cycle")
        assert "# Post-Simulation Analysis Report" in md

    def test_contains_consensus_counts(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_CONSENSUS_OBS], "test-cycle")
        # Buy/sell/hold counts from _CONSENSUS_OBS render into the table
        assert "50" in md  # buy_count
        assert "30" in md  # sell_count
        assert "20" in md  # hold_count

    def test_contains_timeline_table(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_TIMELINE_OBS], "test-cycle")
        assert "## Round Timeline" in md
        # 3 rounds × BUY/SELL/HOLD header columns
        assert "| Round |" in md
        assert "BUY" in md

    def test_contains_bracket_table(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_BRACKET_OBS], "test-cycle")
        assert "## Bracket Narratives" in md
        assert "Quants" in md

    def test_contains_dissenters_table(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([_DISSENTERS_OBS], "test-cycle")
        assert "## Key Dissenters" in md
        # Dissenter row data
        assert "a1" in md

    def test_empty_observations_produces_header_only(self) -> None:
        assembler = ReportAssembler()
        md = assembler.assemble([], "test-cycle")
        # Header still present, but no section headings since no observations
        assert md.startswith("# Post-Simulation Analysis Report")
        assert "## Consensus Summary" not in md
        assert "## Round Timeline" not in md


class TestMarkdownStructure:
    """Markdown report sections are well-formed and appear in canonical order."""

    def test_all_sections_render_in_canonical_order(self) -> None:
        """When all four observations present, sections appear in SECTION_ORDER."""
        assembler = ReportAssembler()
        md = assembler.assemble(
            [_DISSENTERS_OBS, _BRACKET_OBS, _TIMELINE_OBS, _CONSENSUS_OBS],
            "test-cycle",
        )
        # SECTION_ORDER is consensus → timeline → bracket_narratives → dissenters
        consensus_pos = md.index("## Consensus Summary")
        timeline_pos = md.index("## Round Timeline")
        bracket_pos = md.index("## Bracket Narratives")
        dissenters_pos = md.index("## Key Dissenters")
        assert consensus_pos < timeline_pos < bracket_pos < dissenters_pos

    def test_no_html_tags_in_output(self) -> None:
        """Markdown output must NOT contain HTML markup — the frontend renders
        via marked.js with HTML escaping enabled; raw HTML in the source would
        either render as plain text or be sanitized away."""
        assembler = ReportAssembler()
        md = assembler.assemble(
            [_CONSENSUS_OBS, _TIMELINE_OBS, _BRACKET_OBS, _DISSENTERS_OBS],
            "test-cycle",
        )
        # Common HTML structural tags must not appear in markdown source
        assert "<!DOCTYPE" not in md
        assert "<html" not in md
        assert "<body" not in md
        assert "<svg" not in md
        assert "<script" not in md


class TestMarkdownFileSize:
    """Generated markdown stays small enough to round-trip through file I/O
    and the frontend renderer without pagination."""

    def test_full_report_under_100kb(self) -> None:
        all_obs = [_CONSENSUS_OBS, _TIMELINE_OBS, _BRACKET_OBS, _DISSENTERS_OBS]
        assembler = ReportAssembler()
        md = assembler.assemble(all_obs, "test-cycle")
        size_bytes = len(md.encode("utf-8"))
        # Markdown reports are ~1-10 KB in practice; 100 KB is the soft cap
        # below which the frontend renderer is verified not to choke.
        assert size_bytes < 100_000, f"Markdown size {size_bytes} exceeds 100KB"


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
