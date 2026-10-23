"""The advisory prompt carries one entry per held ticker and nothing else about a position.

Lots are aggregated per ticker, quantity and cost basis never reach the LLM, and
the worked example uses a placeholder ticker (docs/DECISIONS.md#p41-d-05).
Tickers are reserved fictional symbols and every value is made up.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphaswarm.advisory import synthesize
from alphaswarm.advisory.prompt import _WORKED_EXAMPLE
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

_EMPTY_ADVISORY = json.dumps(
    {
        "cycle_id": "c1",
        "generated_at": "2026-10-03T12:00:00+00:00",
        "portfolio_outlook": "Flat.",
        "items": [],
        "total_holdings": 0,
        "affected_holdings": 0,
    }
)
_ENTRY_KEYS = {
    "ticker",
    "sector",
    "region_exposure",
    "supply_chain_sensitivity",
    "macro_beta",
    "relevance_score",
}
# Distinctive fictional position values; none may appear anywhere in the prompt.
_POSITION_VALUES = ("12.3456", "1234.56", "40.125", "860.43", "3.875", "345.67", "1580.23")


class _Graph:
    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 1, "sell_count": 0, "hold_count": 0, "total": 1}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(
            Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),
            Holding(ticker="QQQX", qty=Decimal("40.125"), cost_basis=Decimal("860.43")),
            Holding(ticker="ZZZT", qty=Decimal("3.875"), cost_basis=Decimal("345.67")),
        ),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


async def _prompt_messages() -> list[dict[str, str]]:
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[InferenceResult(content=_EMPTY_ADVISORY, model="test-orch")],
    )
    await synthesize(
        cycle_id="c1",
        portfolio=_portfolio(),
        graph_manager=_Graph(),  # type: ignore[arg-type]
        provider=provider,
    )
    messages: list[dict[str, str]] = provider.calls[0]["messages"]
    return messages


def _portfolio_entries(user_content: str) -> list[dict[str, str]]:
    line = next(text for text in user_content.splitlines() if text.startswith("[{"))
    entries: list[dict[str, str]] = json.loads(line)
    return entries


async def test_each_held_ticker_appears_once() -> None:
    entries = _portfolio_entries((await _prompt_messages())[1]["content"])
    assert sorted(entry["ticker"] for entry in entries) == ["QQQX", "ZZZT"]


async def test_entries_carry_only_the_ticker_and_sector_tags() -> None:
    entries = _portfolio_entries((await _prompt_messages())[1]["content"])
    assert len(entries) == 2
    assert all(set(entry) == _ENTRY_KEYS for entry in entries)


async def test_no_quantity_or_cost_basis_reaches_the_prompt() -> None:
    joined = "\n".join(message["content"] for message in await _prompt_messages())
    for value in _POSITION_VALUES:
        assert value not in joined


async def test_schema_never_asks_for_exposure_or_cost_basis() -> None:
    system = (await _prompt_messages())[0]["content"]
    assert "position_exposure" not in system
    assert "cost_basis" not in system


def test_worked_example_uses_a_placeholder_ticker() -> None:
    assert '"ticker": "ZZZT"' in _WORKED_EXAMPLE
    assert "position_exposure" not in _WORKED_EXAMPLE
