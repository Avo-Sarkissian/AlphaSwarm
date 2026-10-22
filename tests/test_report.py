"""Unit tests for ReportEngine, parser, and graph query tools."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.report import MAX_ITERATIONS, REACT_SYSTEM_PROMPT, _parse_action_input
from tests.inference.fakes import FakeInferenceProvider

# Canonical report tool registry keys (cli.py:_handle_report and
# web/routes/report.py build the same set).
_REPORT_TOOL_REGISTRY_KEYS = {
    "bracket_summary",
    "round_timeline",
    "bracket_narratives",
    "key_dissenters",
    "influence_leaders",
    "signal_flip_analysis",
    "entity_impact",
    "social_post_reach",
}


def test_react_prompt_tool_names_match_registry() -> None:
    """F-06: every tool the ReAct prompt advertises must exist in the dispatch
    registry, else the model emits ACTION names that always hit 'Unknown tool'
    and the corresponding report sections silently never run."""
    import re

    advertised = set(re.findall(r"^- (\w+):", REACT_SYSTEM_PROMPT, flags=re.MULTILINE))
    advertised.discard("FINAL_ANSWER")
    assert advertised == _REPORT_TOOL_REGISTRY_KEYS

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
            'ACTION: bracket_summary\n'
            'INPUT: {"cycle_id": "abc123"}'
        )
        action, input_json = _parse_action_input(content)
        assert action == "bracket_summary"
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
# Task Plan 02: TestReportAssembler (stubs — filled in Plan 02)
# ---------------------------------------------------------------------------


class TestReportAssembler:
    def test_renders_section(self) -> None:
        """ReportAssembler.render_section returns markdown with section heading and data values."""
        from alphaswarm.report import ReportAssembler

        assembler = ReportAssembler()
        data = {
            "buy_count": 50, "sell_count": 30, "hold_count": 17,
            "parse_error_count": 3, "total": 100,
        }
        result = assembler.render_section(
            "01_consensus_summary.j2", data=data, cycle_id="test-cycle",
        )

        assert "Consensus Summary" in result
        assert "50" in result
        assert "30" in result

    async def test_async_file_write(self, tmp_path: pytest.TempdirFactory) -> None:
        """write_report creates the file with the exact content, written off the event loop."""
        from alphaswarm.report import write_report

        report_path = tmp_path / "test_report.md"  # type: ignore[operator]
        await write_report(report_path, "# Report Content")

        assert report_path.exists()
        assert report_path.read_text() == "# Report Content"


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
    result={"buy_count": 50, "sell_count": 30, "hold_count": 17,
            "parse_error_count": 3, "total": 100},
)
_TIMELINE_OBS = ToolObservation(
    tool_name="round_timeline",
    tool_input={"cycle_id": "test-html"},
    result=[
        {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 18,
         "parse_error_count": 2, "total": 100},
        {"round_num": 2, "buy_count": 48, "sell_count": 32, "hold_count": 17,
         "parse_error_count": 3, "total": 100},
        {"round_num": 3, "buy_count": 50, "sell_count": 30, "hold_count": 17,
         "parse_error_count": 3, "total": 100},
    ],
)
_BRACKET_OBS = ToolObservation(
    tool_name="bracket_narratives",
    tool_input={"cycle_id": "test-html"},
    result=[
        {"bracket": "quants", "display_name": "Quants", "buy_count": 8, "sell_count": 1,
         "hold_count": 1, "total": 10, "avg_confidence": 0.85, "avg_sentiment": 0.72,
         "majority": "BUY"},
        {"bracket": "degens", "display_name": "Degens", "buy_count": 0, "sell_count": 0,
         "hold_count": 0, "total": 0, "avg_confidence": 0.0, "avg_sentiment": 0.0,
         "majority": None},
    ],
)
_DISSENTERS_OBS = ToolObservation(
    tool_name="key_dissenters",
    tool_input={"cycle_id": "test-html"},
    result=[
        {"agent_id": "a1", "name": "Quants 1", "bracket": "quants", "signal": "SELL",
         "bracket_majority": "BUY"},
    ],
)


class TestMarkdownAssembler:
    """assemble() produces a valid markdown report with the expected sections.

    The HTML report path was removed (v4.0 → v6.0 migration): reports are now
    markdown that the frontend renders via marked.js. These tests target the
    surviving `ReportAssembler.assemble()` method (docs/DECISIONS.md#sweep-b-1).
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
        assert "17" in md  # hold_count

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


def test_section_order_ends_with_shock_impact() -> None:
    """Phase 27 SHOCK-05 — 'shock_impact' is the last section; every section has a template."""
    from alphaswarm.report import SECTION_ORDER, TEMPLATE_DIR, TOOL_TO_TEMPLATE

    assert SECTION_ORDER[-1] == "shock_impact"
    assert "portfolio_impact" not in SECTION_ORDER
    for tool_name in SECTION_ORDER:
        assert (TEMPLATE_DIR / TOOL_TO_TEMPLATE[tool_name]).is_file(), tool_name


def test_assemble_includes_shock_section_when_observation_present() -> None:
    """Phase 27 SHOCK-05 — assemble() includes Shock Impact Analysis when observation present."""
    from alphaswarm.report import ReportAssembler, ToolObservation

    shock_obs = ToolObservation(
        tool_name="shock_impact",
        tool_input={"cycle_id": "test-cycle"},
        result=_SHOCK_IMPACT_DATA | {"shock_text": "Fed raises rates by 75bps"},
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
    "pre_dominant": "BUY",
    "post_dominant": "SELL",
    "pivot_count": 2,
    "pivot_rate": 0.5,
    "bracket_pivots": [
        {
            "bracket": "quants",
            "display_name": "Quants",
            "comparable": 2,
            "pivots": 2,
            "pre_dominant": "BUY",
            "post_dominant": "SELL",
            "pre_buy_pct": 100.0,
            "post_buy_pct": 0.0,
            "delta_buy_pct": -100.0,
            "dominant_arrow": "▼",
            "agents": [
                {"agent_id": "a01", "pre_signal": "BUY", "post_signal": "SELL"},
                {"agent_id": "a02", "pre_signal": "BUY", "post_signal": "SELL"},
            ],
        },
        {
            "bracket": "degens",
            "display_name": "Degens",
            "comparable": 2,
            "pivots": 0,
            "pre_dominant": "HOLD",
            "post_dominant": "BUY",
            "pre_buy_pct": 0.0,
            "post_buy_pct": 50.0,
            "delta_buy_pct": 50.0,
            "dominant_arrow": "▲",
            "agents": [],
        },
    ],
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


def test_shock_template_shows_pre_dominant_per_bracket() -> None:
    md = ReportAssembler().render_section(
        "11_shock_impact.j2", data=_SHOCK_IMPACT_DATA, cycle_id="c",
    )
    assert "| Degens | HOLD | BUY | ▲ | 50.0% |" in md
    assert "| Pivot Rate | 50.0% |" in md
    assert "**Swarm Majority:** BUY → SELL" in md

class TestReportFilters:
    def test_md_cell_escapes_pipes_and_collapses_whitespace(self) -> None:
        from alphaswarm.report import md_cell

        assert md_cell("ZZZT | QQQX\nmerger\r\n  talks ") == "ZZZT \\| QQQX merger talks"

    def test_md_cell_escapes_backslash_before_pipe(self) -> None:
        from alphaswarm.report import md_cell

        assert md_cell("a\\|b") == "a\\\\\\|b"

    def test_md_cell_none_is_empty(self) -> None:
        from alphaswarm.report import md_cell

        assert md_cell(None) == ""

    def test_num_formats_fixed_digits(self) -> None:
        from alphaswarm.report import num

        assert num(0.12345) == "0.12"
        assert num(3, 1) == "3.0"
        assert num(-50) == "-50.00"

    def test_num_none_is_dash(self) -> None:
        from alphaswarm.report import num

        assert num(None) == "—"

    @pytest.mark.parametrize("bad", ["0.5", True, [1]])
    def test_num_rejects_non_numbers(self, bad: object) -> None:
        from alphaswarm.report import num

        with pytest.raises(TypeError, match="num filter expects a number"):
            num(bad)

    def test_filters_registered_on_assembler(self) -> None:
        from alphaswarm.report import ReportAssembler, md_cell, num

        env = ReportAssembler()._env
        assert env.filters["md_cell"] is md_cell
        assert env.filters["num"] is num


def test_consensus_template_has_parse_error_row_and_shares_sum_to_100() -> None:
    md = ReportAssembler().render_section(
        "01_consensus_summary.j2", data=_CONSENSUS_OBS.result, cycle_id="test-cycle",
    )
    assert "| PARSE_ERROR | 3 | 3.0% |" in md
    assert "| BUY | 50 | 50.0% |" in md
    assert "| HOLD | 17 | 17.0% |" in md


def test_round_timeline_template_has_parse_error_column() -> None:
    md = ReportAssembler().render_section(
        "02_round_timeline.j2", data=_TIMELINE_OBS.result, cycle_id="test-cycle",
    )
    assert "| Round | BUY | SELL | HOLD | PARSE_ERROR | Total |" in md
    assert "| 2 | 48 | 32 | 17 | 3 | 100 |" in md


def test_bracket_template_shows_display_name_total_and_dash_for_no_majority() -> None:
    md = ReportAssembler().render_section(
        "03_bracket_narratives.j2", data=_BRACKET_OBS.result, cycle_id="c",
    )
    assert "| Quants | 8 | 1 | 1 | 10 | BUY | 0.85 | 0.72 |" in md
    assert "| Degens | 0 | 0 | 0 | 0 | — | 0.00 | 0.00 |" in md


def test_dissenters_template_empty_state() -> None:
    md = ReportAssembler().render_section("04_key_dissenters.j2", data=[], cycle_id="c")
    assert "_No final-round dissenters._" in md


def test_influence_template_shows_citations_and_share_percent() -> None:
    rows = [{"agent_id": "sell_side_01", "name": "Sell-Side 1", "bracket": "sell_side",
             "citation_count": 2, "influence_share": 0.5}]
    md = ReportAssembler().render_section("05_influence_leaders.j2", data=rows, cycle_id="c")
    assert "| Rank | Agent | Bracket | Citations | Influence Share |" in md
    assert "| 1 | sell_side_01 | sell_side | 2 | 50.0% |" in md


def test_entity_impact_template_reads_contract_keys() -> None:
    rows = [{"entity_name": "ZZZT Holdings", "entity_type": "company", "avg_sentiment": 0.4,
             "mention_count": 3, "buy_mentions": 2, "sell_mentions": 1, "hold_mentions": 0}]
    md = ReportAssembler().render_section("07_entity_impact.j2", data=rows, cycle_id="c")
    assert "| ZZZT Holdings | company | 0.40 | 3 | 2 | 1 | 0 |" in md


def test_entity_impact_template_escapes_pipes_and_newlines() -> None:
    rows = [{"entity_name": "ZZZT | QQQX\nJV", "entity_type": "company", "avg_sentiment": 0.0,
             "mention_count": 1, "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0}]
    md = ReportAssembler().render_section("07_entity_impact.j2", data=rows, cycle_id="c")
    row = next(line for line in md.splitlines() if line.startswith("| ZZZT"))
    assert row == "| ZZZT \\| QQQX JV | company | 0.00 | 1 | 1 | 0 | 0 |"


def test_social_post_reach_template_reads_query_keys() -> None:
    # Exactly the keys read_social_post_reach returns. Legacy cycles with READ_POST
    # edges still produce such rows, and StrictUndefined must not fail them.
    row = {
        "post_id": "post-1",
        "author_name": "Quants 1",
        "bracket": "quants",
        "signal": "buy",
        "round_num": 1,
        "content": "ZZZT Holdings | QQQX Robotics\nfictional deal chatter",
        "reader_count": 12,
    }
    md = ReportAssembler().render_section("08_social_post_reach.j2", data=[row], cycle_id="c")
    table_row = next(line for line in md.splitlines() if line.startswith("| 1 |"))
    assert table_row == (
        "| 1 | Quants 1 | quants | buy | 1 | 12 | "
        "ZZZT Holdings \\| QQQX Robotics fictional deal chatter |"
    )


def test_signal_flip_template_empty_state() -> None:
    md = ReportAssembler().render_section("06_signal_flip_analysis.j2", data=[], cycle_id="c")
    assert "_No agent changed position between rounds._" in md


def test_strict_undefined_raises_on_missing_row_key() -> None:
    from jinja2.exceptions import UndefinedError

    row = {"entity_name": "ZZZT Holdings", "avg_sentiment": 0.4, "mention_count": 2,
           "buy_mentions": 1, "sell_mentions": 1, "hold_mentions": 0}  # entity_type missing
    with pytest.raises(UndefinedError, match="entity_type"):
        ReportAssembler().render_section("07_entity_impact.j2", data=[row], cycle_id="c")


def test_react_prompt_says_final_round_not_round_3() -> None:
    assert "Round 3" not in REACT_SYSTEM_PROMPT
    assert "rounds 1-3" not in REACT_SYSTEM_PROMPT
    assert "final round" in REACT_SYSTEM_PROMPT
