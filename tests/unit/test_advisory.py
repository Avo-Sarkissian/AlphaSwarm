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
from alphaswarm.holdings.types import Holding, PortfolioSnapshot


# ---------------- Fakes ----------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChatResponse:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class FakeOllamaClient:
    """Returns canned responses in order; tracks call count + sent messages."""

    def __init__(self, canned: list[str]) -> None:
        self._canned = list(canned)
        self.calls: list[list[dict[str, str]]] = []

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        format: str | dict[str, Any] | None = None,
        **_: Any,
    ) -> _FakeChatResponse:
        self.calls.append(messages)
        if not self._canned:
            raise AssertionError("FakeOllamaClient exhausted")
        return _FakeChatResponse(self._canned.pop(0))


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
    """Build a JSON payload matching the AdvisoryReport schema."""
    return json.dumps(
        {
            "cycle_id": "unit_cycle",
            "generated_at": "2026-04-19T22:00:00+00:00",
            "portfolio_outlook": "Swarm is mildly bullish on AI infra names.",
            "items": items,
            "total_holdings": total,
            "affected_holdings": len(items),
        }
    )


def _portfolio(ticker_to_cost: dict[str, str]) -> PortfolioSnapshot:
    holdings = tuple(
        Holding(ticker=t, qty=Decimal("10"), cost_basis=Decimal(cost))
        for t, cost in ticker_to_cost.items()
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
        ticker="AAPL",
        consensus_signal="BUY",
        confidence=0.75,
        rationale_summary="ok",
        position_exposure=Decimal("100"),
    )
    assert item.ticker == "AAPL"

    # Rejects unknown fields (extra='forbid')
    with pytest.raises(ValidationError):
        AdvisoryItem(
            ticker="AAPL",
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
    portfolio = _portfolio({"AAPL": "100", "NVDA": "400", "TSLA": "200"})
    # LLM returns items in arbitrary order; synthesize must rerank by
    # score = confidence × (exposure / total_cost_basis). total = 700.
    # AAPL  0.9 × 100/700 = 0.1286
    # NVDA  0.5 × 400/700 = 0.2857  <- highest
    # TSLA  0.7 × 200/700 = 0.2000
    # Expected order: NVDA, TSLA, AAPL
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "AAPL",
                "consensus_signal": "BUY",
                "confidence": 0.9,
                "rationale_summary": "a",
                "position_exposure": "100",
            },
            {
                "ticker": "NVDA",
                "consensus_signal": "BUY",
                "confidence": 0.5,
                "rationale_summary": "n",
                "position_exposure": "400",
            },
            {
                "ticker": "TSLA",
                "consensus_signal": "HOLD",
                "confidence": 0.7,
                "rationale_summary": "t",
                "position_exposure": "200",
            },
        ],
        total=3,
    )
    fake_graph = FakeGraphManager()
    fake_ollama = FakeOllamaClient(canned=[canned])

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        ollama_client=fake_ollama,  # type: ignore[arg-type]
        orchestrator_model="alphaswarm-orchestrator",
    )

    tickers_in_order = [i.ticker for i in report.items]
    assert tickers_in_order == ["NVDA", "TSLA", "AAPL"]
    assert report.total_holdings == 3
    assert report.affected_holdings == 3


# ---------------- LLM-driven filtering (41-01-03) -------------------------


async def test_ticker_join_filters_unmatched() -> None:
    portfolio = _portfolio(
        {
            "AAPL": "100",
            "NVDA": "400",
            "TSLA": "200",
            "AMZN": "300",
            "MSFT": "150",
        }
    )
    # LLM returns only 2 items — proves D-03: omission is LLM-driven.
    canned = _valid_advisory_payload(
        items=[
            {
                "ticker": "NVDA",
                "consensus_signal": "BUY",
                "confidence": 0.8,
                "rationale_summary": "n",
                "position_exposure": "400",
            },
            {
                "ticker": "TSLA",
                "consensus_signal": "SELL",
                "confidence": 0.6,
                "rationale_summary": "t",
                "position_exposure": "200",
            },
        ],
        total=5,
    )
    fake_graph = FakeGraphManager()
    fake_ollama = FakeOllamaClient(canned=[canned])

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        ollama_client=fake_ollama,  # type: ignore[arg-type]
        orchestrator_model="alphaswarm-orchestrator",
    )

    assert report.total_holdings == 5
    assert report.affected_holdings == 2
    assert {i.ticker for i in report.items} == {"NVDA", "TSLA"}

    # All 5 tickers should appear in the prompt payload (prefetch fidelity)
    prompt_text = "\n".join(m["content"] for m in fake_ollama.calls[0])
    for t in ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT"]:
        assert t in prompt_text


# ---------------- Prefetch order -----------------------------------------


async def test_prefetch_order() -> None:
    portfolio = _portfolio({"AAPL": "100"})
    canned = _valid_advisory_payload(items=[], total=1)
    fake_graph = FakeGraphManager()
    fake_ollama = FakeOllamaClient(canned=[canned])

    await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        ollama_client=fake_ollama,  # type: ignore[arg-type]
        orchestrator_model="alphaswarm-orchestrator",
    )

    read_calls = [
        c for c in fake_graph.call_log if c.startswith("read_") and c != "read_cycle_seed"
    ]
    assert set(read_calls) == {
        "read_consensus_summary",
        "read_round_timeline",
        "read_bracket_narratives",
        "read_entity_impact",
    }
    # LLM called exactly once (no retry needed for valid payload)
    assert len(fake_ollama.calls) == 1


# ---------------- Retry on ValidationError (41-01-04) --------------------


async def test_synthesize_retry_on_validation_error() -> None:
    portfolio = _portfolio({"AAPL": "100"})
    malformed = '{"cycle_id": "unit_cycle", "oops": true}'  # missing required fields
    valid = _valid_advisory_payload(items=[], total=1)

    fake_graph = FakeGraphManager()
    fake_ollama = FakeOllamaClient(canned=[malformed, valid])

    report = await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        ollama_client=fake_ollama,  # type: ignore[arg-type]
        orchestrator_model="alphaswarm-orchestrator",
    )

    assert report.affected_holdings == 0
    assert len(fake_ollama.calls) == 2  # initial + retry

    # The retry message carries the validation error text for the model to correct
    retry_messages = fake_ollama.calls[1]
    assert any(
        "failed validation" in m["content"] for m in retry_messages if m["role"] == "user"
    )


async def test_synthesize_retry_then_fail() -> None:
    portfolio = _portfolio({"AAPL": "100"})
    bad1 = '{"no": "good"}'
    bad2 = '{"still": "broken"}'

    fake_graph = FakeGraphManager()
    fake_ollama = FakeOllamaClient(canned=[bad1, bad2])

    with pytest.raises(ValidationError):
        await synthesize(
            cycle_id="unit_cycle",
            portfolio=portfolio,
            graph_manager=fake_graph,  # type: ignore[arg-type]
            ollama_client=fake_ollama,  # type: ignore[arg-type]
            orchestrator_model="alphaswarm-orchestrator",
        )
    assert len(fake_ollama.calls) == 2  # retry budget is exactly 1


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
        holdings=(
            Holding(ticker=sentinel_ticker, qty=Decimal("7"), cost_basis=sentinel_cost),
        ),
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
    fake_ollama = FakeOllamaClient(canned=[canned])

    await synthesize(
        cycle_id="unit_cycle",
        portfolio=portfolio,
        graph_manager=fake_graph,  # type: ignore[arg-type]
        ollama_client=fake_ollama,  # type: ignore[arg-type]
        orchestrator_model="alphaswarm-orchestrator",
    )
    # Reset structlog so other tests are unaffected
    structlog.reset_defaults()

    log_output = buf.getvalue()
    # Ticker sentinel: ticker IS legitimately passed to the LLM prompt but
    # MUST NOT land in logs (structlog is where Pitfall 1 bites).
    assert sentinel_ticker not in log_output, f"leaked ticker into logs:\n{log_output}"
    assert "999999.99" not in log_output, f"leaked cost_basis into logs:\n{log_output}"
    assert "SNTL_ACCT" not in log_output, f"leaked acct hash into logs:\n{log_output}"
