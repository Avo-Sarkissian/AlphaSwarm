"""Report pipeline: data -> one narrative call -> markdown + sections."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest

from alphaswarm.report import (
    NARRATIVE_UNAVAILABLE,
    SECTION_TEMPLATES,
    TEMPLATE_DIR,
    ReportDataError,
    ReportNarrativeLLMOutput,
    ReportSections,
    build_sections,
    collect_report_data,
    render_report,
    resolve_final_round,
)
from tests.support.report_fakes import (
    CONSENSUS,
    FLIPS,
    INFLUENCE,
    REPORT_CYCLE,
    REPORT_RUMOR,
    SHOCK,
    TIMELINE,
    FakeReportGraph,
)

_READS_WITHOUT_SHOCK = {
    "read_consensus_summary",
    "read_round_timeline",
    "read_bracket_narratives",
    "read_key_dissenters",
    "read_influence_leaders",
    "read_signal_flips",
    "read_entity_impact",
    "read_shock_event",
    "read_cycle_seed",
}


def _graph(**kwargs: Any) -> Any:
    return FakeReportGraph(**kwargs)


async def test_resolve_final_round_is_the_last_round_in_the_data() -> None:
    assert await resolve_final_round(_graph(), REPORT_CYCLE) == 3
    two = [row for row in TIMELINE if row["round_num"] <= 2]
    assert await resolve_final_round(_graph(timeline=two), REPORT_CYCLE) == 2


async def test_resolve_final_round_rejects_a_cycle_without_decisions() -> None:
    with pytest.raises(ReportDataError, match="no decisions"):
        await resolve_final_round(_graph(timeline=[]), REPORT_CYCLE)


async def test_collect_binds_the_cycle_id_on_every_read() -> None:
    graph = _graph()
    data = await collect_report_data(graph, REPORT_CYCLE, 3)
    assert {name for name, _ in graph.calls} == _READS_WITHOUT_SHOCK
    assert {cycle for _, cycle in graph.calls} == {REPORT_CYCLE}
    assert data.cycle_id == REPORT_CYCLE and data.final_round == 3
    assert data.consensus == CONSENSUS
    assert data.influence == INFLUENCE
    assert data.seed_rumor == REPORT_RUMOR
    assert data.shock is None
    assert data.generated_at.tzinfo is not None


async def test_collect_reads_shock_impact_only_when_a_shock_exists() -> None:
    graph = _graph(shock=True)
    data = await collect_report_data(graph, REPORT_CYCLE, 3)
    assert data.shock == SHOCK
    assert ("read_shock_impact", REPORT_CYCLE) in graph.calls


async def test_collect_runs_the_reads_concurrently() -> None:
    graph = _graph()
    await collect_report_data(graph, REPORT_CYCLE, 3)
    assert graph.max_in_flight == len(_READS_WITHOUT_SHOCK)


async def test_missing_seed_becomes_an_empty_string() -> None:
    data = await collect_report_data(_graph(seed=None), REPORT_CYCLE, 3)
    assert data.seed_rumor == ""


NARRATIVE = ReportNarrativeLLMOutput(
    summary="Consensus ended BUY 52-21-24 after Sell-Side conviction spread in R2.",
    moments=["R2: sell_side_03 became the most cited agent.", "R3: buying firmed to 52."],
    dissent=["shorts_02 bought against a sell-majority Shorts bracket."],
    followups=["Watch whether QQQX Robotics guidance holds."],
)


async def _data(**kwargs: Any) -> Any:
    return await collect_report_data(_graph(**kwargs), REPORT_CYCLE, 3)


def _headings(markdown: str) -> list[str]:
    return re.findall(r"^#{1,2} .+$", markdown, flags=re.MULTILINE)


def test_section_templates_cover_every_template_file() -> None:
    assert {template for _, template in SECTION_TEMPLATES} == {path.name for path in TEMPLATE_DIR.glob("*.j2")}


async def test_render_orders_header_summary_tables_and_narrative() -> None:
    md = render_report(await _data(shock=True), NARRATIVE)
    assert _headings(md) == [
        "# Post-Simulation Analysis Report",
        "## Executive Summary",
        "## Consensus Summary",
        "## Round Timeline",
        "## Bracket Narratives",
        "## Key Dissenters",
        "## Influence Leaders",
        "## Signal Flip Analysis",
        "## Entity Impact",
        "## Shock Impact Analysis",
        "## Key Moments",
        "## Dissent",
        "## Follow-ups",
    ]
    assert f"**Cycle:** {REPORT_CYCLE}" in md
    assert "**Rounds:** 3" in md
    assert NARRATIVE.summary in md
    assert "- R2: sell_side_03 became the most cited agent." in md


async def test_render_without_narrative_keeps_every_table() -> None:
    md = render_report(await _data(), None)
    assert NARRATIVE_UNAVAILABLE in md
    assert "## Key Moments" not in md and "## Follow-ups" not in md
    assert "## Influence Leaders" in md and "## Entity Impact" in md


async def test_render_skips_the_shock_section_without_a_shock() -> None:
    assert "## Shock Impact Analysis" not in render_report(await _data(), NARRATIVE)


async def test_header_keeps_the_rumor_on_one_line() -> None:
    data = replace(await _data(), seed_rumor="ZZZT | QQQX\nmerger")
    md = render_report(data, NARRATIVE)
    assert "**Rumor:** ZZZT \\| QQQX merger" in md


async def test_empty_narrative_lists_are_omitted() -> None:
    narrative = ReportNarrativeLLMOutput(summary="Flat cycle.")
    md = render_report(await _data(), narrative)
    assert "## Executive Summary" in md and "## Dissent" not in md


def test_narrative_model_is_lenient_and_capped() -> None:
    out = ReportNarrativeLLMOutput.model_validate(
        {
            "summary": "## Summary\nConsensus   ended\nBUY.",
            "moments": [f"R{i}: moment {i}" for i in range(1, 10)] + [7, ""],
            "dissent": "shorts_02 dissented.",
            "followups": None,
            "confidence": 0.9,
        }
    )
    assert out.summary == "Summary Consensus ended BUY."
    assert len(out.moments) == 6
    assert out.dissent == ["shorts_02 dissented."]
    assert out.followups == []


def test_narrative_model_keeps_leading_signs_on_numbers() -> None:
    out = ReportNarrativeLLMOutput.model_validate(
        {
            "summary": "-12% guidance from QQQX Robotics flipped the Shorts.",
            "followups": ["- Watch QQQX Robotics guidance.", "+5% on ZZZT Holdings would test the BUY camp."],
        }
    )
    assert out.summary.startswith("-12% guidance")
    assert out.followups == [
        "Watch QQQX Robotics guidance.",
        "+5% on ZZZT Holdings would test the BUY camp.",
    ]


def test_narrative_model_requires_a_summary() -> None:
    with pytest.raises(ValueError):
        ReportNarrativeLLMOutput.model_validate({"summary": "   ", "moments": []})


async def test_build_sections_copies_rows_and_narrative() -> None:
    data = await _data()
    sections = build_sections(data, NARRATIVE)
    assert isinstance(sections, ReportSections)
    assert sections.convergence == TIMELINE
    assert sections.influence == INFLUENCE
    assert sections.summary == NARRATIVE.summary
    assert sections.moments == NARRATIVE.moments
    empty = build_sections(data, None)
    assert (empty.summary, empty.moments, empty.dissent, empty.followups) == ("", [], [], [])
    assert empty.convergence == TIMELINE
    assert FLIPS  # imported fixture stays fictional and non-empty
