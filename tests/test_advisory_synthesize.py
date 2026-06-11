"""Regression tests for ITEM 6 of quick task 260512-jqn — Advisory items[]
+ sector enrichment + frontend fallback hooks (closes task #10).

Validates:
    • SECTOR_MAP covers the user's 32 unique tickers (Schwab + Roth).
    • lookup() returns UNKNOWN_SECTOR for tickers not in the map.
    • _enrich_holdings sorts DESC by (|entity_impact| * |macro_beta|
      + 0.5 * seed_match) and attaches sector fields.
    • build_advisory_prompt now carries the "NEVER OMIT" instruction.
    • _enrich_holdings includes the relevance_score field on each item.
"""
from __future__ import annotations

from alphaswarm.advisory import engine
from alphaswarm.advisory.prompt import build_advisory_prompt
from alphaswarm.advisory.sector_map import SECTOR_MAP, UNKNOWN_SECTOR, lookup


# ---------------------------------------------------------------------------
# Sector map coverage
# ---------------------------------------------------------------------------


def test_sector_map_covers_user_tickers() -> None:
    """All 32 unique Schwab + Roth tickers must have a SECTOR_MAP entry."""
    required = [
        "AAPL", "AMZN", "ARM", "ASML", "AVGO", "BYDDY", "COHR", "CHAT",
        "CQQQ", "CRDO", "DBX", "HIMS", "HON", "ISRG", "LPL", "MRVL",
        "NIO", "NKE", "NVDA", "PLTR", "PYPL", "QQQ", "SCHW", "SOFI",
        "SPY", "SWYXX", "TLN", "TSLA", "TSM", "VRT", "VST", "WTAI",
    ]
    assert len(required) == 32
    for ticker in required:
        assert ticker in SECTOR_MAP, f"missing sector entry: {ticker}"
        info = SECTOR_MAP[ticker]
        assert -1.0 <= info["macro_beta"] <= 1.0
        assert info["region_exposure"] in ("US", "Asia", "global", "EM", "cash")
        assert info["supply_chain_sensitivity"] in ("low", "med", "high")
        assert info["sector"]  # non-empty


def test_sector_map_unknown_default() -> None:
    """Unknown tickers fall back to the UNKNOWN_SECTOR default.

    macro_beta=0.5 (not 0.0) so seed-text matches can still promote unknown
    tickers via the `|impact| × |beta| + 0.5 × seed_match` formula —
    SWEEP-260528 B-8 raised the default from 0.0 to 0.5 to keep relevance
    scoring honest when the seed names a ticker outside SECTOR_MAP.
    """
    assert lookup("NOTREAL") == UNKNOWN_SECTOR
    assert lookup("NOTREAL")["sector"] == "unknown"
    assert lookup("NOTREAL")["macro_beta"] == 0.5


def test_sector_lookup_is_case_insensitive() -> None:
    """lookup() upper-cases the input so 'aapl' resolves to AAPL."""
    assert lookup("aapl") == SECTOR_MAP["AAPL"]
    assert lookup("nvda")["sector"] == "semis_ai_accel"


# ---------------------------------------------------------------------------
# Enrichment + relevance scoring
# ---------------------------------------------------------------------------


def test_enrich_holdings_attaches_sector_fields() -> None:
    """Each holding gains sector / region_exposure / supply_chain_sensitivity /
    macro_beta / relevance_score after _enrich_holdings."""
    holdings = [{"ticker": "AAPL", "qty": "10", "cost_basis": "1000"}]
    enriched = engine._enrich_holdings(holdings, entity_impacts={}, seed_text="")
    assert len(enriched) == 1
    h = enriched[0]
    assert h["ticker"] == "AAPL"
    assert h["sector"] == "consumer_tech"
    assert h["region_exposure"] == "global"
    assert "relevance_score" in h
    # Macro_beta from the map preserved as string for JSON payload.
    assert float(h["macro_beta"]) == 0.85


def test_enrich_holdings_sorts_by_relevance() -> None:
    """Higher entity_impact * macro_beta should sort first."""
    holdings = [
        {"ticker": "SWYXX"},  # macro_beta 0.0 → low relevance
        {"ticker": "NVDA"},   # macro_beta 1.0 + impact 0.9 → high relevance
    ]
    entity_impacts = {"NVDA": 0.9, "SWYXX": 0.1}
    enriched = engine._enrich_holdings(holdings, entity_impacts, seed_text="")
    assert enriched[0]["ticker"] == "NVDA"
    assert enriched[-1]["ticker"] == "SWYXX"


def test_enrich_holdings_seed_match_bonus() -> None:
    """Seed-text match on ticker or sector substring adds +0.5 to relevance."""
    holdings = [
        {"ticker": "NKE"},   # sector consumer_apparel — no match
        {"ticker": "NVDA"},  # ticker NVDA appears in seed → bonus
    ]
    enriched = engine._enrich_holdings(
        holdings, entity_impacts={}, seed_text="NVDA earnings beat",
    )
    # NVDA gets the seed_match bonus; NKE gets 0.0 overall (macro_beta absent in impacts).
    assert enriched[0]["ticker"] == "NVDA"


def test_seed_match_no_false_positive_on_ticker_substring() -> None:
    """'ARM' must NOT seed-match inside 'pharma' — ticker matching uses a
    word-boundary regex, not a raw substring test."""
    holdings = [{"ticker": "ARM"}]
    enriched = engine._enrich_holdings(
        holdings, entity_impacts={}, seed_text="big pharma layoffs announced",
    )
    # No entity impact and no legitimate seed match → relevance is 0.0.
    assert float(enriched[0]["relevance_score"]) == 0.0


def test_seed_match_multiword_sector_phrase() -> None:
    """Sector 'consumer_tech' must match 'consumer tech' in the seed text —
    underscores are replaced with spaces before comparison."""
    holdings = [{"ticker": "AAPL"}]  # sector consumer_tech
    enriched = engine._enrich_holdings(
        holdings, entity_impacts={}, seed_text="consumer tech demand slumps",
    )
    # 0 impact + 0.5 × seed_match(1.0) = 0.5
    assert float(enriched[0]["relevance_score"]) == 0.5


def test_enrich_holdings_unknown_ticker_falls_back() -> None:
    """Unknown ticker still appears in enriched output with UNKNOWN sector
    and the SWEEP-260528 B-8 default macro_beta of 0.5."""
    holdings = [{"ticker": "ZZZZZ"}]
    enriched = engine._enrich_holdings(holdings, entity_impacts={}, seed_text="")
    assert len(enriched) == 1
    assert enriched[0]["sector"] == "unknown"
    assert float(enriched[0]["macro_beta"]) == 0.5


# ---------------------------------------------------------------------------
# Prompt rewrite
# ---------------------------------------------------------------------------


def test_prompt_instructs_conviction_items_only() -> None:
    """Prompt MUST instruct the LLM to emit conviction items only — engine
    pads HOLD@0.30 server-side for no-signal holdings (SWEEP-260528 B-7)."""
    msgs = build_advisory_prompt(
        cycle_id="c1",
        seed_rumor="test seed",
        bracket_summary={},
        timeline=[],
        narratives=[],
        entity_impact=[],
        top_holdings=[{"ticker": "AAPL", "sector": "consumer_tech", "macro_beta": "0.85"}],
    )
    full = " ".join(m["content"] for m in msgs)
    assert "EMIT CONVICTION ITEMS ONLY" in full
    assert "engine pads" in full.lower()


def test_prompt_renders_top_holdings_only() -> None:
    """Only top_holdings is rendered to the LLM. rest_holdings is accepted
    for back-compat but intentionally not included in the user message —
    engine.py pads the unsent holdings server-side (SWEEP-260528 B-7)."""
    msgs = build_advisory_prompt(
        cycle_id="c1",
        seed_rumor="seed",
        bracket_summary={},
        timeline=[],
        narratives=[],
        entity_impact=[],
        top_holdings=[{"ticker": "AAPL", "sector": "consumer_tech"}],
        rest_holdings=[{"ticker": "SWYXX", "sector": "money_market"}],
    )
    user = msgs[1]["content"]
    assert "AAPL" in user
    # rest_holdings must NOT leak into the prompt — saves ~1500 tokens.
    assert "SWYXX" not in user
    assert "OTHER HOLDINGS" not in user


def test_prompt_legacy_holdings_kwarg_still_works() -> None:
    """Back-compat: callers passing only `holdings=[...]` get a valid prompt
    (treated as top_holdings).
    """
    msgs = build_advisory_prompt(
        cycle_id="c1",
        seed_rumor="seed",
        bracket_summary={},
        timeline=[],
        narratives=[],
        entity_impact=[],
        holdings=[{"ticker": "AAPL", "qty": "10", "cost_basis": "1000"}],
    )
    user = msgs[1]["content"]
    assert "AAPL" in user
    assert "OTHER HOLDINGS" not in user
    assert "TOP HOLDINGS" not in user  # single-list framing now


# ---------------------------------------------------------------------------
# Sanity: SECTOR_MAP size matches the documented 32 unique tickers
# ---------------------------------------------------------------------------


def test_sector_map_size_matches_user_portfolio() -> None:
    """SECTOR_MAP must have exactly 32 entries (one per unique user ticker)."""
    assert len(SECTOR_MAP) == 32
