"""Reports, advisory inputs and replay work for 2- and 3-round cycles."""

from __future__ import annotations

from collections import Counter

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.report import ReportAssembler
from alphaswarm.types import SignalType
from tests.support.seed_builder import HUB_CITATIONS, SeededCycle

pytestmark = pytest.mark.neo4j


def _pick(seeded_cycle: SeededCycle, seeded_cycle_2r: SeededCycle, num_rounds: int) -> SeededCycle:
    seeded = seeded_cycle if num_rounds == 3 else seeded_cycle_2r
    assert seeded.num_rounds == num_rounds
    return seeded


@pytest.mark.parametrize("num_rounds", [2, 3])
async def test_consensus_and_brackets_use_the_final_round(
    seeded_cycle: SeededCycle,
    seeded_cycle_2r: SeededCycle,
    graph_manager_test: GraphStateManager,
    num_rounds: int,
) -> None:
    seeded = _pick(seeded_cycle, seeded_cycle_2r, num_rounds)
    final = seeded.decisions[num_rounds]
    counts = Counter(d.signal for _, d in final)

    consensus = await graph_manager_test.read_consensus_summary(seeded.cycle_id)
    brackets = await graph_manager_test.read_bracket_narratives(seeded.cycle_id)
    timeline = await graph_manager_test.read_round_timeline(seeded.cycle_id)

    assert consensus == {
        "buy_count": counts[SignalType.BUY],
        "sell_count": counts[SignalType.SELL],
        "hold_count": counts[SignalType.HOLD],
        "parse_error_count": counts[SignalType.PARSE_ERROR],
        "total": len(final),
    }
    assert consensus["buy_count"] + consensus["sell_count"] + consensus["hold_count"] > 0
    assert sum(r["total"] for r in brackets) == len(final) - counts[SignalType.PARSE_ERROR]
    assert [r["round_num"] for r in timeline] == list(range(1, num_rounds + 1))


@pytest.mark.parametrize("num_rounds", [2, 3])
async def test_influence_leaders_exist_for_the_final_round(
    seeded_cycle: SeededCycle,
    seeded_cycle_2r: SeededCycle,
    graph_manager_test: GraphStateManager,
    num_rounds: int,
) -> None:
    seeded = _pick(seeded_cycle, seeded_cycle_2r, num_rounds)
    active = sum(1 for _, d in seeded.decisions[num_rounds] if d.signal != SignalType.PARSE_ERROR)

    leaders = await graph_manager_test.read_influence_leaders(seeded.cycle_id)

    assert leaders, "the seeded builder computes influence edges for the final round"
    for row in leaders:
        assert row["influence_share"] == pytest.approx(row["citation_count"] / active)
    hub, citers = HUB_CITATIONS[0]  # half of each hub's citers cite in round 2, the rest in round 3
    expected = citers if num_rounds == 3 else citers // 2
    assert (leaders[0]["agent_id"], leaders[0]["citation_count"]) == (hub, expected)


@pytest.mark.parametrize("num_rounds", [2, 3])
async def test_key_dissenters_come_from_the_final_round(
    seeded_cycle: SeededCycle,
    seeded_cycle_2r: SeededCycle,
    graph_manager_test: GraphStateManager,
    num_rounds: int,
) -> None:
    seeded = _pick(seeded_cycle, seeded_cycle_2r, num_rounds)
    final = dict(seeded.decisions[num_rounds])

    rows = await graph_manager_test.read_key_dissenters(seeded.cycle_id)

    assert rows
    assert all(final[r["agent_id"]].signal.value.upper() == r["signal"] for r in rows)
    assert all(final[r["agent_id"]].signal is not SignalType.PARSE_ERROR for r in rows)


@pytest.mark.parametrize("num_rounds", [2, 3])
async def test_rendered_consensus_section_is_not_empty(
    seeded_cycle: SeededCycle,
    seeded_cycle_2r: SeededCycle,
    graph_manager_test: GraphStateManager,
    num_rounds: int,
) -> None:
    seeded = _pick(seeded_cycle, seeded_cycle_2r, num_rounds)
    consensus = await graph_manager_test.read_consensus_summary(seeded.cycle_id)

    md = ReportAssembler().render_section(
        "01_consensus_summary.j2",
        data=consensus,
        cycle_id=seeded.cycle_id,
    )

    assert f"| BUY | {consensus['buy_count']} |" in md
    assert f"**Total agents:** {len(seeded.decisions[num_rounds])}" in md
