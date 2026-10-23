"""Unit tests for ADVIS-01 — alphaswarm.advisory.synthesize and boundary types.

pytest-socket --disable-socket is active project-wide; these tests use pure
Fakes with zero network access. Do NOT add @pytest.mark.enable_socket here.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import structlog
from pydantic import ValidationError

from alphaswarm.advisory import AdvisoryItem, AdvisoryReport, synthesize
from alphaswarm.errors import StructuredOutputError
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

# ---------------- Fakes ----------------------------------------------------


def _make_result(content: str) -> InferenceResult:
    """Build an InferenceResult with the given content string."""
    return InferenceResult(content=content, model="test-orch")


class FakeGraphManager:
    """Records call order; returns canned read values."""

    def __init__(
        self,
        consensus: dict[str, Any] | None = None,
        timeline: list[dict[str, Any]] | None = None,
        narratives: list[dict[str, Any]] | None = None,
        entity_impact: list[dict[str, Any]] | None = None,
        seed: str | None = None,
    ) -> None:
        self._consensus = consensus or {
            "buy_count": 50,
            "sell_count": 30,
            "hold_count": 20,
            "total": 100,
        }
        self._timeline = timeline or []
        self._narratives = narratives or []
        self._entity_impact = entity_impact or []
        self._seed = seed
        self.call_log: list[str] = []

    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        self.call_log.append("read_consensus_summary")
        return self._consensus

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        self.call_log.append("read_round_timeline")
        return self._timeline

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        self.call_log.append("read_bracket_narratives")
        return self._narratives

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        self.call_log.append("read_entity_impact")
        return self._entity_impact

    async def read_cycle_seed(self, cycle_id: str) -> str:
        self.call_log.append("read_cycle_seed")
        return self._seed or ""


def _valid_advisory_payload(items: list[dict[str, Any]], *, total: int = 5) -> str:
    """Build an AdvisoryLLMOutput reply; legacy item keys map onto the LLM keys."""
    llm_items = [
        {
            "ticker": item["ticker"],
            "signal": item.get("signal", item.get("consensus_signal")),
            "confidence": item["confidence"],
            "rationale": item.get("rationale", item.get("rationale_summary", "")) or "No rationale.",
        }
        for item in items
    ]
    return json.dumps({"portfolio_outlook": "Swarm is mildly bullish on AI infra names.", "items": llm_items})


def _portfolio(ticker_to_cost: dict[str, str]) -> PortfolioSnapshot:
    holdings = tuple(
        Holding(ticker=t, qty=Decimal("10"), cost_basis=Decimal(cost)) for t, cost in ticker_to_cost.items()
    )
    return PortfolioSnapshot(
        holdings=holdings,
        as_of=datetime.now(UTC),
        account_number_hash="deadbeef",
    )


# ---------------- Schema tests (41-01-01) ----------------------------------


def test_advisory_item_schema() -> None:
    # Valid minimal payload
    item = AdvisoryItem(
        ticker="ZZZT",
        consensus_signal="BUY",
        confidence=0.75,
        rationale_summary="ok",
        position_exposure=Decimal("100"),
    )
    assert item.ticker == "ZZZT"

    # Rejects unknown fields (extra='forbid')
    with pytest.raises(ValidationError):
        AdvisoryItem(
            ticker="ZZZT",
            consensus_signal="BUY",
            confidence=0.5,
            rationale_summary="r",
            position_exposure=Decimal("1"),
            unexpected_field="nope",  # type: ignore[call-arg]
        )

    # Rejects confidence out of bounds
    with pytest.raises(ValidationError):
        AdvisoryItem(
            ticker="X",
            consensus_signal="BUY",
            confidence=1.5,
            rationale_summary="r",
            position_exposure=Decimal("1"),
        )
    with pytest.raises(ValidationError):
        AdvisoryItem(
            ticker="X",
            consensus_signal="BUY",
            confidence=-0.1,
            rationale_summary="r",
            position_exposure=Decimal("1"),
        )


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        AdvisoryReport(
            cycle_id="c",
            generated_at=datetime.now(UTC),
            portfolio_outlook="o",
            items=(),
            total_holdings=0,
            affected_holdings=0,
            bogus="x",  # type: ignore[call-arg]
        )


# ---------------- Ranking (41-01-02) --------------------------------------


async def test_synthesize_returns_ranked_list() -> None:
    portfolio = _portfolio({"ZZZT": "100", "QQQX": "400", "XQZW": "200"})
    # LLM returns items in arbitrary order; synthesize must rerank by
    # score = confidence × (exposure / total_cost_basis). total = 700.
    # ZZZT  0.9 × 100/700 = 0.1286
    # QQQX  0.5 × 400/700 = 0.2857  <- highest
    # XQZW  0.7 × 200/700 = 0.2000
    # Expected order: QQQX, XQZW, ZZZT
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "ZZZT",
                "consensus_signal": "BUY",
                "confidence": 0.9,
                "rationale_summary": "a",
                "position_exposure": "100",
            },
            {
                "ticker": "QQQX",
                "consensus_signal": "BUY",
                "confidence": 0.5,
                "rationale_summary": "n",
                "position_exposure": "400",
            },
            {
                "ticker": "XQZW",
                "consensus_signal": "HOLD",
                "confidence": 0.7,
                "rationale_summary": "t",
                "position_exposure": "200",
            },
        ],
        total=3,
    )
    fake_graph = FakeGraphManager()
    fake_provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[_make_result(canned)],
    )

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        provider=fake_provider,
    )

    tickers_in_order = [i.ticker for i in report.items]
    assert tickers_in_order == ["QQQX", "XQZW", "ZZZT"]
    assert report.total_holdings == 3
    assert report.affected_holdings == 3


# ---------------- LLM-driven filtering (41-01-03) -------------------------


async def test_ticker_join_filters_unmatched() -> None:
    portfolio = _portfolio(
        {
            "ZZZT": "100",
            "QQQX": "400",
            "XQZW": "200",
            "ZQXY": "300",
            "MSFT": "150",
        }
    )
    # LLM returns only 2 items — proves D-03: omission is LLM-driven.
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "QQQX",
                "consensus_signal": "BUY",
                "confidence": 0.8,
                "rationale_summary": "n",
                "position_exposure": "400",
            },
            {
                "ticker": "XQZW",
                "consensus_signal": "SELL",
                "confidence": 0.6,
                "rationale_summary": "t",
                "position_exposure": "200",
            },
        ],
        total=5,
    )
    fake_graph = FakeGraphManager()
    fake_provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[_make_result(canned)],
    )

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        provider=fake_provider,
    )

    # docs/DECISIONS.md#sweep-b-7: the engine pads HOLD@0.30 items server-side for every
    # holding the LLM didn't return, so the full portfolio is represented
    # without spending LLM tokens on no-signal HOLD boilerplate.
    assert report.total_holdings == 5
    # affected_holdings counts only LLM conviction items, NOT padded HOLDs.
    assert report.affected_holdings == 2
    # All 5 tickers present: 2 from the LLM + 3 padded by the engine.
    assert {i.ticker for i in report.items} == {"ZZZT", "QQQX", "XQZW", "ZQXY", "MSFT"}
    # Padded items are HOLD@0.30 with the canonical placeholder message.
    padded = [i for i in report.items if i.ticker in {"ZZZT", "ZQXY", "MSFT"}]
    assert len(padded) == 3
    assert all(i.consensus_signal == "HOLD" for i in padded)
    assert all(abs(float(i.confidence) - 0.30) < 1e-9 for i in padded)

    # Top 15 enriched tickers reach the LLM prompt; with only 5 holdings here
    # the whole portfolio is in the top-15 slice so all 5 still appear.
    prompt_text = "\n".join(m["content"] for m in fake_provider.calls[0]["messages"])
    for t in ["ZZZT", "QQQX", "XQZW", "ZQXY", "MSFT"]:
        assert t in prompt_text


# ---------------- Prefetch order -----------------------------------------


async def test_prefetch_order() -> None:
    portfolio = _portfolio({"ZZZT": "100"})
    canned = _valid_advisory_payload(items=[], total=1)
    fake_graph = FakeGraphManager()
    fake_provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[_make_result(canned)],
    )

    await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        provider=fake_provider,
    )

    read_calls = [c for c in fake_graph.call_log if c.startswith("read_") and c != "read_cycle_seed"]
    assert set(read_calls) == {
        "read_consensus_summary",
        "read_round_timeline",
        "read_bracket_narratives",
        "read_entity_impact",
    }
    # Provider called exactly once (no retry needed for valid payload)
    assert len(fake_provider.calls) == 1


# ---------------- Retry on ValidationError (41-01-04) --------------------


async def test_synthesize_retry_on_validation_error() -> None:
    portfolio = _portfolio({"ZZZT": "100"})
    malformed = '{"cycle_id": "unit_cycle", "oops": true}'  # missing required fields
    valid = _valid_advisory_payload(items=[], total=1)

    fake_graph = FakeGraphManager()
    fake_provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[_make_result(malformed), _make_result(valid)],
    )

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        provider=fake_provider,
    )

    assert report.affected_holdings == 0
    assert len(fake_provider.calls) == 2  # initial + retry

    # The retry carries chat_structured's correction turn (field locations, never values).
    retry_messages = fake_provider.calls[1]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "did not match the required JSON schema" in retry_messages[-1]["content"]
    assert "portfolio_outlook" in retry_messages[-1]["content"]


async def test_synthesize_retry_then_fail() -> None:
    portfolio = _portfolio({"ZZZT": "100"})
    bad1 = '{"no": "good"}'
    bad2 = '{"still": "broken"}'

    fake_graph = FakeGraphManager()
    fake_provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[_make_result(bad1), _make_result(bad2)],
    )

    with pytest.raises(StructuredOutputError):
        await synthesize(
            cycle_id="unit_cycle",
            portfolio=portfolio,
            graph_manager=fake_graph,  # type: ignore[arg-type]
            provider=fake_provider,
        )
    assert len(fake_provider.calls) == 2  # retry budget is exactly 1


# ---------------- Post-LLM reconciliation (audit fix #1) ------------------


def _portfolio_with_lots(lots: list[tuple[str, str]]) -> PortfolioSnapshot:
    """Portfolio built from (ticker, cost_basis) lots — duplicate tickers allowed."""
    holdings = tuple(Holding(ticker=t, qty=Decimal("10"), cost_basis=Decimal(cost)) for t, cost in lots)
    return PortfolioSnapshot(
        holdings=holdings,
        as_of=datetime.now(UTC),
        account_number_hash="deadbeef",
    )


async def test_duplicate_lots_pad_once_with_aggregated_exposure() -> None:
    """ZZZT held in taxable AND Roth (two lots) yields ONE padded item with
    the cost basis aggregated across lots; total_holdings counts unique tickers."""
    portfolio = _portfolio_with_lots([("ZZZT", "100"), ("ZZZT", "50"), ("QQQX", "300")])
    canned = _valid_advisory_payload(items=[], total=3)

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=FakeGraphManager(),  # type: ignore[arg-type]
        provider=FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(canned)],
        ),
    )

    assert report.total_holdings == 2  # unique tickers, not lots
    assert sorted(i.ticker for i in report.items) == ["QQQX", "ZZZT"]
    zzzt = next(i for i in report.items if i.ticker == "ZZZT")
    assert zzzt.position_exposure == Decimal("150")  # 100 + 50 aggregated


async def test_hallucinated_tickers_filtered_and_exposure_overwritten() -> None:
    """LLM items for unowned tickers are dropped; kept items get the actual
    aggregated cost basis instead of the LLM-invented exposure."""
    portfolio = _portfolio_with_lots([("ZZZT", "100"), ("QQQX", "250"), ("QQQX", "150")])
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "GME",  # not owned — hallucinated
                "consensus_signal": "BUY",
                "confidence": 0.9,
                "rationale_summary": "hallucinated",
                "position_exposure": "123456",
            },
            {
                "ticker": "QQQX",
                "consensus_signal": "BUY",
                "confidence": 0.8,
                "rationale_summary": "real",
                "position_exposure": "999",  # LLM-invented — must be overwritten
            },
        ],
        total=3,
    )

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=FakeGraphManager(),  # type: ignore[arg-type]
        provider=FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(canned)],
        ),
    )

    tickers = {i.ticker for i in report.items}
    assert "GME" not in tickers
    assert tickers == {"ZZZT", "QQQX"}
    qqqx = next(i for i in report.items if i.ticker == "QQQX")
    assert qqqx.position_exposure == Decimal("400")  # 250 + 150 actual lots
    assert report.affected_holdings == 1  # only the kept QQQX conviction item


async def test_padded_items_sort_after_conviction_items() -> None:
    """Padded HOLD@0.30 placeholders rank AFTER conviction items even when
    their raw score (confidence × exposure share) is higher — sort key is
    (is_padded, -score)."""
    # ZZZT dominates exposure: padded score 0.30 × ~1.0 beats the tiny QQQX
    # conviction score 0.35 × ~0.0001 — old ranking put ZZZT first.
    portfolio = _portfolio_with_lots([("QQQX", "10"), ("ZZZT", "100000")])
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "QQQX",
                "consensus_signal": "BUY",
                "confidence": 0.35,
                "rationale_summary": "small but conviction",
                "position_exposure": "10",
            },
        ],
        total=2,
    )

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=FakeGraphManager(),  # type: ignore[arg-type]
        provider=FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(canned)],
        ),
    )

    assert [i.ticker for i in report.items] == ["QQQX", "ZZZT"]
    assert report.items[1].consensus_signal == "HOLD"
    assert abs(float(report.items[1].confidence) - 0.30) < 1e-9


async def test_llm_duplicate_ticker_items_deduped_keep_highest_confidence() -> None:
    """If the LLM emits the same ticker twice, keep the higher-confidence item."""
    portfolio = _portfolio_with_lots([("ZZZT", "400")])
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "ZZZT",
                "consensus_signal": "HOLD",
                "confidence": 0.5,
                "rationale_summary": "weak",
                "position_exposure": "400",
            },
            {
                "ticker": "ZZZT",
                "consensus_signal": "BUY",
                "confidence": 0.8,
                "rationale_summary": "strong",
                "position_exposure": "400",
            },
        ],
        total=1,
    )

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=FakeGraphManager(),  # type: ignore[arg-type]
        provider=FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(canned)],
        ),
    )

    assert len(report.items) == 1
    assert report.items[0].consensus_signal == "BUY"
    assert report.items[0].confidence == 0.8


async def test_cycle_id_overwritten_with_caller_value() -> None:
    """The LLM-echoed cycle_id never persists — the caller's value wins."""
    portfolio = _portfolio_with_lots([("ZZZT", "100")])
    canned = _valid_advisory_payload(items=[], total=1)  # echoes "unit_cycle"

    report = await synthesize(
        cycle_id="real_cycle_42",
        portfolio=portfolio,
        graph_manager=FakeGraphManager(),  # type: ignore[arg-type]
        provider=FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-orch",
            scripted=[_make_result(canned)],
        ),
    )

    assert report.cycle_id == "real_cycle_42"


# ---------------- Isolation sanity (mini canary; full canary in 41-02) ---


async def test_synthesize_never_logs_portfolio_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mini-canary: sentinel portfolio values MUST NOT appear in log output.

    Full four-surface ISOL-07 canary lives in tests/invariants/ and is
    activated in Plan 41-02. This unit test is the first guard.
    """
    sentinel_ticker = "SNTL_CANARY_TICKER"
    sentinel_cost = Decimal("999999.99")
    portfolio = PortfolioSnapshot(
        holdings=(Holding(ticker=sentinel_ticker, qty=Decimal("7"), cost_basis=sentinel_cost),),
        as_of=datetime.now(UTC),
        account_number_hash="SNTL_ACCT",
    )
    # Configure structlog to a StringIO for this test
    buf = io.StringIO()
    structlog.configure(
        processors=[structlog.processors.JSONRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )

    canned = _valid_advisory_payload(items=[], total=1)
    fake_graph = FakeGraphManager()
    fake_provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[_make_result(canned)],
    )

    await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        provider=fake_provider,
    )
    # Reset structlog so other tests are unaffected
    structlog.reset_defaults()

    log_output = buf.getvalue()
    # Ticker sentinel: ticker IS legitimately passed to the LLM prompt but
    # MUST NOT land in logs (structlog is where Pitfall 1 bites).
    assert sentinel_ticker not in log_output, f"leaked ticker into logs:\n{log_output}"
    assert "999999.99" not in log_output, f"leaked cost_basis into logs:\n{log_output}"
    assert "SNTL_ACCT" not in log_output, f"leaked acct hash into logs:\n{log_output}"


# ---------------- F-07: entity-impact ranking ------------------------------


def test_enrich_holdings_entity_impact_drives_ranking() -> None:
    """F-07: a strong entity impact must lift its holding above an unmatched one
    (the ranking was previously dead because entity_impacts was always empty)."""
    from alphaswarm.advisory.engine import _enrich_holdings

    holdings = [
        {"ticker": "ZZZT", "qty": "10", "cost_basis": "1000"},
        {"ticker": "QQQX", "qty": "10", "cost_basis": "1000"},
    ]
    # QQQX carries a strong directional impact; ZZZT none. No seed match for either.
    ranked = _enrich_holdings(holdings, {"QQQX": -0.9}, seed_text="an unrelated rumor")
    assert ranked[0]["ticker"] == "QQQX"
    assert float(ranked[0]["relevance_score"]) > float(ranked[1]["relevance_score"])
