"""Pins the GraphStateManager facade across the graph package split.

1. The public API (names and signatures) is a golden; the split must not change it.
2. Only the facade's helpers open Neo4j sessions (docs/DECISIONS.md#p4-d-07).
3. With Neo4j down, every facade method raises Neo4jUnavailableError, never a raw
   driver error (docs/DECISIONS.md#adr-neo4j-schema).
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from neo4j.exceptions import ServiceUnavailable

from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.graph import GraphStateManager
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.types import AgentPersona, SeedEvent
from tests.support.golden import assert_golden

SRC = Path(__file__).resolve().parents[1] / "src" / "alphaswarm"
CYCLE_ID = "00000000-0000-4000-8000-000000000015"
RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SESSION_OWNERS = frozenset({"_read", "_write", "ensure_schema"})


def _graph_sources() -> list[Path]:
    package = SRC / "graph"
    return sorted(package.glob("*.py")) if package.is_dir() else [SRC / "graph.py"]


def _public_api() -> dict[str, str]:
    api = {"__init__": str(inspect.signature(GraphStateManager.__init__))}
    for name, member in inspect.getmembers(GraphStateManager, inspect.isfunction):
        if not name.startswith("_"):
            api[name] = str(inspect.signature(member))
    return api


def test_public_api_is_pinned() -> None:
    assert_golden("graph/facade_api.json", _public_api(), normalize_values=False)


def _session_calls(path: Path) -> list[tuple[str, str]]:
    """(enclosing function, file:line) for every `.session(` call in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    calls: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "session":
            enclosing = [f for f in functions if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)]
            owner = max(enclosing, key=lambda f: f.lineno).name if enclosing else "<module>"
            calls.append((owner, f"{path.name}:{node.lineno}"))
    return calls


def test_only_the_facade_helpers_open_sessions() -> None:
    calls = [call for path in _graph_sources() for call in _session_calls(path)]
    assert calls, "expected _read/_write/ensure_schema to open sessions"
    assert {owner for owner, _ in calls} <= SESSION_OWNERS, calls
    assert {where.split(":")[0] for _, where in calls} <= {"graph.py", "manager.py"}, calls


class _DownSession:
    async def __aenter__(self) -> _DownSession:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute_read(self, *args: object, **kwargs: object) -> object:
        raise ServiceUnavailable("simulated outage")

    async def execute_write(self, *args: object, **kwargs: object) -> object:
        raise ServiceUnavailable("simulated outage")

    async def run(self, *args: object, **kwargs: object) -> object:
        raise ServiceUnavailable("simulated outage")


class _DownDriver:
    def session(self, **kwargs: object) -> _DownSession:
        return _DownSession()

    async def verify_connectivity(self) -> None:
        raise ServiceUnavailable("simulated outage")

    async def close(self) -> None:
        return None


def _one_persona() -> list[AgentPersona]:
    return generate_personas(load_bracket_configs())[:1]


Call = Callable[[GraphStateManager], Awaitable[object]]

OUTAGE_CALLS: dict[str, Call] = {
    "compute_influence_edges": lambda gm: gm.compute_influence_edges(CYCLE_ID, 2, 10),
    "create_cycle_with_seed_event": lambda gm: gm.create_cycle_with_seed_event(
        RUMOR,
        SeedEvent(raw_rumor=RUMOR, entities=[], overall_sentiment=0.1),
        num_rounds=3,
    ),
    "cycle_exists": lambda gm: gm.cycle_exists(CYCLE_ID),
    "ensure_schema": lambda gm: gm.ensure_schema(),
    "read_agent_decisions": lambda gm: gm.read_agent_decisions(CYCLE_ID, "quants_01"),
    "read_agent_interview_context": lambda gm: gm.read_agent_interview_context("quants_01", CYCLE_ID),
    "read_bracket_narratives": lambda gm: gm.read_bracket_narratives(CYCLE_ID),
    "read_bracket_narratives_for_round": lambda gm: gm.read_bracket_narratives_for_round(CYCLE_ID, 1),
    "read_completed_cycles": lambda gm: gm.read_completed_cycles(),
    "read_consensus_summary": lambda gm: gm.read_consensus_summary(CYCLE_ID),
    "read_cycle_entities": lambda gm: gm.read_cycle_entities(CYCLE_ID),
    "read_cycle_seed": lambda gm: gm.read_cycle_seed(CYCLE_ID),
    "read_cycle_status": lambda gm: gm.read_cycle_status(CYCLE_ID),
    "read_decision_narrative": lambda gm: gm.read_decision_narrative(CYCLE_ID, "quants_01"),
    "read_entity_impact": lambda gm: gm.read_entity_impact(CYCLE_ID),
    "read_full_cycle_signals": lambda gm: gm.read_full_cycle_signals(CYCLE_ID),
    "read_influence_edges": lambda gm: gm.read_influence_edges(CYCLE_ID, 2),
    "read_influence_leaders": lambda gm: gm.read_influence_leaders(CYCLE_ID),
    "read_key_dissenters": lambda gm: gm.read_key_dissenters(CYCLE_ID),
    "read_latest_cycle_id": lambda gm: gm.read_latest_cycle_id(),
    "read_rationale_entries_for_round": lambda gm: gm.read_rationale_entries_for_round(CYCLE_ID, 1),
    "read_round_timeline": lambda gm: gm.read_round_timeline(CYCLE_ID),
    "read_shock_event": lambda gm: gm.read_shock_event(CYCLE_ID),
    "read_shock_impact": lambda gm: gm.read_shock_impact(CYCLE_ID),
    "read_signal_flips": lambda gm: gm.read_signal_flips(CYCLE_ID),
    "remove_legacy_properties": lambda gm: gm.remove_legacy_properties(),
    "seed_agents": lambda gm: gm.seed_agents(_one_persona()),
    "set_cycle_status": lambda gm: gm.set_cycle_status(CYCLE_ID, "failed", error_code="internal_error"),
    "verify_connectivity": lambda gm: gm.verify_connectivity(),
    "write_cycle_metrics": lambda gm: gm.write_cycle_metrics(CYCLE_ID, {"num_rounds": 3}),
    "write_decision_narrative": lambda gm: gm.write_decision_narrative(
        CYCLE_ID, "quants_01", "Fictional arc for a fictional cycle."
    ),
    "write_shock_event": lambda gm: gm.write_shock_event(CYCLE_ID, "Fictional regulator opens a review", 2),
}
# close has no I/O to map; persist_round needs aligned episodes and entity
# matches and its error mapping is covered by tests/neo4j/test_persist_round.py.
NOT_COVERED = frozenset({"close", "persist_round"})


def test_outage_table_covers_the_whole_api() -> None:
    public = {name for name in _public_api() if name != "__init__"}
    assert public - NOT_COVERED == set(OUTAGE_CALLS)


@pytest.mark.parametrize("method", sorted(OUTAGE_CALLS))
async def test_every_facade_method_maps_a_driver_outage(method: str) -> None:
    gm = GraphStateManager(_DownDriver(), _one_persona())
    with pytest.raises(Neo4jUnavailableError) as exc_info:
        await OUTAGE_CALLS[method](gm)
    assert exc_info.value.op
