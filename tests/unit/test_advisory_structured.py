"""Advisory: LLM-facing output, server-side assembly, backend stats (docs/DECISIONS.md#adr-advisory-pipeline)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaswarm.advisory.types import (
    AdvisoryItem,
    AdvisoryLLMItem,
    AdvisoryLLMOutput,
    AdvisoryReport,
    AdvisoryStats,
)


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
