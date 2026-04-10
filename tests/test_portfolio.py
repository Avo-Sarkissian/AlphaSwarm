"""Unit tests for alphaswarm.portfolio (Phase 25 PORTFOLIO-01..04).

Revised per 25-REVIEWS.md to cover:
- Word-boundary ticker matching (no ARM vs ALARM false positive)
- Non-equity preservation as gaps with reason='non_equity'
- Currency edge cases (blanks, --, N/A, parens-negative)
- BOM encoding (utf-8-sig)
- Dynamic header row detection
- Duplicate ticker aggregation
- TypedDict contract shape
- No individual position logging
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from alphaswarm.portfolio import (
    REASON_NO_COVERAGE,
    REASON_NON_EQUITY,
    TICKER_ENTITY_MAP,
    PortfolioParseError,
    _find_header_row,
    _match_entity,
    _parse_currency,
    _parse_quantity,
    build_portfolio_impact,
    parse_schwab_csv,
    parse_schwab_csv_async,
)


SAMPLE_CSV = (
    '"Positions for account Individual as of 03:47 PM ET, 2026/04/09",,,,,,,,,,,,,,,,,\n'
    '\n'
    '"Symbol","Description","Qty (Quantity)","Price","Price Chng %","Price Chng $","Mkt Val (Market Value)","Day Chng %","Day Chng $","Cost Basis","Gain $","Gain %","Ratings","Reinvest Dividends?","Capital Gains?","% Of Account","Security Type","Asset Type"\n'
    '"AAPL","APPLE INC","101.3071","260.80","+0.50%","+1.30","$26,416.56 ","+0.50%","+131.70","$12,000.00","$14,416.56 ","+120.14%","--","Yes","Yes","15.00%","Stock","Equity"\n'
    '"LPL","LG DISPLAY CO","1,000","3.00","--","--","$3,000.00 ","--","--","$3,500.00","($500.00)","(14.28%)","--","Yes","Yes","1.70%","Stock","Equity"\n'
    '"PLTR","PALANTIR TECHNOLOGIES","100","80.00","--","--","$8,000.00 ","--","($4,472.00)","$5,000.00","$3,000.00","60.00%","--","Yes","Yes","4.5%","Stock","Equity"\n'
    '"QQQ","INVESCO QQQ TRUST","50","500.00","--","--","$25,000.00 ","--","--","$20,000.00","$5,000.00","25.00%","--","Yes","Yes","14.2%","ETF","ETFs & Closed End Funds"\n'
    '"Cash & Cash Investments","","--","--","--","--","$500.00","--","--","--","--","--","--","--","--","0.3%","Cash","Cash and Money Market"\n'
    '"Positions Total","",--,--,"+0.28%","+1.30","$62,916.56 ","--","--","$40,500.00","$21,916.56 ","+54.12%","--","--","--","100%","--","--"\n'
)


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    p = tmp_path / "Individual-Positions-test.csv"
    p.write_text(SAMPLE_CSV, encoding="utf-8")
    return p


# -----------------------------------------------------------------------------
# Currency / quantity parsing (REVIEWS: currency edge cases)
# -----------------------------------------------------------------------------

class TestCurrencyParsing:
    def test_standard(self) -> None:
        assert _parse_currency("$26,416.56") == 26416.56

    def test_trailing_space(self) -> None:
        assert _parse_currency("$26,416.56 ") == 26416.56

    def test_parens_negative(self) -> None:
        assert _parse_currency("($4,472.00)") == -4472.00

    def test_empty(self) -> None:
        assert _parse_currency("") == 0.0

    def test_dash_sentinel(self) -> None:
        assert _parse_currency("--") == 0.0

    def test_na_sentinel(self) -> None:
        assert _parse_currency("N/A") == 0.0
        assert _parse_currency("n/a") == 0.0

    def test_unparseable_falls_back_to_zero(self) -> None:
        assert _parse_currency("garbage") == 0.0

    def test_plain(self) -> None:
        assert _parse_currency("1000.00") == 1000.00


class TestQuantityParsing:
    def test_thousands_separator(self) -> None:
        assert _parse_quantity("1,000") == 1000.0

    def test_plain(self) -> None:
        assert _parse_quantity("101.3071") == 101.3071

    def test_empty(self) -> None:
        assert _parse_quantity("") == 0.0

    def test_dash(self) -> None:
        assert _parse_quantity("--") == 0.0


# -----------------------------------------------------------------------------
# Header row detection (REVIEWS: CSV header fragility)
# -----------------------------------------------------------------------------

class TestHeaderRowDetection:
    def test_finds_header_at_row_2(self) -> None:
        lines = [
            '"metadata row",,,',
            '',
            '"Symbol","Description","Qty (Quantity)","Asset Type"',
        ]
        assert _find_header_row(lines) == 2

    def test_finds_header_at_row_0_if_no_metadata(self) -> None:
        lines = [
            '"Symbol","Description","Qty (Quantity)","Asset Type"',
            '"AAPL","APPLE","10","Equity"',
        ]
        assert _find_header_row(lines) == 0

    def test_raises_when_header_missing(self) -> None:
        lines = [
            '"some data"',
            '"more data"',
            '"still no symbol header"',
            '"nope"',
            '"nope"',
        ]
        with pytest.raises(PortfolioParseError, match="header row not found"):
            _find_header_row(lines)


# -----------------------------------------------------------------------------
# Parser happy path
# -----------------------------------------------------------------------------

class TestParseSchwabCsv:
    def test_returns_typed_dict_shape(self, sample_csv: Path) -> None:
        result = parse_schwab_csv(sample_csv)
        assert set(result.keys()) == {"equity_holdings", "excluded_holdings"}

    def test_equity_keys(self, sample_csv: Path) -> None:
        result = parse_schwab_csv(sample_csv)
        assert set(result["equity_holdings"].keys()) == {"AAPL", "LPL", "PLTR"}

    def test_excluded_keys_includes_etf(self, sample_csv: Path) -> None:
        result = parse_schwab_csv(sample_csv)
        assert "QQQ" in result["excluded_holdings"]
        assert result["excluded_holdings"]["QQQ"]["asset_type"] == "ETFs & Closed End Funds"

    def test_positions_total_and_cash_skipped(self, sample_csv: Path) -> None:
        result = parse_schwab_csv(sample_csv)
        all_keys = set(result["equity_holdings"]) | set(result["excluded_holdings"])
        assert "Positions Total" not in all_keys
        assert "Cash & Cash Investments" not in all_keys

    def test_parses_shares_and_market_value(self, sample_csv: Path) -> None:
        result = parse_schwab_csv(sample_csv)
        aapl = result["equity_holdings"]["AAPL"]
        assert aapl["shares"] == pytest.approx(101.3071)
        assert aapl["market_value"] == pytest.approx(26416.56)

    def test_parses_lpl_with_thousands_comma(self, sample_csv: Path) -> None:
        result = parse_schwab_csv(sample_csv)
        lpl = result["equity_holdings"]["LPL"]
        assert lpl["shares"] == pytest.approx(1000.0)
        assert lpl["market_value"] == pytest.approx(3000.00)

    def test_empty_equity_still_returns_shape(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.csv"
        p.write_text(
            '"Positions for account",,,,\n\n'
            '"Symbol","Description","Qty (Quantity)","Mkt Val (Market Value)","Asset Type"\n'
            '"QQQ","INVESCO QQQ","10","$5000.00","ETFs & Closed End Funds"\n',
            encoding="utf-8",
        )
        result = parse_schwab_csv(p)
        assert result["equity_holdings"] == {}
        assert "QQQ" in result["excluded_holdings"]


# -----------------------------------------------------------------------------
# BOM handling (REVIEWS: encoding issues)
# -----------------------------------------------------------------------------

class TestBomEncoding:
    def test_handles_utf8_bom(self, tmp_path: Path) -> None:
        p = tmp_path / "bom.csv"
        # Write with utf-8-sig so a BOM \ufeff is prefixed to the file
        p.write_text(SAMPLE_CSV, encoding="utf-8-sig")
        result = parse_schwab_csv(p)
        assert "AAPL" in result["equity_holdings"]


# -----------------------------------------------------------------------------
# Duplicate ticker handling (REVIEWS: duplicate tickers)
# -----------------------------------------------------------------------------

class TestDuplicateTickerAggregation:
    def test_duplicate_equity_rows_aggregate(self, tmp_path: Path) -> None:
        csv_text = (
            '"Positions for account",,,,\n\n'
            '"Symbol","Description","Qty (Quantity)","Mkt Val (Market Value)","Asset Type"\n'
            '"AAPL","APPLE INC","10","$1000.00","Equity"\n'
            '"AAPL","APPLE INC","5","$500.00","Equity"\n'
        )
        p = tmp_path / "dup.csv"
        p.write_text(csv_text, encoding="utf-8")
        result = parse_schwab_csv(p)
        assert result["equity_holdings"]["AAPL"]["shares"] == pytest.approx(15.0)
        assert result["equity_holdings"]["AAPL"]["market_value"] == pytest.approx(1500.0)


# -----------------------------------------------------------------------------
# Header missing raises (REVIEWS: fail-fast on malformed CSV)
# -----------------------------------------------------------------------------

class TestMalformedCsvRaises:
    def test_missing_header_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.csv"
        p.write_text("garbage\nnot,a,header\nalso,not,header\n", encoding="utf-8")
        with pytest.raises(PortfolioParseError):
            parse_schwab_csv(p)

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "missing_col.csv"
        p.write_text(
            '"Positions",,,\n\n'
            '"Symbol","Description","Asset Type"\n'
            '"AAPL","Apple","Equity"\n',
            encoding="utf-8",
        )
        with pytest.raises(PortfolioParseError, match="missing required columns"):
            parse_schwab_csv(p)

    def test_too_short_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "short.csv"
        p.write_text("one\ntwo\n", encoding="utf-8")
        with pytest.raises(PortfolioParseError):
            parse_schwab_csv(p)


# -----------------------------------------------------------------------------
# No persistence / no individual logging (REVIEWS: privacy)
# -----------------------------------------------------------------------------

class TestNoPersistence:
    def test_parse_does_not_write_any_file(self, sample_csv: Path, tmp_path: Path) -> None:
        before = set(tmp_path.rglob("*"))
        _ = parse_schwab_csv(sample_csv)
        after = set(tmp_path.rglob("*"))
        assert before == after  # no new files created

    def test_no_open_write_in_portfolio_py(self) -> None:
        src = Path("src/alphaswarm/portfolio.py").read_text(encoding="utf-8")
        assert ".write_text(" not in src
        assert ".write_bytes(" not in src
        assert 'json.dump' not in src
        # No write-mode open calls
        assert "open(" not in src or "open(path," not in src


class TestNoIndividualLogging:
    def test_log_call_sites_do_not_reference_individual_keys(self) -> None:
        """Log messages must only surface counts and path — never ticker/value details."""
        src = Path("src/alphaswarm/portfolio.py").read_text(encoding="utf-8")
        # The only log.info call should carry equity_count/excluded_count/path
        assert "log.info" in src
        assert 'equity_count=' in src
        assert 'excluded_count=' in src
        # Must not include per-position keys in any log call
        assert 'log.info("schwab_csv_parsed", holding=' not in src
        assert 'log.info("schwab_csv_parsed", tickers=' not in src


# -----------------------------------------------------------------------------
# Word-boundary matching (REVIEWS: MEDIUM consensus — ticker substring collision)
# -----------------------------------------------------------------------------

class TestWordBoundaryMatch:
    def test_arm_does_not_match_alarm(self) -> None:
        entities = [{"entity_name": "Market Alarm System", "avg_sentiment": 0.0,
                     "mention_count": 1, "buy_mentions": 0, "sell_mentions": 0, "hold_mentions": 1}]
        assert _match_entity("ARM", entities) is None

    def test_vrt_does_not_match_advertisement(self) -> None:
        entities = [{"entity_name": "Advertisement Industry", "avg_sentiment": 0.0,
                     "mention_count": 1, "buy_mentions": 0, "sell_mentions": 0, "hold_mentions": 1}]
        assert _match_entity("VRT", entities) is None

    def test_hon_does_not_match_honest(self) -> None:
        entities = [{"entity_name": "Honest Company Inc", "avg_sentiment": 0.0,
                     "mention_count": 1, "buy_mentions": 0, "sell_mentions": 0, "hold_mentions": 1}]
        assert _match_entity("HON", entities) is None

    def test_tln_does_not_match_talent(self) -> None:
        entities = [{"entity_name": "Talent Acquisition Corp", "avg_sentiment": 0.0,
                     "mention_count": 1, "buy_mentions": 0, "sell_mentions": 0, "hold_mentions": 1}]
        assert _match_entity("TLN", entities) is None

    def test_arm_matches_arm_holdings(self) -> None:
        entities = [{"entity_name": "ARM Holdings plc", "avg_sentiment": 0.0,
                     "mention_count": 1, "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0}]
        assert _match_entity("ARM", entities) is not None

    def test_case_insensitive(self) -> None:
        entities = [{"entity_name": "apple inc.", "avg_sentiment": 0.1,
                     "mention_count": 10, "buy_mentions": 5, "sell_mentions": 2, "hold_mentions": 3}]
        assert _match_entity("AAPL", entities) is not None


# -----------------------------------------------------------------------------
# build_portfolio_impact: matched + gap semantics
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBuildPortfolioImpact:
    async def test_matches_aapl_against_entity_impact(self) -> None:
        parse_result = {
            "equity_holdings": {
                "AAPL": {"ticker": "AAPL", "shares": 100.0, "market_value": 26000.0},
            },
            "excluded_holdings": {},
        }
        gm = AsyncMock()
        gm.read_entity_impact.return_value = [
            {
                "entity_name": "Apple Inc",
                "entity_type": "COMPANY",
                "avg_sentiment": 0.43,
                "mention_count": 45,
                "buy_mentions": 30,
                "sell_mentions": 5,
                "hold_mentions": 10,
            },
        ]
        result = await build_portfolio_impact(parse_result, gm, "cycle-1")
        assert len(result["matched_tickers"]) == 1
        assert result["gap_tickers"] == []
        t = result["matched_tickers"][0]
        assert t["ticker"] == "AAPL"
        assert t["signal"] == "BUY"
        assert t["confidence"] == pytest.approx(30 / 45, abs=1e-3)
        assert t["entity_name"] == "Apple Inc"
        assert t["market_value_display"] == "$26,000.00"

    async def test_unmatched_equity_becomes_no_coverage_gap(self) -> None:
        parse_result = {
            "equity_holdings": {
                "AAPL": {"ticker": "AAPL", "shares": 10.0, "market_value": 2600.0},
                "COHR": {"ticker": "COHR", "shares": 5.0, "market_value": 500.0},
            },
            "excluded_holdings": {},
        }
        gm = AsyncMock()
        gm.read_entity_impact.return_value = [
            {"entity_name": "Apple Inc", "avg_sentiment": 0.2,
             "mention_count": 10, "buy_mentions": 6, "sell_mentions": 2, "hold_mentions": 2},
        ]
        result = await build_portfolio_impact(parse_result, gm, "c1")
        gap = next(g for g in result["gap_tickers"] if g["ticker"] == "COHR")
        assert gap["reason"] == REASON_NO_COVERAGE
        assert gap["asset_type"] == "Equity"

    async def test_excluded_etf_appears_as_non_equity_gap(self) -> None:
        parse_result = {
            "equity_holdings": {},
            "excluded_holdings": {
                "QQQ": {
                    "ticker": "QQQ", "shares": 10.0, "market_value": 5000.0,
                    "asset_type": "ETFs & Closed End Funds",
                },
            },
        }
        gm = AsyncMock()
        gm.read_entity_impact.return_value = []
        result = await build_portfolio_impact(parse_result, gm, "c1")
        assert len(result["gap_tickers"]) == 1
        gap = result["gap_tickers"][0]
        assert gap["ticker"] == "QQQ"
        assert gap["reason"] == REASON_NON_EQUITY
        assert gap["asset_type"] == "ETFs & Closed End Funds"

    async def test_excluded_holdings_do_not_count_in_coverage_denominator(self) -> None:
        parse_result = {
            "equity_holdings": {
                "AAPL": {"ticker": "AAPL", "shares": 1.0, "market_value": 100.0},
            },
            "excluded_holdings": {
                "QQQ": {"ticker": "QQQ", "shares": 10.0, "market_value": 5000.0,
                        "asset_type": "ETFs & Closed End Funds"},
                "SPY": {"ticker": "SPY", "shares": 20.0, "market_value": 9000.0,
                        "asset_type": "ETFs & Closed End Funds"},
            },
        }
        gm = AsyncMock()
        gm.read_entity_impact.return_value = [
            {"entity_name": "Apple Inc", "avg_sentiment": 0.1,
             "mention_count": 5, "buy_mentions": 3, "sell_mentions": 1, "hold_mentions": 1},
        ]
        result = await build_portfolio_impact(parse_result, gm, "c1")
        assert result["coverage_summary"]["total_equity_holdings"] == 1
        assert result["coverage_summary"]["covered"] == 1
        assert result["coverage_summary"]["coverage_pct"] == 100.0
        # Gap tickers include both ETFs
        gap_tickers = {g["ticker"] for g in result["gap_tickers"]}
        assert gap_tickers == {"QQQ", "SPY"}

    async def test_coverage_summary_zero_equity(self) -> None:
        parse_result = {"equity_holdings": {}, "excluded_holdings": {}}
        gm = AsyncMock()
        gm.read_entity_impact.return_value = []
        result = await build_portfolio_impact(parse_result, gm, "c1")
        assert result["coverage_summary"]["coverage_pct"] == 0.0
        assert result["matched_tickers"] == []
        assert result["gap_tickers"] == []

    async def test_ticker_not_in_map_becomes_no_coverage_gap(self) -> None:
        parse_result = {
            "equity_holdings": {
                "ZZZX": {"ticker": "ZZZX", "shares": 1.0, "market_value": 10.0},
            },
            "excluded_holdings": {},
        }
        gm = AsyncMock()
        gm.read_entity_impact.return_value = [
            {"entity_name": "ZZZX Corporation", "avg_sentiment": 0.0,
             "mention_count": 1, "buy_mentions": 0, "sell_mentions": 0, "hold_mentions": 1},
        ]
        result = await build_portfolio_impact(parse_result, gm, "c1")
        assert len(result["gap_tickers"]) == 1
        assert result["gap_tickers"][0]["reason"] == REASON_NO_COVERAGE
        assert result["matched_tickers"] == []

    async def test_async_parser_wrapper(self, tmp_path: Path) -> None:
        p = tmp_path / "sample.csv"
        p.write_text(SAMPLE_CSV, encoding="utf-8")
        result = await parse_schwab_csv_async(p)
        assert "AAPL" in result["equity_holdings"]


# -----------------------------------------------------------------------------
# Majority signal tie-breaker (REPLAN-8, Gemini MEDIUM)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMajoritySignalTieBreaker:
    async def _run(self, buy: int, sell: int, hold: int) -> dict:
        parse_result = {
            "equity_holdings": {
                "AAPL": {"ticker": "AAPL", "shares": 1.0, "market_value": 100.0},
            },
            "excluded_holdings": {},
        }
        gm = AsyncMock()
        gm.read_entity_impact.return_value = [
            {
                "entity_name": "Apple Inc",
                "avg_sentiment": 0.0,
                "mention_count": buy + sell + hold,
                "buy_mentions": buy,
                "sell_mentions": sell,
                "hold_mentions": hold,
            },
        ]
        result = await build_portfolio_impact(parse_result, gm, "c1")
        return result["matched_tickers"][0]

    async def test_all_three_tied_prefers_hold(self) -> None:
        """Three-way tie: HOLD > SELL > BUY wins."""
        m = await self._run(5, 5, 5)
        assert m["signal"] == "HOLD"

    async def test_buy_sell_tied_hold_lower_prefers_sell(self) -> None:
        """Two-way tie between BUY/SELL (both above HOLD): SELL wins."""
        m = await self._run(10, 10, 2)
        assert m["signal"] == "SELL"

    async def test_sell_hold_tied_buy_lower_prefers_hold(self) -> None:
        """Two-way tie between SELL/HOLD (both above BUY): HOLD wins."""
        m = await self._run(2, 10, 10)
        assert m["signal"] == "HOLD"

    async def test_buy_hold_tied_sell_lower_prefers_hold(self) -> None:
        """Two-way tie between BUY/HOLD (both above SELL): HOLD wins."""
        m = await self._run(10, 2, 10)
        assert m["signal"] == "HOLD"

    async def test_clear_buy_winner(self) -> None:
        """No tie: BUY is strict max, BUY wins."""
        m = await self._run(15, 3, 3)
        assert m["signal"] == "BUY"


# -----------------------------------------------------------------------------
# Multi-word entity matching edge cases (REPLAN-9, Codex MEDIUM)
# -----------------------------------------------------------------------------

class TestMultiWordEntityMatching:
    """REPLAN-9: verify word-boundary regex handles punctuation and multi-word
    entity names correctly for SCHW, HIMS, TSM, BYDDY, NIO, ARM."""

    def test_schw_matches_charles_schwab_corporation(self) -> None:
        entities = [{
            "entity_name": "Charles Schwab Corporation",
            "avg_sentiment": 0.0, "mention_count": 1,
            "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0,
        }]
        assert _match_entity("SCHW", entities) is not None

    def test_hims_matches_hims_and_hers(self) -> None:
        """Ampersand in entity name must not break word-boundary match."""
        entities = [{
            "entity_name": "Hims & Hers Health Inc",
            "avg_sentiment": 0.0, "mention_count": 1,
            "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0,
        }]
        assert _match_entity("HIMS", entities) is not None

    def test_tsm_matches_taiwan_semiconductor(self) -> None:
        entities = [{
            "entity_name": "Taiwan Semiconductor Manufacturing Co",
            "avg_sentiment": 0.0, "mention_count": 1,
            "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0,
        }]
        assert _match_entity("TSM", entities) is not None

    def test_byddy_matches_byd_company(self) -> None:
        entities = [{
            "entity_name": "BYD Company Limited",
            "avg_sentiment": 0.0, "mention_count": 1,
            "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0,
        }]
        assert _match_entity("BYDDY", entities) is not None

    def test_nio_matches_nio_inc_with_period(self) -> None:
        entities = [{
            "entity_name": "Nio Inc.",
            "avg_sentiment": 0.0, "mention_count": 1,
            "buy_mentions": 1, "sell_mentions": 0, "hold_mentions": 0,
        }]
        assert _match_entity("NIO", entities) is not None

    def test_schw_does_not_match_bare_schwarz(self) -> None:
        """Negative: 'Schwarz' is a substring of 'Schwab' would fail only via
        naive matching; but note that neither map key matches. This test
        ensures nothing matches when no canonical disambiguation applies."""
        entities = [{
            "entity_name": "Schwarz Gruppe",
            "avg_sentiment": 0.0, "mention_count": 1,
            "buy_mentions": 0, "sell_mentions": 0, "hold_mentions": 1,
        }]
        assert _match_entity("SCHW", entities) is None


# -----------------------------------------------------------------------------
# Async wrapper uses asyncio.to_thread (REPLAN-1, consensus MEDIUM)
# -----------------------------------------------------------------------------

class TestAsyncWrapperUsesToThread:
    """REPLAN-1: parse_schwab_csv_async MUST be implemented via asyncio.to_thread
    to keep the synchronous csv.DictReader off the event loop."""

    def test_async_wrapper_uses_to_thread(self) -> None:
        src = Path("src/alphaswarm/portfolio.py").read_text(encoding="utf-8")
        assert "async def parse_schwab_csv_async" in src
        # The wrapper body MUST contain asyncio.to_thread — verify lexically.
        start = src.index("async def parse_schwab_csv_async")
        # Find the next blank-line separator that ends the function body
        end = src.index("\n\n\n", start) if "\n\n\n" in src[start:] else len(src)
        block = src[start:end]
        assert "asyncio.to_thread" in block, (
            "parse_schwab_csv_async must use asyncio.to_thread to avoid "
            "blocking the event loop on csv.DictReader (REPLAN-1)"
        )


# -----------------------------------------------------------------------------
# TICKER_ENTITY_MAP coverage
# -----------------------------------------------------------------------------

class TestTickerEntityMap:
    def test_contains_all_25_equities(self) -> None:
        expected = {
            "AAPL","AMZN","ARM","ASML","AVGO","BYDDY","COHR","DBX","HIMS","HON",
            "ISRG","LPL","MRVL","NIO","NKE","NVDA","PLTR","PYPL","SCHW","SOFI",
            "TLN","TSLA","TSM","VRT","VST",
        }
        assert set(TICKER_ENTITY_MAP.keys()) == expected

    def test_every_value_is_non_empty_list(self) -> None:
        for ticker, substrings in TICKER_ENTITY_MAP.items():
            assert isinstance(substrings, list) and len(substrings) >= 1, ticker

    def test_short_tickers_have_qualified_names(self) -> None:
        """Short tickers (3 chars or less) must use multi-word names to avoid collision."""
        for ticker in ("ARM", "HON", "NIO", "TLN", "VRT"):
            substrings = TICKER_ENTITY_MAP[ticker]
            assert any(" " in s for s in substrings), (
                f"{ticker} needs at least one multi-word substring to disambiguate"
            )
