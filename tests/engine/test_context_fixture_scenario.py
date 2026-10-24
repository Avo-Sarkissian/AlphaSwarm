"""A fixture's block reaches Round 1 prompts and the run manifest (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from alphaswarm.context_formatter import format_market_context
from alphaswarm.ingestion.fixture import build_fixture_packet
from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import MarketSlice, NewsSlice
from alphaswarm.settings import SimulationSettings

PACKET = build_fixture_packet(
    event_id="evt-001",
    as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
    ticker="ZZZT",
    close=Decimal("123.45"),
    volume=1_000_000,
    headlines=("ZZZT Holdings names a new chief executive (fictional)",),
)


def _text(call: Any) -> str:
    return "\n".join(str(message["content"]) for message in call.messages)


def _round1(worker: Any) -> list[Any]:
    return [c for c in worker.calls_for("decision") if c.round_num == 1]


class _RecordingMarket(FakeMarketDataProvider):
    """Records every fetch; a point-in-time run must make none."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        self.calls.append("get_prices")
        return await super().get_prices(tickers)

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        self.calls.append("get_fundamentals")
        return await super().get_fundamentals(tickers)

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        self.calls.append("get_volume")
        return await super().get_volume(tickers)


class _RecordingNews(FakeNewsProvider):
    """Records every fetch; a point-in-time run must make none."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def get_headlines(
        self,
        entities: list[str],
        *,
        max_age_hours: int = 72,
        tickers: Mapping[str, str] | None = None,
    ) -> dict[str, NewsSlice]:
        self.calls.append("get_headlines")
        return await super().get_headlines(entities, max_age_hours=max_age_hours, tickers=tickers)


async def test_round1_prompts_carry_the_fixture_block(run_scenario: Any, scripted_worker: Any) -> None:
    await run_scenario(num_rounds=2, context_fixture=PACKET)
    round1 = _round1(scripted_worker)
    assert len(round1) == 100
    assert all("== ZZZT ==" in _text(c) and "Price: $123.45" in _text(c) for c in round1)


async def test_the_fixture_wins_over_supplied_providers(run_scenario: Any, scripted_worker: Any) -> None:
    market, news = _RecordingMarket(), _RecordingNews()
    await run_scenario(num_rounds=2, context_fixture=PACKET, market_provider=market, news_provider=news)
    assert market.calls == [] and news.calls == []
    round1 = _round1(scripted_worker)
    assert len(round1) == 100
    assert all("Price: $123.45" in _text(c) for c in round1)


async def test_no_fixture_and_no_providers_send_no_block(run_scenario: Any, scripted_worker: Any) -> None:
    await run_scenario(num_rounds=2)
    assert not any("Price: $123.45" in _text(c) for c in _round1(scripted_worker))


async def test_manifest_records_the_fixture_block(run_scenario: Any, fake_graph: Any) -> None:
    await run_scenario(num_rounds=2, context_fixture=PACKET)
    call = fake_graph.write_run_manifest.await_args
    manifest = call.kwargs["manifest"] if "manifest" in call.kwargs else call.args[1]
    assert manifest.market_context == format_market_context(PACKET)


async def test_private_headlines_draw_from_the_fixture(
    run_scenario: Any, scripted_worker: Any, scenario_settings: Any
) -> None:
    packet = build_fixture_packet(
        event_id="evt-002",
        as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
        ticker="ZZZT",
        close=Decimal("123.45"),
        volume=1_000_000,
        headlines=tuple(f"Fictional headline {i} about ZZZT Holdings" for i in range(1, 7)),
    )
    scenario_settings.simulation = SimulationSettings(private_headlines=True, sim_seed=101)
    await run_scenario(num_rounds=2, context_fixture=packet)
    seen: list[tuple[str, ...]] = []
    for call in _round1(scripted_worker):
        lines = sorted(line.strip() for line in _text(call).splitlines() if "Fictional headline" in line)
        assert lines, "every agent sees at least one fixture headline"
        seen.append(tuple(lines))
    assert len(set(seen)) > 1, "private subsets differ between agents"
