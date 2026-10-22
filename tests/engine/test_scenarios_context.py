"""Prompt-content and lifecycle scenarios on the real run_simulation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import NewsSlice
from alphaswarm.types import AgentPersona
from alphaswarm.worker import MARKET_CONTEXT_GUARD, UNTRUSTED_DATA_OPEN
from tests.engine.scenario import RunScenario, recorded_decisions, round_calls
from tests.inference.fakes import ScriptedProvider
from tests.support.controllers import ImmediateController

HEADLINE = "ZZZT Holdings confirms a strategic review"


async def test_round_prompts_show_previous_round_peers_and_never_self(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    await run_scenario()
    bracket_of = {p.id: p.bracket for p in all_personas}
    assert all(c.shown_peer_ids == () for c in round_calls(scripted_worker, 1))
    for round_num in (2, 3):
        calls = round_calls(scripted_worker, round_num)
        assert len(calls) == 100
        for call in calls:
            assert 1 <= len(call.shown_peer_ids) <= 10, call.agent_id
            assert call.agent_id not in call.shown_peer_ids
            assert len({bracket_of[p] for p in call.shown_peer_ids}) >= 4, call.agent_id
    shown = {
        (c.agent_id, c.round_num): set(c.shown_peer_ids)
        for c in scripted_worker.calls_for("decision")
    }
    decisions_by_round = recorded_decisions(fake_graph)
    assert [len(decisions_by_round[r]) for r in (1, 2, 3)] == [100, 100, 100]
    # The default script cites shown peers, so an empty list means citations were lost.
    assert all(d.cited_agents for r in (2, 3) for _, d in decisions_by_round[r])
    for round_num, decisions in decisions_by_round.items():
        for agent_id, decision in decisions:
            assert set(decision.cited_agents) <= shown[(agent_id, round_num)]


async def test_market_context_reaches_round_1_only(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider
) -> None:
    """Pins docs/DECISIONS.md#adr-market-context and #p40-d-06 (Round 1 only, fenced)."""
    news = FakeNewsProvider(
        {
            "ZZZT Holdings": NewsSlice(
                entity="ZZZT Holdings",
                headlines=(HEADLINE,),
                fetched_at=datetime(2026, 10, 3, tzinfo=UTC),
                source="fake_news",
            )
        }
    )
    await run_scenario(market_provider=FakeMarketDataProvider(), news_provider=news)
    for round_num, expected in ((1, True), (2, False), (3, False)):
        for call in round_calls(scripted_worker, round_num):
            systems = [m["content"] for m in call.messages if m["role"] == "system"]
            assert (MARKET_CONTEXT_GUARD in systems) is expected
            assert (UNTRUSTED_DATA_OPEN in call.messages[-1]["content"]) is expected
    assert HEADLINE in round_calls(scripted_worker, 1)[0].messages[-1]["content"]


async def test_worker_lifecycle_two_sessions_d05(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    scripted_orchestrator: ScriptedProvider,
    scenario_controller: ImmediateController,
    fake_model_manager: MagicMock,
) -> None:
    """Pins docs/DECISIONS.md#p7-d-05 and #p7-d-06 (worker reload and a fresh governor
    session for rounds 2-3). It is kept out of the scenario goldens on purpose, so a
    revision of that lifecycle rewrites only this test."""
    await run_scenario()
    assert (scripted_orchestrator.prepare_calls, scripted_orchestrator.teardown_calls) == (1, 1)
    assert (scripted_worker.prepare_calls, scripted_worker.teardown_calls) == (2, 2)
    assert (scenario_controller.monitoring_starts, scenario_controller.monitoring_stops) == (2, 2)
    assert fake_model_manager.ensure_clean_state.await_count == 2
    fake_model_manager.load_model.assert_not_awaited()
    fake_model_manager.unload_model.assert_not_awaited()
