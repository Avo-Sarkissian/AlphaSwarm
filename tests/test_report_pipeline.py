"""Report pipeline: data -> one narrative call -> markdown + sections."""

from __future__ import annotations

from typing import Any

import pytest

from alphaswarm.report import ReportDataError, collect_report_data, resolve_final_round
from tests.support.report_fakes import (
    CONSENSUS,
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
