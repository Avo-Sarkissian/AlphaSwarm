"""Report templates rendered from real rows of the seeded cycle.

Every template must render under StrictUndefined (a key the query does not return is an
error, not a blank cell). Templates without a known bug are pinned with a golden.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest
from jinja2 import Environment

from alphaswarm.report import TEMPLATE_DIR, ReportAssembler, ToolObservation
from tests.support.golden import assert_golden

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from tests.support.seed_builder import SeededCycle

pytestmark = pytest.mark.neo4j

Source = Callable[["GraphStateManager", str], Awaitable[object]]

# Template file -> the read that feeds it (same pairing as web/routes/report.py).
SOURCES: dict[str, Source] = {
    "01_consensus_summary.j2": lambda gm, cid: gm.read_consensus_summary(cid),
    "02_round_timeline.j2": lambda gm, cid: gm.read_round_timeline(cid),
    "03_bracket_narratives.j2": lambda gm, cid: gm.read_bracket_narratives(cid),
    "04_key_dissenters.j2": lambda gm, cid: gm.read_key_dissenters(cid),
    "05_influence_leaders.j2": lambda gm, cid: gm.read_influence_leaders(cid),
    "06_signal_flip_analysis.j2": lambda gm, cid: gm.read_signal_flips(cid),
    "07_entity_impact.j2": lambda gm, cid: gm.read_entity_impact(cid),
    "11_shock_impact.j2": lambda gm, cid: gm.read_shock_impact(cid),
}

_SHARE_RE = re.compile(r"^\| [A-Z_ ]+ \| \d+ \| (?P<share>\d+\.\d)% \|$", re.MULTILINE)


def _strict_env() -> Environment:
    return ReportAssembler()._env


def _table_rows(markdown: str) -> list[list[str]]:
    """Data rows of the first markdown table (header and separator skipped)."""
    lines = [line for line in markdown.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[2:]]


def test_every_template_has_a_row_source() -> None:
    assert {path.name for path in TEMPLATE_DIR.glob("*.j2")} == set(SOURCES)


@pytest.mark.parametrize("template", sorted(SOURCES))
async def test_template_renders_with_strict_undefined(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle, template: str
) -> None:
    data = await SOURCES[template](graph_reader, seeded_cycle.cycle_id)
    rendered = _strict_env().get_template(template).render(data=data, cycle_id=seeded_cycle.cycle_id)
    assert rendered.startswith("## ")


async def test_signal_flip_template_golden(graph_reader: GraphStateManager, seeded_cycle: SeededCycle) -> None:
    rows = await graph_reader.read_signal_flips(seeded_cycle.cycle_id)
    rendered = ReportAssembler().render_section("06_signal_flip_analysis.j2", data=rows, cycle_id=seeded_cycle.cycle_id)
    assert len(_table_rows(rendered)) == len(rows)
    assert_golden("report/06_signal_flip_analysis.md", rendered)


async def test_entity_impact_table_has_no_blank_cells(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_entity_impact(seeded_cycle.cycle_id)
    assert rows
    rendered = ReportAssembler().render_section("07_entity_impact.j2", data=rows, cycle_id=seeded_cycle.cycle_id)
    table = _table_rows(rendered)
    assert table
    assert all(all(cells) for cells in table)


async def test_consensus_shares_add_up_to_100(graph_reader: GraphStateManager, seeded_cycle: SeededCycle) -> None:
    data = await graph_reader.read_consensus_summary(seeded_cycle.cycle_id)
    rendered = ReportAssembler().render_section("01_consensus_summary.j2", data=data, cycle_id=seeded_cycle.cycle_id)
    shares = [float(m.group("share")) for m in _SHARE_RE.finditer(rendered)]
    assert len(shares) >= 3
    assert sum(shares) == pytest.approx(100.0, abs=0.3)


TEMPLATE_READERS: tuple[tuple[str, str], ...] = (
    ("01_consensus_summary.j2", "read_consensus_summary"),
    ("02_round_timeline.j2", "read_round_timeline"),
    ("03_bracket_narratives.j2", "read_bracket_narratives"),
    ("04_key_dissenters.j2", "read_key_dissenters"),
    ("05_influence_leaders.j2", "read_influence_leaders"),
    ("06_signal_flip_analysis.j2", "read_signal_flips"),
    ("07_entity_impact.j2", "read_entity_impact"),
    ("11_shock_impact.j2", "read_shock_impact"),
)


@pytest.mark.parametrize(("template", "reader"), TEMPLATE_READERS)
async def test_every_template_renders_seeded_rows_strictly(
    seeded_cycle: SeededCycle,
    graph_manager_test: GraphStateManager,
    template: str,
    reader: str,
) -> None:
    rows = await getattr(graph_manager_test, reader)(seeded_cycle.cycle_id)

    md = ReportAssembler().render_section(template, data=rows, cycle_id=seeded_cycle.cycle_id)

    # [ \t], not \s: a row ending "|" followed by the next row's "|" is not a blank cell.
    assert re.search(r"\|[ \t]*\|", md) is None, md  # no blank cell anywhere
    assert "None" not in md


@pytest.mark.parametrize(
    ("template", "reader"),
    # 06 is pinned by test_signal_flip_template_golden.
    [pair for pair in TEMPLATE_READERS if pair[0] != "06_signal_flip_analysis.j2"],
)
async def test_fixed_template_golden(
    seeded_cycle: SeededCycle,
    graph_manager_test: GraphStateManager,
    template: str,
    reader: str,
) -> None:
    rows = await getattr(graph_manager_test, reader)(seeded_cycle.cycle_id)
    md = ReportAssembler().render_section(template, data=rows, cycle_id=seeded_cycle.cycle_id)
    assert_golden(f"report/{template.removesuffix('.j2')}.md", md)


TOOL_READERS: tuple[tuple[str, str], ...] = (
    ("bracket_summary", "read_consensus_summary"),
    ("round_timeline", "read_round_timeline"),
    ("bracket_narratives", "read_bracket_narratives"),
    ("key_dissenters", "read_key_dissenters"),
    ("influence_leaders", "read_influence_leaders"),
    ("signal_flip_analysis", "read_signal_flips"),
    ("entity_impact", "read_entity_impact"),
    ("shock_impact", "read_shock_impact"),
)


async def test_assembled_report_has_no_empty_section(
    seeded_cycle: SeededCycle,
    graph_manager_test: GraphStateManager,
) -> None:
    observations = [
        ToolObservation(
            tool_name=tool,
            tool_input={"cycle_id": seeded_cycle.cycle_id},
            result=await getattr(graph_manager_test, reader)(seeded_cycle.cycle_id),
        )
        for tool, reader in TOOL_READERS
    ]

    md = ReportAssembler().assemble(observations, seeded_cycle.cycle_id)

    sections = re.split(r"^## ", md, flags=re.MULTILINE)[1:]
    assert len(sections) == len(TOOL_READERS)
    for section in sections:
        heading, _, body = section.partition("\n")
        assert body.strip(), f"empty report section: {heading}"
