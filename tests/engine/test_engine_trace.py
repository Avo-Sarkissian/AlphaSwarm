"""Engine traces pinned before the module-split refactors.

The scenario goldens (tests/golden/scenarios/<name>.json) pin outcomes. These traces
pin how the engine reaches them: every state-sink mutation in order, every graph call
in order, the exact prompts of three sample agents per round, a digest over all
prompts, and every orchestrator message. Worker and governor lifecycle calls (model
load and unload, governor sessions: docs/DECISIONS.md#p7-d-05 and #p7-d-06) are left
out on purpose, so a change to that lifecycle leaves these files alone. Structural
refactors keep these files byte-identical; a deliberate change to prompts or state
calls regenerates them in the same commit
(UPDATE_GOLDEN=1 uv run pytest -q tests/engine/test_engine_trace.py).
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from unittest.mock import MagicMock

import pytest

from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import Fundamentals, MarketSlice, NewsSlice
from alphaswarm.types import AgentPersona
from tests.engine.scenario import SCENARIO_MODIFIERS_JSON, SCENARIO_SHOCK_TEXT, RecordingStateStore, RunScenario
from tests.inference.fakes import ScriptedProvider
from tests.support.golden import assert_golden

ORDERED_STATE_CALLS = frozenset(
    {
        "set_phase",
        "set_round",
        "set_num_rounds",
        "set_cycle",
        "begin_run",
        "bump_edges_version",
        "record_applied_shock",
        "set_bracket_summaries",
    }
)
COUNTED_STATE_CALLS = frozenset({"update_agent_state", "push_rationale", "update_tps"})
SECOND_SHOCK_TEXT = "ZZZT Holdings raises its offer for QQQX Robotics to $4.6B in cash."
HEADLINE = "ZZZT Holdings confirms a strategic review"
# Only ticker-shaped entity names reach MarketDataProvider.get_prices, so the market
# trace's seed names one ticker next to a company name and a sector.
TICKER = "QQQX"
TICKER_HEADLINE = "QQQX Robotics board weighs the ZZZT offer"
MARKET_SEED_JSON = json.dumps(
    {
        "entities": [
            {"name": "ZZZT Holdings", "type": "company", "relevance": 0.95, "sentiment": 0.6},
            {"name": TICKER, "type": "company", "relevance": 0.9, "sentiment": 0.7},
            {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.4},
        ],
        "overall_sentiment": 0.55,
    }
)
FETCHED_AT = datetime(2026, 10, 3, tzinfo=UTC)


def _plain(value: object) -> object:
    """JSON-friendly form of one call argument."""
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return type(value).__name__


class TracingStateStore(RecordingStateStore):
    """RecordingStateStore that also logs every engine-facing call."""

    def __init__(self) -> None:
        super().__init__()
        self.trace: list[list[object]] = []
        self.counts: Counter[str] = Counter()

    def __getattribute__(self, name: str) -> Any:
        attr = super().__getattribute__(name)
        if name not in ORDERED_STATE_CALLS and name not in COUNTED_STATE_CALLS:
            return attr
        note = super().__getattribute__("_note")
        if inspect.iscoroutinefunction(attr):

            async def _traced_async(*args: Any, **kwargs: Any) -> Any:
                note(name, args, kwargs)
                return await attr(*args, **kwargs)

            return _traced_async

        def _traced(*args: Any, **kwargs: Any) -> Any:
            note(name, args, kwargs)
            return attr(*args, **kwargs)

        return _traced

    def _note(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        if name in COUNTED_STATE_CALLS:
            self.counts[name] += 1
            return
        values = [*args, *kwargs.values()]
        if name == "set_bracket_summaries":
            row: list[object] = [[s.bracket, s.buy_count, s.sell_count, s.hold_count, s.total] for s in values[0]]
        elif name == "begin_run":
            ids = list(values[0])
            row = [len(ids), ids[0] if ids else None, ids[-1] if ids else None]
        else:
            row = [_plain(v) for v in values]
        self.trace.append([name, *row])


def _graph_calls(graph: MagicMock) -> list[list[object]]:
    """Every top-level GraphStateManager call in order, without random decision ids."""
    rows: list[list[object]] = []
    for name, args, kwargs in graph.mock_calls:
        if not name or "." in name:
            continue
        if name == "persist_round":
            rows.append(
                [
                    name,
                    args[1],
                    len(args[2]),
                    len(kwargs["episodes"]),
                    len(kwargs["entity_matches"]),
                    sorted(kwargs),
                ]
            )
        elif name == "write_cycle_metrics":
            rows.append([name, sorted(args[1])])
        elif name == "create_cycle_with_seed_event":
            rows.append([name, args[0], kwargs.get("num_rounds"), kwargs.get("prompt_template_hash"), sorted(kwargs)])
        elif name == "write_decision_narratives":
            rows.append([name, len(list(args[-1]))])
        else:
            rows.append([name, *(_plain(a) for a in args), {key: _plain(val) for key, val in sorted(kwargs.items())}])
    return rows


def _prompts(worker: ScriptedProvider, personas: Sequence[AgentPersona]) -> dict[str, object]:
    calls = sorted(worker.calls_for("decision"), key=lambda c: (c.round_num or 0, c.agent_id or ""))
    payload = [[c.round_num, c.agent_id, c.messages] for c in calls]
    sample_ids = {personas[0].id, personas[len(personas) // 2].id, personas[-1].id}
    return {
        "decision_calls": len(calls),
        "digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "samples": {f"r{c.round_num}:{c.agent_id}": c.messages for c in calls if c.agent_id in sample_ids},
    }


def _trace(
    *,
    store: TracingStateStore,
    worker: ScriptedProvider,
    orchestrator: ScriptedProvider,
    graph: MagicMock,
    personas: Sequence[AgentPersona],
) -> dict[str, object]:
    return {
        "state_calls": store.trace,
        "state_call_counts": dict(sorted(store.counts.items())),
        "graph_calls": _graph_calls(graph),
        "prompts": _prompts(worker, personas),
        "orchestrator_messages": [c.messages for c in orchestrator.calls_for("orchestrator")],
        "narrative_calls": len(worker.calls_for("narrative")),
    }


@pytest.fixture
def scenario_store() -> TracingStateStore:
    """Overrides tests/engine/conftest.py so every scenario here records a trace."""
    return TracingStateStore()


@pytest.fixture
def check_trace(
    scenario_store: TracingStateStore,
    scripted_worker: ScriptedProvider,
    scripted_orchestrator: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> Any:
    def _check(golden: str, *, orchestrator: ScriptedProvider | None = None) -> None:
        assert_golden(
            f"scenarios/{golden}",
            _trace(
                store=scenario_store,
                worker=scripted_worker,
                orchestrator=orchestrator if orchestrator is not None else scripted_orchestrator,
                graph=fake_graph,
                personas=all_personas,
            ),
        )

    return _check


async def test_trace_three_rounds(run_scenario: RunScenario, check_trace: Any) -> None:
    await run_scenario()
    check_trace("trace_three_rounds.json")


async def test_trace_two_rounds(run_scenario: RunScenario, check_trace: Any) -> None:
    await run_scenario(num_rounds=2)
    check_trace("trace_two_rounds.json")


async def test_trace_two_shocks(run_scenario: RunScenario, check_trace: Any) -> None:
    await run_scenario(shocks={2: SCENARIO_SHOCK_TEXT, 3: SECOND_SHOCK_TEXT})
    check_trace("trace_two_shocks.json")


async def test_trace_market_context(
    run_scenario: RunScenario, check_trace: Any, all_personas: list[AgentPersona]
) -> None:
    """Round 1's market block: price, fundamentals and a headline for the ticker, a
    headline for the company name, and no block for the sector, which has no data."""
    orchestrator = ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=all_personas,
        orchestrator_script=[MARKET_SEED_JSON, SCENARIO_MODIFIERS_JSON],
    )
    market = FakeMarketDataProvider(
        {
            TICKER: MarketSlice(
                ticker=TICKER,
                price=Decimal("41.27"),
                volume=1_250_000,
                fundamentals=Fundamentals(
                    pe_ratio=Decimal("18.4"), eps=Decimal("2.24"), market_cap=Decimal("4200000000")
                ),
                fetched_at=FETCHED_AT,
                source="fake_market_data",
            )
        }
    )
    news = FakeNewsProvider(
        {
            "ZZZT Holdings": NewsSlice(
                entity="ZZZT Holdings",
                headlines=(HEADLINE,),
                fetched_at=FETCHED_AT,
                source="fake_news",
            ),
            TICKER: NewsSlice(entity=TICKER, headlines=(TICKER_HEADLINE,), fetched_at=FETCHED_AT, source="fake_news"),
        }
    )
    await run_scenario(orchestrator=orchestrator, market_provider=market, news_provider=news)
    check_trace("trace_market_context.json", orchestrator=orchestrator)
