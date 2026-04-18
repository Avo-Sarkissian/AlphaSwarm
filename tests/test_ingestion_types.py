"""ISOL-02 unit tests: ContextPacket, MarketSlice, NewsSlice, Fundamentals.

extra='forbid' rejection, deep frozenness (REVIEW HIGH: tuple-only collections,
nested Fundamentals sub-model in place of dict), zero-holdings-field schema
assertions, StalenessState typed literal (REVIEW MEDIUM), Decimal price
(REVIEW MEDIUM).
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaswarm.ingestion.types import (
    ContextPacket,
    Fundamentals,
    MarketSlice,
    NewsSlice,
)

SENSITIVE_FIELD_NAMES = frozenset({
    "holdings", "portfolio", "positions", "cost_basis",
    "qty", "shares", "account_number", "account_id",
})


# ------ MarketSlice ------


def test_market_slice_constructs_with_required_fields() -> None:
    m = MarketSlice(ticker="AAPL", fetched_at=datetime.now(UTC), source="yfinance")
    assert m.ticker == "AAPL"
    assert m.staleness == "fresh"
    assert m.price is None


def test_market_slice_price_accepts_decimal() -> None:
    """REVIEW MEDIUM: price is Decimal for financial precision (not float)."""
    m = MarketSlice(
        ticker="AAPL",
        price=Decimal("185.42"),
        fetched_at=datetime.now(UTC),
        source="yfinance",
    )
    assert m.price == Decimal("185.42")
    assert isinstance(m.price, Decimal)


def test_market_slice_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        MarketSlice(
            ticker="AAPL",
            fetched_at=datetime.now(UTC),
            source="x",
            holdings=["bad"],  # type: ignore[call-arg]
        )


def test_market_slice_is_frozen() -> None:
    m = MarketSlice(ticker="AAPL", fetched_at=datetime.now(UTC), source="x")
    with pytest.raises(ValidationError):
        m.ticker = "MSFT"  # type: ignore[misc]


def test_market_slice_zero_holdings_fields() -> None:
    for field_name in MarketSlice.model_fields:
        assert field_name not in SENSITIVE_FIELD_NAMES


# ------ Fundamentals (REVIEW HIGH: nested frozen sub-model, not dict) ------


def test_fundamentals_is_frozen_base_model() -> None:
    f = Fundamentals(pe_ratio=Decimal("25.5"), eps=Decimal("6.1"))
    with pytest.raises(ValidationError):
        f.pe_ratio = Decimal("99")  # type: ignore[misc]


def test_fundamentals_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        Fundamentals(
            pe_ratio=Decimal("25"),
            unknown_metric=Decimal("0"),  # type: ignore[call-arg]
        )


def test_market_slice_fundamentals_is_nested_frozen_model_not_dict() -> None:
    """REVIEW HIGH: dict would allow m.fundamentals['pe_ratio']=999 even on a frozen slice.
    A nested frozen BaseModel produces deep immutability.
    """
    m = MarketSlice(
        ticker="AAPL",
        fetched_at=datetime.now(UTC),
        source="x",
        fundamentals=Fundamentals(pe_ratio=Decimal("20")),
    )
    assert isinstance(m.fundamentals, Fundamentals)
    assert not isinstance(m.fundamentals, dict)
    # Mutation attempt on nested model also fails (deep freeze):
    with pytest.raises(ValidationError):
        m.fundamentals.pe_ratio = Decimal("30")  # type: ignore[misc,union-attr]


# ------ NewsSlice ------


def test_news_slice_headlines_is_tuple() -> None:
    n = NewsSlice(
        entity="AAPL",
        fetched_at=datetime.now(UTC),
        source="rss",
        headlines=("headline 1", "headline 2"),
    )
    assert isinstance(n.headlines, tuple)
    # REVIEW HIGH: tuples expose no append/extend — the mutation surface is closed.
    assert not hasattr(n.headlines, "append")


def test_news_slice_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        NewsSlice(
            entity="AAPL",
            fetched_at=datetime.now(UTC),
            source="rss",
            portfolio="bad",  # type: ignore[call-arg]
        )


def test_news_slice_zero_holdings_fields() -> None:
    for field_name in NewsSlice.model_fields:
        assert field_name not in SENSITIVE_FIELD_NAMES


# ------ ContextPacket ------


def test_context_packet_constructs_empty() -> None:
    p = ContextPacket(cycle_id="c1", as_of=datetime.now(UTC), entities=("AAPL",))
    assert p.market == ()
    assert p.news == ()


def test_context_packet_collections_are_tuples() -> None:
    """REVIEW HIGH: entities, market, news must all be tuple-typed and tuple-instance at runtime."""
    p = ContextPacket(cycle_id="c1", as_of=datetime.now(UTC), entities=("AAPL", "MSFT"))
    assert isinstance(p.entities, tuple)
    assert isinstance(p.market, tuple)
    assert isinstance(p.news, tuple)


def test_context_packet_annotations_are_tuple_only() -> None:
    """REVIEW HIGH: introspect annotations — NO list[...] annotation anywhere."""
    hints = typing.get_type_hints(ContextPacket)
    for name, hint in hints.items():
        str_hint = str(hint)
        assert "list[" not in str_hint and "typing.List" not in str_hint, (
            f"ContextPacket.{name} has list annotation {str_hint!r}; must be tuple"
        )


def test_market_slice_annotations_have_no_dict_fundamentals() -> None:
    """REVIEW HIGH: fundamentals must be nested frozen Fundamentals,
    not dict[str, float]."""
    hints = typing.get_type_hints(MarketSlice)
    fundamentals_hint = str(hints["fundamentals"])
    assert "dict" not in fundamentals_hint.lower(), (
        f"MarketSlice.fundamentals must not be a dict; got {fundamentals_hint!r}"
    )
    assert "Fundamentals" in fundamentals_hint


def test_context_packet_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        ContextPacket(
            cycle_id="c1",
            as_of=datetime.now(UTC),
            entities=("AAPL",),
            holdings=[],  # type: ignore[call-arg]
        )


def test_context_packet_rejects_portfolio_field() -> None:
    with pytest.raises(ValidationError):
        ContextPacket(
            cycle_id="c1",
            as_of=datetime.now(UTC),
            entities=("AAPL",),
            portfolio=[],  # type: ignore[call-arg]
        )


def test_context_packet_zero_holdings_fields() -> None:
    for field_name in ContextPacket.model_fields:
        assert field_name not in SENSITIVE_FIELD_NAMES


def test_context_packet_is_frozen() -> None:
    p = ContextPacket(cycle_id="c1", as_of=datetime.now(UTC), entities=("AAPL",))
    with pytest.raises(ValidationError):
        p.cycle_id = "c2"  # type: ignore[misc]


def test_staleness_accepts_only_literal_values() -> None:
    """REVIEW MEDIUM: StalenessState is a typed literal — 'unknown' must be rejected."""
    for value in ("fresh", "stale", "fetch_failed"):
        m = MarketSlice(
            ticker="AAPL",
            fetched_at=datetime.now(UTC),
            source="x",
            staleness=value,  # type: ignore[arg-type]
        )
        assert m.staleness == value
    with pytest.raises(ValidationError):
        MarketSlice(
            ticker="AAPL",
            fetched_at=datetime.now(UTC),
            source="x",
            staleness="unknown",  # type: ignore[arg-type]
        )
