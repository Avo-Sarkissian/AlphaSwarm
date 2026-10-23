"""Advisory: LLM-facing output, server-side assembly, backend stats (docs/DECISIONS.md#adr-advisory-pipeline)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

import alphaswarm.advisory.engine as engine_module
from alphaswarm.advisory.engine import (
    ADVISORY_TEMPERATURE,
    advisory_llm_schema,
    assemble_advisory_report,
    synthesize,
)
from alphaswarm.advisory.prompt import build_advisory_prompt
from alphaswarm.advisory.types import (
    AdvisoryItem,
    AdvisoryLLMItem,
    AdvisoryLLMOutput,
    AdvisoryReport,
    AdvisoryStats,
)
from alphaswarm.errors import StructuredOutputError
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider, ScriptedProvider


def _item(ticker: str, signal: str, confidence: float, source: str = "swarm") -> AdvisoryItem:
    return AdvisoryItem(
        ticker=ticker,
        consensus_signal=signal,  # type: ignore[arg-type]
        confidence=confidence,
        rationale_summary="Fictional rationale.",
        position_exposure=Decimal("1234.56"),
        source=source,  # type: ignore[arg-type]
    )


def test_llm_item_normalises_near_miss_output() -> None:
    item = AdvisoryLLMItem.model_validate(
        {
            "ticker": " zzzt ",
            "signal": "buy",
            "confidence": 85,
            "rationale": "Deal  is\naccretive.",
            "risk": "  ",
            "upside": "Re-rating.",
            "position_exposure": "999",
        }
    )
    assert (item.ticker, item.signal, item.confidence) == ("ZZZT", "BUY", 0.85)
    assert item.rationale == "Deal is accretive."
    assert (item.risk, item.upside) == (None, "Re-rating.")


def test_llm_item_accepts_long_option_style_symbols() -> None:
    item = AdvisoryLLMItem.model_validate(
        {"ticker": "ZZZT  261218C00012500", "signal": "HOLD", "confidence": 0.5, "rationale": "Fictional option."}
    )
    assert item.ticker == "ZZZT  261218C00012500"


def test_llm_output_ignores_engine_fields_and_requires_outlook() -> None:
    out = AdvisoryLLMOutput.model_validate_json(
        json.dumps(
            {
                "cycle_id": "x",
                "generated_at": "t",
                "total_holdings": 9,
                "portfolio_outlook": "Constructive.",
                "items": [],
            }
        )
    )
    assert out.items == []
    with pytest.raises(ValidationError):
        AdvisoryLLMOutput.model_validate({"items": []})


def test_llm_schema_has_only_the_fields_the_engine_keeps() -> None:
    schema = AdvisoryLLMOutput.model_json_schema()
    assert set(schema["properties"]) == {"portfolio_outlook", "items"}
    item = schema["$defs"]["AdvisoryLLMItem"]["properties"]
    assert set(item) == {"ticker", "signal", "confidence", "rationale", "risk", "upside"}


def test_stats_cover_conviction_items_only() -> None:
    items = [
        _item("ZZZT", "BUY", 0.8),
        _item("QQQX", "BUY", 0.6),
        _item("XQZW", "SELL", 0.7),
        _item("ZQXY", "HOLD", 0.3, source="placeholder"),
        _item("QZZX", "HOLD", 0.3, source="placeholder"),
    ]
    stats = AdvisoryStats.from_items(items)
    assert (stats.conviction_count, stats.placeholder_count) == (3, 2)
    assert (stats.buy_count, stats.sell_count, stats.hold_count) == (2, 1, 0)
    assert stats.avg_confidence == pytest.approx(0.7)
    assert stats.dominant_signal == "BUY"
    assert stats.dominant_share == pytest.approx(2 / 3)


def test_stats_without_conviction_items() -> None:
    stats = AdvisoryStats.from_items([_item("ZQXY", "HOLD", 0.3, source="placeholder")])
    assert (stats.conviction_count, stats.avg_confidence, stats.dominant_signal, stats.dominant_share) == (
        0,
        None,
        None,
        None,
    )


def test_stats_tie_break_prefers_sell_then_buy() -> None:
    stats = AdvisoryStats.from_items([_item("ZZZT", "BUY", 0.5), _item("QQQX", "SELL", 0.5)])
    assert stats.dominant_signal == "SELL"


def test_legacy_advisory_payload_still_validates() -> None:
    legacy = {
        "cycle_id": "00000000-0000-4000-8000-0000000000a1",
        "generated_at": "2026-09-01T12:00:00+00:00",
        "portfolio_outlook": "Legacy outlook.",
        "items": [
            {
                "ticker": "ZZZT",
                "consensus_signal": "BUY",
                "confidence": 0.8,
                "rationale_summary": "Old.",
                "position_exposure": "1234.56",
            }
        ],
        "total_holdings": 1,
        "affected_holdings": 1,
    }
    report = AdvisoryReport.model_validate(legacy)
    assert report.items[0].source == "swarm"
    assert report.stats is None and report.holdings_as_of is None


def test_domain_models_still_forbid_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        AdvisoryItem.model_validate(
            {
                "ticker": "ZZZT",
                "consensus_signal": "BUY",
                "confidence": 0.5,
                "rationale_summary": "x",
                "position_exposure": "1",
                "surprise": True,
            }
        )
    report = AdvisoryReport(
        cycle_id="c",
        generated_at=datetime.now(UTC),
        portfolio_outlook="o",
        items=(),
        total_holdings=0,
        affected_holdings=0,
        stats=AdvisoryStats.from_items([]),
        holdings_as_of=datetime.now(UTC),
    )
    assert report.stats is not None


AS_OF = datetime(2026, 9, 30, 21, 0, tzinfo=UTC)


def _portfolio(*lots: tuple[str, str]) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=tuple(Holding(ticker=t, qty=Decimal("12.3456"), cost_basis=Decimal(c)) for t, c in lots),
        as_of=AS_OF,
        account_number_hash="cafebabe",
    )


class _Graph:
    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 52, "sell_count": 21, "hold_count": 24, "parse_error_count": 3, "total": 100}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


def _reply(*items: dict[str, Any]) -> str:
    return json.dumps({"portfolio_outlook": "Constructive on the deal names.", "items": list(items)})


ZZZT_BUY = {
    "ticker": "ZZZT",
    "signal": "BUY",
    "confidence": 0.82,
    "rationale": "Deal is accretive.",
    "risk": "Regulatory delay.",
    "upside": "Margin re-rating.",
}


def test_schema_restricts_tickers_to_the_prompt_list() -> None:
    schema = advisory_llm_schema(["QQQX", "ZZZT", "ZZZT"])
    ticker = schema["properties"]["items"]["items"]["properties"]["ticker"]
    assert ticker == {"type": "string", "enum": ["QQQX", "ZZZT"]}
    assert "$defs" not in schema
    with pytest.raises(ValueError):
        advisory_llm_schema([])


def test_prompt_asks_only_for_fields_the_engine_keeps() -> None:
    system = build_advisory_prompt(
        cycle_id="c1",
        seed_rumor="s",
        bracket_summary={},
        timeline=[],
        narratives=[],
        entity_impact=[],
        top_holdings=[{"ticker": "ZZZT", "sector": "industrials"}],
    )[0]["content"]
    for engine_field in (
        "cycle_id",
        "generated_at",
        "total_holdings",
        "affected_holdings",
        "position_exposure",
        "consensus_signal",
    ):
        assert engine_field not in system
    for kept in ('"portfolio_outlook"', '"signal"', '"rationale"', '"risk"', '"upside"'):
        assert kept in system
    assert "EMIT CONVICTION ITEMS ONLY" in system and "engine pads" in system.lower()


def test_assemble_pads_aggregates_ranks_and_counts() -> None:
    portfolio = _portfolio(("ZZZT", "1000"), ("ZZZT", "234.56"), ("QQQX", "500"), ("XQZW", "100"))
    llm = engine_module.AdvisoryLLMOutput.model_validate_json(
        _reply(ZZZT_BUY, {"ticker": "XQZW", "signal": "SELL", "confidence": 0.6, "rationale": "Weak."})
    )
    report = assemble_advisory_report(
        cycle_id="00000000-0000-4000-8000-0000000000a1",
        portfolio=portfolio,
        llm=llm,
        generated_at=AS_OF,
    )
    assert [(i.ticker, i.source) for i in report.items] == [
        ("ZZZT", "swarm"),
        ("XQZW", "swarm"),
        ("QQQX", "placeholder"),
    ]
    zzzt = report.items[0]
    assert zzzt.position_exposure == Decimal("1234.56")
    assert (zzzt.risk, zzzt.upside) == ("Regulatory delay.", "Margin re-rating.")
    assert report.items[2].consensus_signal == "HOLD" and report.items[2].confidence == 0.30
    assert (report.total_holdings, report.affected_holdings) == (3, 2)
    assert report.stats is not None and report.stats.placeholder_count == 1
    assert report.stats.avg_confidence == pytest.approx(0.71)
    assert report.holdings_as_of == AS_OF and report.generated_at == AS_OF


def test_hallucinated_ticker_dropped_and_logged_without_holdings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(engine_module, "log", fake_log)
    llm = engine_module.AdvisoryLLMOutput.model_validate_json(
        _reply(ZZZT_BUY, {"ticker": "QZZX", "signal": "BUY", "confidence": 0.9, "rationale": "Not held."})
    )
    report = assemble_advisory_report(cycle_id="c1", portfolio=_portfolio(("ZZZT", "1234.56")), llm=llm)
    assert [i.ticker for i in report.items] == ["ZZZT"]
    fake_log.warning.assert_called_once_with(
        "advisory_hallucinated_tickers_dropped",
        cycle_id="c1",
        count=1,
        tickers=["QZZX"],
    )
    logged = repr(fake_log.mock_calls)
    assert "1234.56" not in logged and "12.3456" not in logged


async def test_synthesize_one_call_low_temperature_enum_schema() -> None:
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=_reply(ZZZT_BUY), model="fake-orch")],
    )
    report = await synthesize(
        cycle_id="c1",
        portfolio=_portfolio(("ZZZT", "1234.56"), ("QQQX", "500")),
        graph_manager=_Graph(),  # type: ignore[arg-type]
        provider=provider,
    )
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["temperature"] == ADVISORY_TEMPERATURE == 0.2
    assert call["json_mode"] is False
    enum = call["response_schema"]["properties"]["items"]["items"]["properties"]["ticker"]["enum"]
    assert enum == ["QQQX", "ZZZT"]
    assert report.items[0].ticker == "ZZZT" and report.stats is not None


async def test_advisory_makes_zero_retries_on_the_scripted_happy_path(all_personas: list[Any]) -> None:
    provider = ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=all_personas,
        orchestrator_script=[_reply(ZZZT_BUY)],
    )
    await synthesize(
        cycle_id="c1",
        portfolio=_portfolio(("ZZZT", "1234.56")),
        graph_manager=_Graph(),  # type: ignore[arg-type]
        provider=provider,
    )
    assert len(provider.calls_for("orchestrator")) == 1


async def test_near_miss_reply_needs_no_retry() -> None:
    near_miss = (
        "```json\n"
        + json.dumps(
            {
                "portfolio_outlook": "Ok.",
                "items": [{"ticker": "zzzt", "signal": "buy", "confidence": 85, "rationale": "Accretive.", "extra": 1}],
            }
        )
        + "\n```"
    )
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=near_miss, model="fake-orch")],
    )
    report = await synthesize(
        cycle_id="c1",
        portfolio=_portfolio(("ZZZT", "1234.56")),
        graph_manager=_Graph(),  # type: ignore[arg-type]
        provider=provider,
    )
    assert len(provider.calls) == 1
    assert report.items[0].consensus_signal == "BUY" and report.items[0].confidence == 0.85


async def test_two_invalid_replies_fail_without_partial_file() -> None:
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content="prose", model="fake-orch")] * 2,
    )
    with pytest.raises(StructuredOutputError):
        await synthesize(
            cycle_id="c1",
            portfolio=_portfolio(("ZZZT", "1234.56")),
            graph_manager=_Graph(),  # type: ignore[arg-type]
            provider=provider,
        )
    assert len(provider.calls) == 2
