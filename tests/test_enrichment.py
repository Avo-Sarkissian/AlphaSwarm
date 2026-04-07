"""Bracket-specific market data enrichment tests (Phase 18).

Tests verify:
- format_market_block produces correct slices per bracket group
- build_enriched_user_message handles empty/non-empty snapshots
- Char cap truncation works
- Headline injection is budget-capped
- JSON_OUTPUT_INSTRUCTIONS includes ticker_decisions schema
"""

from __future__ import annotations

from alphaswarm.types import BracketType, MarketDataSnapshot


# --- Fixtures ---

AAPL_SNAP = MarketDataSnapshot(
    symbol="AAPL",
    company_name="Apple Inc.",
    last_close=182.50,
    price_change_30d_pct=4.2,
    price_change_90d_pct=8.1,
    avg_volume_30d=48_200_000,
    fifty_two_week_high=199.0,
    fifty_two_week_low=142.0,
    pe_ratio=28.5,
    market_cap=3_000_000_000_000,
    revenue_ttm=400_000_000_000,
    gross_margin_pct=45.0,
    debt_to_equity=1.5,
    earnings_surprise_pct=5.2,
    next_earnings_date="2025-07-15",
    eps_trailing=6.50,
)

TSLA_SNAP = MarketDataSnapshot(
    symbol="TSLA",
    company_name="Tesla Inc.",
    last_close=245.00,
    price_change_30d_pct=-2.5,
    price_change_90d_pct=12.0,
    avg_volume_30d=95_000_000,
    fifty_two_week_high=300.0,
    fifty_two_week_low=180.0,
    pe_ratio=60.0,
    market_cap=780_000_000_000,
    revenue_ttm=97_000_000_000,
    gross_margin_pct=18.0,
    debt_to_equity=0.8,
    earnings_surprise_pct=-1.5,
    next_earnings_date="2025-07-22",
    eps_trailing=4.10,
    headlines=[
        "Tesla Q2 deliveries beat expectations",
        "Musk announces new Gigafactory location",
        "EV subsidy changes could impact margins",
    ],
)


# --- format_market_block tests ---


def test_format_market_block_quants() -> None:
    """Quants bracket returns close/30d/90d/vol/52w fields only."""
    from alphaswarm.enrichment import format_market_block

    result = format_market_block({"AAPL": AAPL_SNAP}, BracketType.QUANTS)
    assert "182.50" in result  # last_close
    assert "4.2" in result  # 30d change
    assert "8.1" in result  # 90d change
    assert "48.2M" in result  # volume
    assert "142.00" in result  # 52w low
    assert "199.00" in result  # 52w high
    # Should NOT contain fundamentals
    assert "PE=" not in result
    assert "mktcap" not in result


def test_format_market_block_suits() -> None:
    """Suits bracket returns PE/mktcap/rev/margin/D-E fields only."""
    from alphaswarm.enrichment import format_market_block

    result = format_market_block({"AAPL": AAPL_SNAP}, BracketType.SUITS)
    assert "PE=" in result
    assert "28.5" in result  # PE ratio
    assert "margin=" in result
    assert "45.0" in result  # gross margin
    assert "D/E=" in result
    # Should NOT contain technicals
    assert "vol=" not in result
    assert "52w=" not in result


def test_format_market_block_insiders() -> None:
    """Insiders bracket returns surprise/next_earnings/EPS/mktcap (no headlines when empty)."""
    from alphaswarm.enrichment import format_market_block

    result = format_market_block({"AAPL": AAPL_SNAP}, BracketType.INSIDERS)
    assert "surprise=" in result
    assert "5.2" in result  # earnings surprise
    assert "next_earnings=" in result
    assert "2025-07-15" in result
    assert "EPS=" in result
    assert "6.50" in result
    # No headlines for AAPL_SNAP (headlines=[])
    assert "Headlines:" not in result


def test_format_market_block_insiders_with_headlines() -> None:
    """Insiders bracket with populated headlines includes headline text."""
    from alphaswarm.enrichment import format_market_block

    result = format_market_block({"TSLA": TSLA_SNAP}, BracketType.INSIDERS)
    assert "Headlines:" in result
    assert "Tesla Q2 deliveries" in result


def test_format_market_block_macro_gets_earnings_slice() -> None:
    """Macro bracket gets Earnings/Insider slice per D-04."""
    from alphaswarm.enrichment import format_market_block

    result = format_market_block({"AAPL": AAPL_SNAP}, BracketType.MACRO)
    assert "surprise=" in result
    assert "EPS=" in result
    assert "next_earnings=" in result
    # Should NOT have technicals
    assert "vol=" not in result
    assert "52w=" not in result


def test_format_market_block_empty_snapshots() -> None:
    """Empty snapshots dict returns empty string."""
    from alphaswarm.enrichment import format_market_block

    result = format_market_block({}, BracketType.QUANTS)
    assert result == ""


def test_format_market_block_truncation() -> None:
    """Output is truncated to MAX_MARKET_BLOCK_CHARS for the bracket."""
    from alphaswarm.enrichment import MAX_MARKET_BLOCK_CHARS, format_market_block

    # Create many snapshots to exceed the char cap
    snapshots = {}
    for i in range(20):
        sym = f"T{i:03d}"
        snapshots[sym] = MarketDataSnapshot(
            symbol=sym,
            last_close=100.0 + i,
            price_change_30d_pct=float(i),
            price_change_90d_pct=float(i * 2),
            avg_volume_30d=float(1_000_000 * (i + 1)),
            fifty_two_week_high=200.0,
            fifty_two_week_low=50.0,
        )
    result = format_market_block(snapshots, BracketType.QUANTS)
    assert len(result) <= MAX_MARKET_BLOCK_CHARS[BracketType.QUANTS]


# --- build_enriched_user_message tests ---


def test_build_enriched_user_message_with_snapshots() -> None:
    """Non-empty snapshots returns market data header + rumor."""
    from alphaswarm.enrichment import build_enriched_user_message

    result = build_enriched_user_message(
        "Apple might acquire a chip maker",
        {"AAPL": AAPL_SNAP},
        BracketType.QUANTS,
    )
    assert "--- Market Data ---" in result
    assert "Rumor: Apple might acquire a chip maker" in result


def test_build_enriched_user_message_empty_snapshots() -> None:
    """Empty snapshots returns bare rumor string (no header)."""
    from alphaswarm.enrichment import build_enriched_user_message

    result = build_enriched_user_message(
        "Some rumor text",
        {},
        BracketType.QUANTS,
    )
    assert result == "Some rumor text"
    assert "--- Market Data ---" not in result


# --- JSON_OUTPUT_INSTRUCTIONS tests ---


def test_json_output_instructions_contains_ticker_decisions() -> None:
    """JSON_OUTPUT_INSTRUCTIONS contains 'ticker_decisions' substring."""
    from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS

    assert "ticker_decisions" in JSON_OUTPUT_INSTRUCTIONS


def test_json_output_instructions_direction_values() -> None:
    """JSON_OUTPUT_INSTRUCTIONS shows buy/sell/hold for direction (NOT parse_error)."""
    from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS

    assert '"direction": "buy"|"sell"|"hold"' in JSON_OUTPUT_INSTRUCTIONS
    assert "parse_error" not in JSON_OUTPUT_INSTRUCTIONS


# --- Headline budget-cap test ---


def test_format_market_block_headline_budget_cap() -> None:
    """With 3 tickers and 10 headlines each, not all 30 headlines are injected."""
    from alphaswarm.enrichment import format_market_block

    long_headlines = [f"Breaking news headline number {i} about important market events and developments" for i in range(10)]
    snaps = {}
    for sym in ["AAA", "BBB", "CCC"]:
        snaps[sym] = MarketDataSnapshot(
            symbol=sym,
            company_name=f"{sym} Corp",
            earnings_surprise_pct=2.0,
            next_earnings_date="2025-08-01",
            eps_trailing=3.00,
            market_cap=500_000_000_000,
            headlines=list(long_headlines),
        )
    result = format_market_block(snaps, BracketType.INSIDERS)
    # Count total headlines injected -- should be less than 30 (10 per ticker)
    headline_count = result.count("Breaking news headline")
    assert headline_count < 30
    assert headline_count > 0  # At least some headlines injected
