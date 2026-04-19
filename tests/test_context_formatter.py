"""Unit tests for alphaswarm.context_formatter.format_market_context.

Phase 40 Plan 02 Task 1. Covers:
  - Full block emission (price + fundamentals + headlines) in D-08 order.
  - Headline cap at 5 (D-09).
  - Silent skip of fetch_failed slices (D-03) for market, news, and both.
  - Skip of entities with no data (no empty blocks).
  - None return when every entity produces nothing (Pitfall 5).
  - Empty entities tuple returns None.
  - Budget-greedy fill (no mid-block truncation).
  - Decimal precision preserved via Decimal.__str__.
  - Company-name entity limitation pin (REVIEWS concern #2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphaswarm.context_formatter import format_market_context
from alphaswarm.ingestion.types import (
    ContextPacket,
    Fundamentals,
    MarketSlice,
    NewsSlice,
    StalenessState,
)

FIXED_DT = datetime(2026, 4, 19, tzinfo=UTC)


def _ms(
    ticker: str,
    price: str | None = "100.00",
    staleness: StalenessState = "fresh",
    fundamentals: Fundamentals | None = None,
) -> MarketSlice:
    return MarketSlice(
        ticker=ticker,
        price=Decimal(price) if price is not None else None,
        fundamentals=fundamentals,
        fetched_at=FIXED_DT,
        source="test",
        staleness=staleness,
    )


def _ns(
    entity: str,
    headlines: tuple[str, ...] = (),
    staleness: StalenessState = "fresh",
) -> NewsSlice:
    return NewsSlice(
        entity=entity,
        headlines=headlines,
        fetched_at=FIXED_DT,
        source="test",
        staleness=staleness,
    )


# ---------------------------------------------------------------------------
# Core behavior tests
# ---------------------------------------------------------------------------


def test_format_market_context_full_block() -> None:
    """Entity with price + fundamentals + 2 headlines produces a full D-08 block."""
    fundamentals = Fundamentals(
        pe_ratio=Decimal("35.12"),
        eps=Decimal("14.88"),
        market_cap=Decimal("1200000000000"),
    )
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVDA",),
        market=(_ms("NVDA", price="523.45", fundamentals=fundamentals),),
        news=(
            _ns(
                "NVDA",
                headlines=("NVDA beats estimates", "Analyst upgrade"),
            ),
        ),
    )
    out = format_market_context(packet)
    assert out is not None
    assert "== NVDA ==" in out
    assert "Price: $523.45" in out
    assert "P/E: 35.12" in out
    assert "EPS: 14.88" in out
    assert "Mkt Cap: 1200000000000" in out
    assert "Recent headlines:" in out
    assert "  - NVDA beats estimates" in out
    assert "  - Analyst upgrade" in out
    # D-08 order: header → Price → Fundamentals → Recent headlines
    header_i = out.index("== NVDA ==")
    price_i = out.index("Price:")
    funds_i = out.index("Fundamentals:")
    news_i = out.index("Recent headlines:")
    assert header_i < price_i < funds_i < news_i


def test_format_market_context_caps_headlines_at_5() -> None:
    """Entity with 10 headlines → exactly 5 bullet lines (D-09)."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVDA",),
        market=(),
        news=(
            _ns(
                "NVDA",
                headlines=tuple(f"headline {i}" for i in range(10)),
            ),
        ),
    )
    out = format_market_context(packet)
    assert out is not None
    # Count "  - " bullet lines
    bullet_count = sum(1 for line in out.splitlines() if line.startswith("  - "))
    assert bullet_count == 5
    assert "headline 0" in out
    assert "headline 4" in out
    assert "headline 5" not in out
    assert "headline 9" not in out


def test_format_market_context_skips_fetch_failed_market() -> None:
    """Market is fetch_failed → block has Recent headlines but NO Price line."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVDA",),
        market=(_ms("NVDA", price="100.00", staleness="fetch_failed"),),
        news=(_ns("NVDA", headlines=("headline A",)),),
    )
    out = format_market_context(packet)
    assert out is not None
    assert "== NVDA ==" in out
    assert "Recent headlines:" in out
    assert "headline A" in out
    assert "Price:" not in out
    assert "Fundamentals:" not in out


def test_format_market_context_skips_fetch_failed_news() -> None:
    """News is fetch_failed → block has Price but NO Recent headlines line."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVDA",),
        market=(_ms("NVDA", price="200.00"),),
        news=(_ns("NVDA", headlines=("hidden",), staleness="fetch_failed"),),
    )
    out = format_market_context(packet)
    assert out is not None
    assert "== NVDA ==" in out
    assert "Price: $200.00" in out
    assert "Recent headlines:" not in out
    assert "hidden" not in out


def test_format_market_context_skips_entity_with_no_data() -> None:
    """Entity absent from both market and news is entirely skipped."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("FED",),
        market=(),
        news=(),
    )
    out = format_market_context(packet)
    assert out is None


def test_format_market_context_all_failed_returns_none() -> None:
    """Every slice is fetch_failed → None (Pitfall 5)."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVDA", "AAPL"),
        market=(
            _ms("NVDA", staleness="fetch_failed"),
            _ms("AAPL", staleness="fetch_failed"),
        ),
        news=(
            _ns("NVDA", headlines=("x",), staleness="fetch_failed"),
            _ns("AAPL", headlines=("y",), staleness="fetch_failed"),
        ),
    )
    out = format_market_context(packet)
    assert out is None


def test_format_market_context_empty_entities_returns_none() -> None:
    """Empty entities tuple → None."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=(),
        market=(),
        news=(),
    )
    out = format_market_context(packet)
    assert out is None


def test_format_market_context_respects_budget_cap() -> None:
    """Output respects budget cap AND never truncates mid-block."""
    entities = tuple(f"TICK{i}" for i in range(20))
    market = tuple(_ms(t, price="100.00") for t in entities)
    news = tuple(_ns(t, headlines=("a long-ish headline for test purposes",)) for t in entities)
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=entities,
        market=market,
        news=news,
    )
    out = format_market_context(packet, budget=200)
    assert out is not None
    assert len(out) <= 200
    # No mid-block truncation: each block starts with "== " and ends with a
    # headline or Price line. Splitting on double-newline should yield
    # complete blocks.
    for block in out.split("\n\n"):
        assert block.startswith("== TICK")
        # Every block that begins must also have at least one data line.
        assert "\n" in block


def test_format_market_context_preserves_decimal_precision() -> None:
    """Decimal.__str__ preserves precision — no float rounding."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVDA",),
        market=(_ms("NVDA", price="523.4567"),),
        news=(),
    )
    out = format_market_context(packet)
    assert out is not None
    assert "$523.4567" in out  # Full precision preserved
    assert "$523.45 " not in out
    assert "$523.46" not in out


def test_format_market_context_company_name_entity_news_only() -> None:
    """Phase 40 known limitation (REVIEWS concern #2): orchestrator emits
    'NVIDIA' not 'NVDA', so the NVDA market slice does NOT attach; news
    attaches because NewsSlice is keyed by the entity name as-emitted."""
    packet = ContextPacket(
        cycle_id="cid",
        as_of=FIXED_DT,
        entities=("NVIDIA",),
        market=(_ms("NVDA", price="523.45"),),  # ticker shape, not "NVIDIA"
        news=(_ns("NVIDIA", headlines=("NVIDIA breaks records",)),),
    )
    out = format_market_context(packet)
    assert out is not None
    assert "== NVIDIA ==" in out
    assert "Recent headlines:" in out
    assert "NVIDIA breaks records" in out
    assert "Price:" not in out  # KNOWN LIMITATION pinned
    assert "Fundamentals:" not in out
