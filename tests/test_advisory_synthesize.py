"""Advisory relevance ranking over the data-driven sector map.

Every ticker and value here is fictional; the owner's curated map lives in the
gitignored data/sector_map.local.json (docs/DECISIONS.md#adr-holdings-isolation).
These tests replace the ones that pinned the owner's ticker list and its size.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st

from alphaswarm.advisory import engine, synthesize
from alphaswarm.advisory.prompt import build_advisory_prompt
from alphaswarm.advisory.sector_map import EMPTY_SECTOR_MAP, SectorMap, load_sector_map
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

EXAMPLE: SectorMap = load_sector_map(Path("/nonexistent/sector_map.local.json"))
SEED = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
_EMPTY_ADVISORY = json.dumps(
    {
        "cycle_id": "c1",
        "generated_at": "2026-10-03T12:00:00+00:00",
        "portfolio_outlook": "Flat.",
        "items": [],
        "total_holdings": 2,
        "affected_holdings": 0,
    }
)


class _Graph:
    def __init__(self, entity_impact: list[dict[str, Any]], seed: str = "") -> None:
        self._entity_impact = entity_impact
        self._seed = seed

    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 1, "sell_count": 0, "hold_count": 0, "total": 1}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return self._entity_impact

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return self._seed


def _portfolio(*tickers: str) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=tuple(Holding(ticker=t, qty=Decimal("1.5"), cost_basis=Decimal("100.25")) for t in tickers),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


async def _ranked_tickers(
    portfolio: PortfolioSnapshot,
    graph: _Graph,
    *,
    sector_map: SectorMap | None,
) -> list[str]:
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[InferenceResult(content=_EMPTY_ADVISORY, model="test-orch")],
    )
    await synthesize(
        cycle_id="c1",
        portfolio=portfolio,
        graph_manager=graph,  # type: ignore[arg-type]
        provider=provider,
        sector_map=sector_map,
    )
    user = provider.calls[0]["messages"][1]["content"]
    line = next(text for text in user.splitlines() if text.startswith("[{"))
    return [entry["ticker"] for entry in json.loads(line)]


def test_example_map_covers_the_fictional_tickers() -> None:
    assert EXAMPLE.source == "example"
    assert sorted(EXAMPLE.entries) == sorted(["ZZZT", "QQQX", "XQZW", "ZQXY", "QZZX"])


def test_enrich_attaches_sector_fields() -> None:
    [row] = engine._enrich_holdings([{"ticker": "ZZZT"}], {}, "", sector_map=EXAMPLE)
    assert row["sector"] == "Industrial Automation"
    assert float(row["macro_beta"]) == 0.9
    assert row["relevance_score"] == "0.0000"


def test_entity_impact_drives_ranking() -> None:
    ranked = engine._enrich_holdings(
        [{"ticker": "ZZZT"}, {"ticker": "ZQXY"}],
        {"ZQXY": 0.9},
        "an unrelated rumor",
        sector_map=EXAMPLE,
    )
    assert [row["ticker"] for row in ranked] == ["ZQXY", "ZZZT"]
    assert float(ranked[0]["relevance_score"]) == 0.36  # |0.9| x |0.4|


def test_seed_matches_the_sector_label_as_a_phrase() -> None:
    ranked = engine._enrich_holdings(
        [{"ticker": "QQQX"}, {"ticker": "ZZZT"}],
        {},
        "industrial automation orders surge",
        sector_map=EXAMPLE,
    )
    assert ranked[0]["ticker"] == "ZZZT"
    assert float(ranked[0]["relevance_score"]) == 0.5
    assert float(ranked[1]["relevance_score"]) == 0.0


def test_ticker_match_needs_a_whole_word() -> None:
    [row] = engine._enrich_holdings([{"ticker": "QZZX"}], {}, "QZZXY rallied", sector_map=EXAMPLE)
    assert float(row["relevance_score"]) == 0.0


def test_unknown_sector_never_matches_unknown_sources() -> None:
    [row] = engine._enrich_holdings(
        [{"ticker": "ZZZT"}],
        {},
        "unknown sources say the deal is close",
        sector_map=EMPTY_SECTOR_MAP,
    )
    assert row["sector"] == "unknown"
    assert float(row["relevance_score"]) == 0.0


@given(st.text(max_size=200))
def test_unknown_sector_only_matches_its_ticker(seed: str) -> None:
    assume(not re.search(r"\bzzzt\b", seed, re.IGNORECASE))
    [row] = engine._enrich_holdings([{"ticker": "ZZZT"}], {}, seed, sector_map=EMPTY_SECTOR_MAP)
    assert float(row["relevance_score"]) == 0.0


@given(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False), st.text(max_size=120))
def test_relevance_is_bounded_and_sorted(impact: float, seed: str) -> None:
    rows = engine._enrich_holdings(
        [{"ticker": t} for t in sorted(EXAMPLE.entries)],
        {"ZZZT": impact},
        seed,
        sector_map=EXAMPLE,
    )
    scores = [float(row["relevance_score"]) for row in rows]
    assert all(0.0 <= score <= 1.5 for score in scores)
    assert scores == sorted(scores, reverse=True)


async def test_aliases_from_the_injected_map_rank_the_holding() -> None:
    graph = _Graph([{"entity_name": "QQQX Robotics", "avg_sentiment": 0.8}])
    assert await _ranked_tickers(_portfolio("ZZZT", "QQQX"), graph, sector_map=EXAMPLE) == [
        "QQQX",
        "ZZZT",
    ]


async def test_without_a_map_aliases_do_not_resolve() -> None:
    graph = _Graph([{"entity_name": "QQQX Robotics", "avg_sentiment": 0.8}])
    # Neither holding scores, so the order is first-seen.
    assert await _ranked_tickers(_portfolio("ZZZT", "QQQX"), graph, sector_map=None) == [
        "ZZZT",
        "QQQX",
    ]


async def test_a_held_ticker_resolves_without_a_map() -> None:
    graph = _Graph([{"entity_name": "qqqx", "avg_sentiment": -0.8}])
    assert await _ranked_tickers(_portfolio("ZZZT", "QQQX"), graph, sector_map=None) == [
        "QQQX",
        "ZZZT",
    ]


def test_prompt_instructs_conviction_items_only() -> None:
    messages = build_advisory_prompt(
        cycle_id="c1",
        seed_rumor=SEED,
        bracket_summary={},
        timeline=[],
        narratives=[],
        entity_impact=[],
        top_holdings=[{"ticker": "ZZZT", "sector": "Industrial Automation"}],
    )
    full = " ".join(message["content"] for message in messages)
    assert "EMIT CONVICTION ITEMS ONLY" in full
    assert "engine pads" in full.lower()
