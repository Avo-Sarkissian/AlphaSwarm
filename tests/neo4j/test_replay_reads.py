"""Replay reads against real Cypher: per-round bracket totals and Decision rationales."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from alphaswarm.config import DEFAULT_BRACKETS, generate_personas, load_bracket_configs
from alphaswarm.graph import GraphStateManager
from alphaswarm.state import StateStore
from alphaswarm.types import SignalType
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.replay_manager import ReplayManager
from tests.support.mini_cycle import cypher, dec, write_mini_cycle
from tests.support.seed_builder import SeededCycle

pytestmark = pytest.mark.neo4j


async def test_replay_bracket_rows_have_totals_without_failures(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [
                ("degens_01", dec(SignalType.BUY)),
                ("degens_02", dec(SignalType.SELL)),
                ("degens_03", dec(SignalType.PARSE_ERROR, 0.0)),
            ]
        },
    )

    rows = await graph_manager_test.read_bracket_narratives_for_round(cycle_id, 1)

    assert rows == [
        {
            "bracket": "degens",
            "buy_count": 1,
            "sell_count": 1,
            "hold_count": 0,
            "total": 2,
            "avg_confidence": pytest.approx(0.7),
            "avg_sentiment": pytest.approx(0.1),
        }
    ]


async def test_replay_rationale_reads_decision_not_episode(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [
                ("quants_01", dec(SignalType.BUY, 0.9, rationale="decision text")),
                ("quants_02", dec(SignalType.SELL, 0.9, rationale="second text")),
            ]
        },
    )
    await cypher(
        graph_manager_test,
        "MATCH (d:Decision {cycle_id: $id})-[:HAS_EPISODE]->(re:RationaleEpisode) "
        "SET re.rationale = 'stale episode text'",
        id=cycle_id,
    )

    rows = await graph_manager_test.read_rationale_entries_for_round(cycle_id, 1)

    assert rows == [
        {"agent_id": "quants_01", "signal": "buy", "rationale": "decision text", "round_num": 1},
        {"agent_id": "quants_02", "signal": "sell", "rationale": "second text", "round_num": 1},
    ]


async def test_replay_of_seeded_cycle_shows_every_bracket(
    seeded_cycle: SeededCycle,
    graph_manager_test: GraphStateManager,
) -> None:
    manager = ReplayManager(SimpleNamespace(state_store=StateStore()))  # type: ignore[arg-type]
    signals = await graph_manager_test.read_full_cycle_signals(seeded_cycle.cycle_id)

    await manager.start(seeded_cycle.cycle_id, signals, ConnectionManager(), graph_manager_test)

    summaries = manager.store.snapshot().bracket_summaries
    assert [s.display_name for s in summaries] == [b.display_name for b in DEFAULT_BRACKETS]
    bracket_of = {p.id: p.bracket.value for p in generate_personas(load_bracket_configs())}
    valid_r1 = [aid for aid, d in seeded_cycle.decisions[1] if d.signal != SignalType.PARSE_ERROR]
    assert sum(s.total for s in summaries) == len(valid_r1)
    assert {s.bracket for s in summaries if s.total > 0} == {bracket_of[a] for a in valid_r1}
