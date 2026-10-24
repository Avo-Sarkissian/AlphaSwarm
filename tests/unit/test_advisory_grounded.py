"""Advisory items grounded in swarm evidence (docs/DECISIONS.md#adr-grounded-advisory)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from structlog.testing import capture_logs

from alphaswarm.advisory.engine import assemble_advisory_report, synthesize
from alphaswarm.advisory.evidence import SwarmEvidence
from alphaswarm.advisory.types import AdvisoryLLMItem, AdvisoryLLMOutput, AdvisoryReport
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

AS_OF = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
PORTFOLIO = PortfolioSnapshot(
    holdings=(
        Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),
        Holding(ticker="QQQX", qty=Decimal("3.5"), cost_basis=Decimal("617.28")),
        Holding(ticker="XQZW", qty=Decimal("1"), cost_basis=Decimal("100.00")),
    ),
    as_of=AS_OF,
    account_number_hash="cafebabe",
)


def _evidence(ticker: str, support: int, signal: str | None, confidence: float | None) -> SwarmEvidence:
    return SwarmEvidence(
        ticker=ticker,
        support=support,
        buy=support,
        sell=0,
        hold=0,
        net_score=0.6 if signal else 0.0,
        signal=signal,
        confidence=confidence,
        sentiment=0.35,  # type: ignore[arg-type]
        agent_ids=tuple(f"quants_{i:02d}" for i in range(1, support + 1)),
    )


def _llm(*items: tuple[str, str, float]) -> AdvisoryLLMOutput:
    return AdvisoryLLMOutput(
        portfolio_outlook="Fictional outlook.",
        items=[AdvisoryLLMItem(ticker=t, signal=s, confidence=c, rationale=f"LLM view on {t}") for t, s, c in items],  # type: ignore[arg-type]
    )


def _items(report: AdvisoryReport) -> dict[str, Any]:
    return {item.ticker: item for item in report.items}


def test_swarm_signal_is_displayed_and_the_llm_signal_kept() -> None:
    report = assemble_advisory_report(
        cycle_id="c1",
        portfolio=PORTFOLIO,
        llm=_llm(("ZZZT", "SELL", 0.7)),
        evidence={"ZZZT": _evidence("ZZZT", 4, "BUY", 0.62)},
        generated_at=AS_OF,
    )
    item = _items(report)["ZZZT"]
    assert (item.consensus_signal, item.confidence) == ("BUY", 0.62)
    assert (item.swarm_signal, item.llm_signal, item.divergent) == ("BUY", "SELL", True)
    assert item.swarm_support == 4 and item.swarm_sentiment == 0.35
    assert item.evidence_agent_ids == ("quants_01", "quants_02", "quants_03", "quants_04")
    assert item.rationale_summary == "LLM view on ZZZT"
    assert item.cost_basis_exposure == Decimal("1234.56")
    assert report.stats is not None
    assert (report.stats.divergent_count, report.stats.evidence_count) == (1, 1)


def test_thin_evidence_never_overrides_or_flags_divergence() -> None:
    report = assemble_advisory_report(
        cycle_id="c1",
        portfolio=PORTFOLIO,
        llm=_llm(("ZZZT", "BUY", 0.8)),
        evidence={"ZZZT": _evidence("ZZZT", 2, None, None)},
        generated_at=AS_OF,
    )
    item = _items(report)["ZZZT"]
    assert (item.consensus_signal, item.confidence, item.source) == ("BUY", 0.8, "swarm")
    assert item.swarm_signal is None and item.swarm_support == 2
    assert item.llm_signal == "BUY" and item.divergent is False


def test_evidence_only_holding_is_a_conviction_item() -> None:
    report = assemble_advisory_report(
        cycle_id="c1",
        portfolio=PORTFOLIO,
        llm=_llm(),
        evidence={"QQQX": _evidence("QQQX", 3, "HOLD", 0.5)},
        generated_at=AS_OF,
    )
    item = _items(report)["QQQX"]
    assert (item.consensus_signal, item.source, item.llm_signal, item.divergent) == ("HOLD", "swarm", None, False)
    assert item.rationale_summary.startswith("Swarm evidence: 3 final-round agents referenced this company")


def test_no_evidence_and_no_llm_item_is_a_placeholder() -> None:
    report = assemble_advisory_report(cycle_id="c1", portfolio=PORTFOLIO, llm=_llm(), generated_at=AS_OF)
    item = _items(report)["XQZW"]
    assert (item.consensus_signal, item.confidence, item.source) == ("HOLD", 0.30, "placeholder")
    assert item.swarm_support == 0 and item.swarm_signal is None and item.llm_signal is None


def test_legacy_file_maps_position_exposure() -> None:
    legacy = {
        "cycle_id": "c1",
        "generated_at": "2026-10-03T12:00:00+00:00",
        "portfolio_outlook": "Flat.",
        "items": [
            {
                "ticker": "ZZZT",
                "consensus_signal": "HOLD",
                "confidence": 0.3,
                "rationale_summary": "x",
                "position_exposure": "1234.56",
            }
        ],
        "total_holdings": 1,
        "affected_holdings": 0,
    }
    report = AdvisoryReport.model_validate(legacy)
    item = report.items[0]
    assert item.cost_basis_exposure == Decimal("1234.56")
    assert (item.swarm_support, item.swarm_signal, item.llm_signal, item.divergent) == (0, None, None, False)
    dumped = json.loads(report.model_dump_json())
    assert "position_exposure" not in dumped["items"][0]
    assert dumped["items"][0]["evidence_agent_ids"] == []


class _GroundedGraph:
    """Fake graph: three agents reference ZZZT Holdings (resolved ticker ZZZT)."""

    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 3, "sell_count": 0, "hold_count": 0, "parse_error_count": 0, "total": 3}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."

    async def read_final_round_decisions(self, cycle_id: str) -> list[dict[str, Any]]:
        entity = {"name": "ZZZT Holdings", "type": "company", "ticker": "ZZZT"}
        return [
            {
                "agent_id": f"sell_side_0{i}",
                "bracket": "sell_side",
                "reach": 0.75,
                "signal": "buy",
                "confidence": 0.8,
                "sentiment": 0.5,
                "entities": [entity],
            }
            for i in range(1, 4)
        ]


async def test_synthesize_grounds_the_prompt_and_the_items() -> None:
    reply = json.dumps(
        {
            "portfolio_outlook": "Fictional.",
            "items": [{"ticker": "ZZZT", "signal": "SELL", "confidence": 0.7, "rationale": "Deal risk dominates."}],
        }
    )
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=reply, model="fake-orch")],
    )
    with capture_logs() as logs:
        report = await synthesize(
            cycle_id="c1",
            portfolio=PORTFOLIO,
            graph_manager=_GroundedGraph(),  # type: ignore[arg-type]
            provider=provider,
        )
    user = provider.calls[0]["messages"][1]["content"]
    assert "swarm_consensus (final round): BUY" in user
    # Per-holding evidence is joined after the call and never sent to the model
    # (docs/DECISIONS.md#adr-holdings-isolation).
    assert "sell_side_01" not in user and "swarm signal" not in user
    item = _items(report)["ZZZT"]
    assert (item.consensus_signal, item.llm_signal, item.divergent) == ("BUY", "SELL", True)
    assert "evidence_agent_ids" in report.model_dump_json()
    done = next(e for e in logs if e["event"] == "advisory_synthesize_complete")
    assert (done["evidence_items"], done["divergent_items"]) == (1, 1)
    held = {"ZZZT", "QQQX", "XQZW"}
    assert not [
        e for e in logs if e["event"] != "advisory_hallucinated_tickers_dropped" and held & {str(v) for v in e.values()}
    ]
