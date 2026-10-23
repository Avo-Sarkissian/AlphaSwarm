"""Unit tests for the report section templates, filters and renderer."""

from __future__ import annotations

import pytest

from alphaswarm.report import ReportAssembler

# Report read rows (GraphStateManager shapes) for the single-template render tests.
_CONSENSUS_ROW: dict = {"buy_count": 50, "sell_count": 30, "hold_count": 17, "parse_error_count": 3, "total": 100}
_TIMELINE_ROWS: list[dict] = [
    {"round_num": 1, "buy_count": 45, "sell_count": 35, "hold_count": 18, "parse_error_count": 2, "total": 100},
    {"round_num": 2, "buy_count": 48, "sell_count": 32, "hold_count": 17, "parse_error_count": 3, "total": 100},
    {"round_num": 3, "buy_count": 50, "sell_count": 30, "hold_count": 17, "parse_error_count": 3, "total": 100},
]
_BRACKET_ROWS: list[dict] = [
    {
        "bracket": "quants",
        "display_name": "Quants",
        "buy_count": 8,
        "sell_count": 1,
        "hold_count": 1,
        "total": 10,
        "avg_confidence": 0.85,
        "avg_sentiment": 0.72,
        "majority": "BUY",
    },
    {
        "bracket": "degens",
        "display_name": "Degens",
        "buy_count": 0,
        "sell_count": 0,
        "hold_count": 0,
        "total": 0,
        "avg_confidence": 0.0,
        "avg_sentiment": 0.0,
        "majority": None,
    },
]


class TestReportAssembler:
    def test_renders_section(self) -> None:
        """ReportAssembler.render_section returns markdown with section heading and data values."""
        assembler = ReportAssembler()
        data = {
            "buy_count": 50,
            "sell_count": 30,
            "hold_count": 17,
            "parse_error_count": 3,
            "total": 100,
        }
        result = assembler.render_section(
            "01_consensus_summary.j2",
            data=data,
            cycle_id="test-cycle",
        )

        assert "Consensus Summary" in result
        assert "50" in result
        assert "30" in result


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
    result = assembler.render_section("11_shock_impact.j2", data=_SHOCK_IMPACT_DATA, cycle_id="test-cycle")

    assert "Bracket Signal Shift" in result
    assert "Quants" in result
    assert "Degens" in result


def test_shock_impact_template_renders_pivot_list() -> None:
    """Phase 27 SHOCK-05 — 11_shock_impact.j2 renders Agent Pivot List heading when pivots exist."""
    from alphaswarm.report import ReportAssembler

    assembler = ReportAssembler()
    result = assembler.render_section("11_shock_impact.j2", data=_SHOCK_IMPACT_DATA, cycle_id="test-cycle")

    assert "Agent Pivot List" in result
    assert "a01" in result
    assert "a02" in result


def test_shock_template_shows_pre_dominant_per_bracket() -> None:
    md = ReportAssembler().render_section(
        "11_shock_impact.j2",
        data=_SHOCK_IMPACT_DATA,
        cycle_id="c",
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
        "01_consensus_summary.j2",
        data=_CONSENSUS_ROW,
        cycle_id="test-cycle",
    )
    assert "| PARSE_ERROR | 3 | 3.0% |" in md
    assert "| BUY | 50 | 50.0% |" in md
    assert "| HOLD | 17 | 17.0% |" in md


def test_round_timeline_template_has_parse_error_column() -> None:
    md = ReportAssembler().render_section(
        "02_round_timeline.j2",
        data=_TIMELINE_ROWS,
        cycle_id="test-cycle",
    )
    assert "| Round | BUY | SELL | HOLD | PARSE_ERROR | Total |" in md
    assert "| 2 | 48 | 32 | 17 | 3 | 100 |" in md


def test_bracket_template_shows_display_name_total_and_dash_for_no_majority() -> None:
    md = ReportAssembler().render_section(
        "03_bracket_narratives.j2",
        data=_BRACKET_ROWS,
        cycle_id="c",
    )
    assert "| Quants | 8 | 1 | 1 | 10 | BUY | 0.85 | 0.72 |" in md
    assert "| Degens | 0 | 0 | 0 | 0 | — | 0.00 | 0.00 |" in md


def test_dissenters_template_empty_state() -> None:
    md = ReportAssembler().render_section("04_key_dissenters.j2", data=[], cycle_id="c")
    assert "_No final-round dissenters._" in md


def test_influence_template_shows_citations_and_share_percent() -> None:
    rows = [
        {
            "agent_id": "sell_side_01",
            "name": "Sell-Side 1",
            "bracket": "sell_side",
            "citation_count": 2,
            "influence_share": 0.5,
        }
    ]
    md = ReportAssembler().render_section("05_influence_leaders.j2", data=rows, cycle_id="c")
    assert "| Rank | Agent | Bracket | Citations | Influence Share |" in md
    assert "| 1 | sell_side_01 | sell_side | 2 | 50.0% |" in md


def test_entity_impact_template_reads_contract_keys() -> None:
    rows = [
        {
            "entity_name": "ZZZT Holdings",
            "entity_type": "company",
            "avg_sentiment": 0.4,
            "mention_count": 3,
            "buy_mentions": 2,
            "sell_mentions": 1,
            "hold_mentions": 0,
        }
    ]
    md = ReportAssembler().render_section("07_entity_impact.j2", data=rows, cycle_id="c")
    assert "| ZZZT Holdings | company | 0.40 | 3 | 2 | 1 | 0 |" in md


def test_entity_impact_template_escapes_pipes_and_newlines() -> None:
    rows = [
        {
            "entity_name": "ZZZT | QQQX\nJV",
            "entity_type": "company",
            "avg_sentiment": 0.0,
            "mention_count": 1,
            "buy_mentions": 1,
            "sell_mentions": 0,
            "hold_mentions": 0,
        }
    ]
    md = ReportAssembler().render_section("07_entity_impact.j2", data=rows, cycle_id="c")
    row = next(line for line in md.splitlines() if line.startswith("| ZZZT"))
    assert row == "| ZZZT \\| QQQX JV | company | 0.00 | 1 | 1 | 0 | 0 |"


def test_signal_flip_template_empty_state() -> None:
    md = ReportAssembler().render_section("06_signal_flip_analysis.j2", data=[], cycle_id="c")
    assert "_No agent changed position between rounds._" in md


def test_strict_undefined_raises_on_missing_row_key() -> None:
    from jinja2.exceptions import UndefinedError

    row = {
        "entity_name": "ZZZT Holdings",
        "avg_sentiment": 0.4,
        "mention_count": 2,
        "buy_mentions": 1,
        "sell_mentions": 1,
        "hold_mentions": 0,
    }  # entity_type missing
    with pytest.raises(UndefinedError, match="entity_type"):
        ReportAssembler().render_section("07_entity_impact.j2", data=[row], cycle_id="c")
