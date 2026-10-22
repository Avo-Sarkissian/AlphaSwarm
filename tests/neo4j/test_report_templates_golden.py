"""Report templates rendered from real rows of the seeded cycle.

Every template must render under StrictUndefined (a key the query does not return is an
error, not a blank cell). Templates without a known bug are pinned with a golden.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from alphaswarm.report import TEMPLATE_DIR, ReportAssembler, md_cell, num
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
    "08_social_post_reach.j2": lambda gm, cid: gm.read_social_post_reach(cid),
    "11_shock_impact.j2": lambda gm, cid: gm.read_shock_impact(cid),
}

_STRICT_XFAIL = {
    "07_entity_impact.j2": pytest.mark.xfail(
        strict=True,
        reason="T2.2: entity-impact template reads keys the query never returns (fix: plan 06)",
    ),
}

_SHARE_RE = re.compile(r"^\| [A-Z_ ]+ \| \d+ \| (?P<share>\d+\.\d)% \|$", re.MULTILINE)


def _strict_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    env.filters["md_cell"] = md_cell
    env.filters["num"] = num
    return env


def _table_rows(markdown: str) -> list[list[str]]:
    """Data rows of the first markdown table (header and separator skipped)."""
    lines = [line for line in markdown.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[2:]]


def test_every_template_has_a_row_source() -> None:
    assert {path.name for path in TEMPLATE_DIR.glob("*.j2")} == set(SOURCES)


@pytest.mark.parametrize(
    "template",
    [pytest.param(name, marks=_STRICT_XFAIL.get(name, ())) for name in sorted(SOURCES)],
)
async def test_template_renders_with_strict_undefined(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle, template: str
) -> None:
    data = await SOURCES[template](graph_reader, seeded_cycle.cycle_id)
    rendered = (
        _strict_env().get_template(template).render(data=data, cycle_id=seeded_cycle.cycle_id)
    )
    assert rendered.startswith("## ")


async def test_signal_flip_template_golden(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_signal_flips(seeded_cycle.cycle_id)
    rendered = ReportAssembler().render_section(
        "06_signal_flip_analysis.j2", data=rows, cycle_id=seeded_cycle.cycle_id
    )
    assert len(_table_rows(rendered)) == len(rows)
    assert_golden("report/06_signal_flip_analysis.md", rendered)


@pytest.mark.xfail(
    strict=True, reason="T2.2: entity-impact table renders blank cells (fix: plan 06)"
)
async def test_entity_impact_table_has_no_blank_cells(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_entity_impact(seeded_cycle.cycle_id)
    assert rows
    rendered = ReportAssembler().render_section(
        "07_entity_impact.j2", data=rows, cycle_id=seeded_cycle.cycle_id
    )
    table = _table_rows(rendered)
    assert table
    assert all(all(cells) for cells in table)


@pytest.mark.xfail(
    strict=True, reason="T2.3: consensus shares use a total that includes failures (fix: plan 06)"
)
async def test_consensus_shares_add_up_to_100(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    data = await graph_reader.read_consensus_summary(seeded_cycle.cycle_id)
    rendered = ReportAssembler().render_section(
        "01_consensus_summary.j2", data=data, cycle_id=seeded_cycle.cycle_id
    )
    shares = [float(m.group("share")) for m in _SHARE_RE.finditer(rendered)]
    assert len(shares) >= 3
    assert sum(shares) == pytest.approx(100.0, abs=0.3)
