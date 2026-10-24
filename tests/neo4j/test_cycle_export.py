"""Portable export of real graph data on neo4j-test.

The seeded cycle must round-trip through pydantic, stay under 300 KB and never
carry the peer prompt text; a cycle shaped like a pre-2026-10 one must export
with defaults. The last test writes the golden fixture the frontend demo tests use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaswarm.export import CycleExport, export_cycle, export_json
from alphaswarm.graph import GraphStateManager
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.types import SignalType
from tests.support.golden import assert_golden_file
from tests.support.mini_cycle import cypher, dec, write_mini_cycle
from tests.support.seed_builder import PEER_CONTEXT_TEXT, SHOCK_ROUND, SHOCK_TEXT, SeededCycle

pytestmark = pytest.mark.neo4j

REPO = Path(__file__).resolve().parents[2]
FRONTEND_FIXTURE = REPO / "frontend" / "src" / "__tests__" / "fixtures" / "cycle_export.json"
MAX_EXPORT_BYTES = 300_000
LEGACY_AGENT = "legacy_whale_01"


async def test_seeded_cycle_round_trips_and_stays_small(
    seeded_cycle: SeededCycle, graph_reader: GraphStateManager, tmp_path: Path
) -> None:
    export = await export_cycle(graph_reader, seeded_cycle.cycle_id, reports_dir=tmp_path)
    payload = export_json(export)

    assert len(payload.encode("utf-8")) < MAX_EXPORT_BYTES
    assert CycleExport.model_validate_json(payload) == export
    assert PEER_CONTEXT_TEXT not in payload


async def test_seeded_cycle_export_matches_the_builder(
    seeded_cycle: SeededCycle, graph_reader: GraphStateManager, tmp_path: Path
) -> None:
    export = await export_cycle(graph_reader, seeded_cycle.cycle_id, reports_dir=tmp_path)

    assert export.cycle.status == "complete"
    assert export.cycle.num_rounds == seeded_cycle.num_rounds
    assert [a.id for a in export.roster] == [p.id for p in generate_personas(list(DEFAULT_BRACKETS))]
    assert [r.round_num for r in export.rounds] == list(range(1, seeded_cycle.num_rounds + 1))
    for rnd in export.rounds:
        expected = dict(seeded_cycle.decisions[rnd.round_num])
        assert [d.agent_id for d in rnd.decisions] == [p.id for p in seeded_cycle.personas]
        assert all(d.signal == expected[d.agent_id].signal.value for d in rnd.decisions)
        assert {(c.source_id, c.target_id) for c in rnd.citations} == set(seeded_cycle.cited_pairs[rnd.round_num])
    assert [(s.text, s.injected_before_round) for s in export.shocks] == [(SHOCK_TEXT, SHOCK_ROUND)]
    final = export.rounds[-1].decisions
    assert export.cycle.metrics["final_buy"] == sum(1 for d in final if d.signal == "buy")
    assert export.cycle.manifest is None
    assert export.report_markdown is None
    assert all(d.peer_ids == [] and d.control is False for r in export.rounds for d in r.decisions)


async def test_legacy_cycle_exports_with_defaults(graph_manager_test: GraphStateManager, tmp_path: Path) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=3,
        rounds={
            1: [
                ("quants_01", dec(SignalType.BUY, rationale="ZZZT — the premium looks thin")),
                ("degens_01", dec(SignalType.SELL)),
            ],
            2: [("quants_01", dec(SignalType.SELL, cited=["degens_01"])), ("degens_01", dec(SignalType.SELL))],
        },
    )
    # Shape it like a pre-2026-10 cycle: an archival agent, no stored num_rounds,
    # and a run that failed after two rounds.
    await cypher(
        graph_manager_test,
        "MERGE (a:Agent {id: $id}) SET a.name = 'Whale 1', a.bracket = 'whales', "
        "a.influence_weight_base = 0.5, a.temperature = 0.7",
        id=LEGACY_AGENT,
    )
    await cypher(
        graph_manager_test,
        """
        MATCH (a:Agent {id: $agent}), (c:Cycle {cycle_id: $cycle})
        CREATE (a)-[:MADE]->(:Decision {decision_id: $did, cycle_id: $cycle, round: 1,
                signal: 'hold', confidence: 0.4, sentiment: 0.0, rationale: 'archival view'})
        REMOVE c.num_rounds
        SET c.status = 'failed'
        """,
        agent=LEGACY_AGENT,
        cycle=cycle_id,
        did="00000000-0000-4000-8000-00000000beef",
    )
    try:
        export = await export_cycle(graph_manager_test, cycle_id, reports_dir=tmp_path)
    finally:
        await cypher(graph_manager_test, "MATCH (a:Agent {id: $id}) DETACH DELETE a", id=LEGACY_AGENT)

    assert export.cycle.status == "failed"
    assert export.cycle.num_rounds == 2
    assert export.roster[-1].id == LEGACY_AGENT
    assert export.cycle.manifest is None
    assert all(d.peer_ids == [] and d.control is False for r in export.rounds for d in r.decisions)
    assert "—" in export_json(export)


async def test_export_fixture_for_the_frontend(
    seeded_cycle: SeededCycle, graph_reader: GraphStateManager, tmp_path: Path
) -> None:
    export = await export_cycle(graph_reader, seeded_cycle.cycle_id, reports_dir=tmp_path)
    assert_golden_file(FRONTEND_FIXTURE, export.model_dump(mode="json", by_alias=True))
