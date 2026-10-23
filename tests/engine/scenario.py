"""Constants and helpers for deterministic run_simulation scenarios.

All data is fictional. scenario_summary() reduces a run to a domain-level record
for golden comparison; it deliberately excludes lifecycle counts so engine
refactors can keep a scenario golden byte-identical.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Sequence
from typing import Final
from unittest.mock import MagicMock

from alphaswarm.inference.types import InferenceMessage
from alphaswarm.simulation import SimulationResult
from alphaswarm.state import StateStore
from alphaswarm.types import AgentDecision, AgentPersona, BracketType, SimulationPhase
from tests.inference.fakes import (
    DecisionFn,
    ScriptedCall,
    ScriptedProvider,
    default_decision_script,
)

SCENARIO_CYCLE_ID: Final = "00000000-0000-4000-8000-000000000001"
SCENARIO_RUMOR: Final = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SCENARIO_SHOCK_TEXT: Final = "QQQX Robotics board rejects the offer as undervalued."
SCENARIO_SEED_JSON: Final = json.dumps(
    {
        "entities": [
            {"name": "ZZZT Holdings", "type": "company", "relevance": 0.95, "sentiment": 0.6},
            {"name": "QQQX Robotics", "type": "company", "relevance": 0.9, "sentiment": 0.7},
            {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.4},
        ],
        "overall_sentiment": 0.55,
    }
)
SCENARIO_MODIFIERS_JSON: Final = json.dumps(
    {b.value: f"specialist tracking the ZZZT-QQQX deal for the {b.value} desk" for b in BracketType},
    sort_keys=True,
)

RunScenario = Callable[..., Awaitable[SimulationResult]]


class RecordingStateStore(StateStore):
    """A real StateStore that also records every set_phase call, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.phases: list[SimulationPhase] = []

    async def set_phase(self, phase: SimulationPhase) -> None:
        self.phases.append(phase)
        await super().set_phase(phase)


def recorded_decisions(graph: MagicMock) -> dict[int, list[tuple[str, AgentDecision]]]:
    """Decisions handed to GraphStateManager.persist_round, keyed by round.

    The engine calls persist_round(cycle_id, round_num, decisions, decision_ids=..., ...)
    once per round (docs/DECISIONS.md#p4-d-08).
    """
    out: dict[int, list[tuple[str, AgentDecision]]] = {}
    for call in graph.persist_round.await_args_list:
        out[int(call.args[1])] = list(call.args[2])
    return out


def persisted_rounds(graph: MagicMock) -> list[int]:
    """Round numbers whose decisions reached the graph, ascending."""
    return sorted(recorded_decisions(graph))


def round_calls(worker: ScriptedProvider, round_num: int) -> list[ScriptedCall]:
    """Decision calls the worker received for one round."""
    return [c for c in worker.calls_for("decision") if c.round_num == round_num]


def influence_weights_from_writes(graph: MagicMock, *, up_to_round: int, total_agents: int) -> dict[str, float]:
    """In-memory stand-in for GraphStateManager.compute_influence_edges.

    Mirrors the real query: DISTINCT (author, cited) pairs from rounds 1..up_to_round
    with self-citations dropped, weight = pairs naming the agent / total_agents. Like
    the real method it returns {} when total_agents <= 0 (a fully failed round) or
    when nothing is cited.
    """
    if total_agents <= 0:
        return {}
    pairs = {
        (author, cited)
        for round_num, decisions in recorded_decisions(graph).items()
        if round_num <= up_to_round
        for author, decision in decisions
        for cited in decision.cited_agents
        if cited != author
    }
    if not pairs:
        return {}
    counts = Counter(cited for _, cited in pairs)
    return {agent_id: n / total_agents for agent_id, n in sorted(counts.items())}


def failing_in_round(
    round_num: int,
    make_error: Callable[[str], BaseException],
    *,
    agent_ids: Collection[str] | None = None,
) -> DecisionFn:
    """DecisionFn returning make_error(agent_id) in one round (all agents, or only agent_ids)."""

    def _decide(agent_id: str, current: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if current == round_num and (agent_ids is None or agent_id in agent_ids):
            return make_error(agent_id)
        return default_decision_script(agent_id, current, call)

    return _decide


def _decision_row(agent_id: str, decision: AgentDecision) -> str:
    cited = ",".join(decision.cited_agents)
    return f"{agent_id}|{decision.signal.value}|{decision.confidence:.2f}|{cited}"


def _after_rumor(messages: list[InferenceMessage]) -> str:
    user = messages[-1]["content"]
    return user.split(SCENARIO_RUMOR, 1)[1] if SCENARIO_RUMOR in user else "<rumor missing>"


def scenario_summary(
    *,
    store: RecordingStateStore,
    worker: ScriptedProvider,
    graph: MagicMock,
    personas: Sequence[AgentPersona],
) -> dict[str, object]:
    """Domain-level record of a scenario run for golden comparison (no timings, no lifecycle)."""
    bracket_of = {p.id: p.bracket.value for p in personas}
    rounds: dict[str, object] = {}
    for round_num, decisions in sorted(recorded_decisions(graph).items()):
        calls = round_calls(worker, round_num)
        slots = Counter(bracket_of[pid] for c in calls for pid in c.shown_peer_ids)
        rounds[str(round_num)] = {
            "decision_calls": len(calls),
            "decisions": [_decision_row(agent_id, d) for agent_id, d in decisions],
            "signal_counts": dict(sorted(Counter(d.signal.value for _, d in decisions).items())),
            "peer_slots_by_bracket": dict(sorted(slots.items())),
            "user_message_suffixes": sorted({_after_rumor(c.messages) for c in calls}),
        }
    metric_calls = graph.write_cycle_metrics.await_args_list
    metrics = dict(metric_calls[-1].args[1]) if metric_calls else {}
    return {
        "phases": [phase.value for phase in store.phases],
        "rounds": rounds,
        "shocks": [[c.args[1], c.kwargs["injected_before_round"]] for c in graph.write_shock_event.await_args_list],
        "metrics": {k: v for k, v in sorted(metrics.items()) if not k.endswith("_seconds")},
        "narratives_written": sum(len(c.args[1]) for c in graph.write_decision_narratives.await_args_list),
    }
