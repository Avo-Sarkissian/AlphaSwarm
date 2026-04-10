"""Portfolio CSV parsing and ticker-entity bridge for Phase 25.

Per CONTEXT.md D-05, holdings are loaded in-memory only and never persisted to
Neo4j or disk. Per D-06, D-07, D-08, the bridge is a case-insensitive
WORD-BOUNDARY regex match between TICKER_ENTITY_MAP values and entity_name from
read_entity_impact(). Per REVIEWS.md consensus concerns, this module:

- Uses word-boundary matching (\\b...\\b) to prevent substring false positives
  (e.g., "ARM" must not match "ALARM")
- Preserves non-equity holdings in excluded_holdings so they appear in gaps
  with reason="non_equity"
- Aggregates duplicate ticker rows deterministically
- Reads CSV with encoding='utf-8-sig' to handle BOM
- Dynamically detects the header row (not hardcoded to row index 2)
- Uses TypedDict contracts for strict typing per CLAUDE.md
- Never logs individual ticker/position values — only counts and paths
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import structlog

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager

log = structlog.get_logger(component="portfolio")

# -----------------------------------------------------------------------------
# TypedDict contracts (strict typing per CLAUDE.md)
# -----------------------------------------------------------------------------


class Holding(TypedDict):
    ticker: str
    shares: float
    market_value: float


class ExcludedHolding(TypedDict):
    ticker: str
    shares: float
    market_value: float
    asset_type: str


class PortfolioParseResult(TypedDict):
    equity_holdings: dict[str, Holding]
    excluded_holdings: dict[str, ExcludedHolding]


class MatchedPortfolioTicker(TypedDict):
    ticker: str
    shares: float
    market_value: float
    market_value_display: str
    signal: str
    confidence: float
    entity_name: str
    avg_sentiment: float
    mention_count: int


class PortfolioGap(TypedDict):
    ticker: str
    shares: float
    market_value: float
    market_value_display: str
    reason: str  # "no_simulation_coverage" | "non_equity"
    asset_type: str


class CoverageSummary(TypedDict):
    covered: int
    total_equity_holdings: int
    coverage_pct: float


class PortfolioImpact(TypedDict):
    matched_tickers: list[MatchedPortfolioTicker]
    gap_tickers: list[PortfolioGap]
    coverage_summary: CoverageSummary


class PortfolioParseError(ValueError):
    """Raised when a Schwab CSV cannot be parsed (missing header, bad format)."""


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Schwab CSV column names (verified from Individual-Positions-2026-04-09-154713.csv)
COLUMN_SYMBOL = "Symbol"
COLUMN_QTY = "Qty (Quantity)"
COLUMN_MKT_VAL = "Mkt Val (Market Value)"
COLUMN_ASSET_TYPE = "Asset Type"

_SENTINEL_SYMBOLS = frozenset({"Positions Total", "Cash & Cash Investments", ""})
_UNPARSEABLE_CURRENCY = frozenset({"", "--", "N/A", "n/a", "NA"})
_HEADER_SCAN_MAX_LINES = 5  # Review fix: dynamic header detection

# Reason codes for PortfolioGap.reason
REASON_NO_COVERAGE = "no_simulation_coverage"
REASON_NON_EQUITY = "non_equity"

# REPLAN-8: Majority signal tie-breaker — conservative default (HOLD > SELL > BUY).
# When two or more of (buy_mentions, sell_mentions, hold_mentions) are tied at the
# max, iterate this tuple in order and pick the first one whose count equals the
# max. This avoids depending on dict insertion order for determinism.
TIE_BREAKER_ORDER: tuple[str, ...] = ("HOLD", "SELL", "BUY")

# TICKER_ENTITY_MAP — per CONTEXT D-06/D-09. Maps ticker -> list of canonical
# name substrings to match via WORD-BOUNDARY regex against entity_name values
# from GraphStateManager.read_entity_impact(). Word-boundary matching prevents
# short tickers (ARM, VRT, NIO, HON) from matching unrelated words (per
# REVIEWS.md MEDIUM consensus concern).
TICKER_ENTITY_MAP: dict[str, list[str]] = {
    "AAPL": ["Apple"],
    "AMZN": ["Amazon"],
    "ARM": ["Arm Holdings", "ARM Holdings"],   # explicit to avoid 'alarm'
    "ASML": ["ASML"],
    "AVGO": ["Broadcom"],
    "BYDDY": ["BYD"],
    "COHR": ["Coherent"],
    "DBX": ["Dropbox"],
    "HIMS": ["Hims & Hers", "Hims"],
    "HON": ["Honeywell International", "Honeywell"],  # explicit to avoid 'honest'
    "ISRG": ["Intuitive Surgical"],
    "LPL": ["LG Display"],
    "MRVL": ["Marvell"],
    "NIO": ["NIO Inc", "Nio Inc"],             # explicit to avoid 'bionic'
    "NKE": ["Nike"],
    "NVDA": ["NVIDIA", "Nvidia"],
    "PLTR": ["Palantir"],
    "PYPL": ["PayPal", "Paypal"],
    "SCHW": ["Charles Schwab", "Schwab"],
    "SOFI": ["SoFi", "Sofi Technologies"],
    "TLN": ["Talen Energy"],                   # explicit to avoid 'talent'
    "TSLA": ["Tesla"],
    "TSM": ["Taiwan Semiconductor", "TSMC"],
    "VRT": ["Vertiv Holdings", "Vertiv"],      # explicit to avoid 'advert'
    "VST": ["Vistra"],
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _parse_currency(raw: str) -> float:
    """Parse a Schwab-formatted currency string to float.

    Handles: "$26,416.56 " (trailing space), "($4,472.00)" (parens-negative),
    "1,000.00" (no $), "" (empty), "--" (Schwab dash), "N/A" (explicit NA).
    Returns 0.0 for any unparseable value per REVIEWS.md currency edge case.
    """
    s = raw.strip()
    if s in _UNPARSEABLE_CURRENCY:
        return 0.0
    # Parens => negative
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_quantity(raw: str) -> float:
    """Parse a Schwab-formatted quantity string to float (handles thousands-sep)."""
    s = raw.strip().replace(",", "")
    if not s or s in _UNPARSEABLE_CURRENCY:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_header_row(lines: list[str]) -> int:
    """Locate the Schwab CSV header row by scanning the first N lines.

    Searches for a row containing both 'Symbol' AND 'Asset Type' as quoted
    columns. This is more robust than hardcoding row index 2, addressing the
    Gemini LOW-severity concern about Schwab format drift.

    Returns: 0-based line index of the header row.
    Raises: PortfolioParseError if no header row is found within N lines.
    """
    for idx, line in enumerate(lines[:_HEADER_SCAN_MAX_LINES]):
        if '"Symbol"' in line and '"Asset Type"' in line:
            return idx
        if "Symbol" in line and "Asset Type" in line:
            return idx
    raise PortfolioParseError(
        f"Schwab CSV header row not found in first {_HEADER_SCAN_MAX_LINES} lines "
        f"(expected a row containing both 'Symbol' and 'Asset Type' columns)"
    )


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def parse_schwab_csv(path: Path) -> PortfolioParseResult:
    """Parse a Schwab Individual-Positions CSV export into an in-memory result.

    Per CONTEXT.md D-01..D-05 and REVIEWS.md consensus fixes:
      - Reads with encoding='utf-8-sig' (handles BOM from Excel exports)
      - Dynamically detects the header row (scans first 5 lines)
      - Separates equity rows into equity_holdings and non-equity rows into
        excluded_holdings (so ETFs appear as gaps with reason='non_equity')
      - Aggregates duplicate ticker rows deterministically (sum shares + value)
      - Strips currency formatting ($, commas, spaces, parens, '--', 'N/A')
      - Never persists anything
      - Never logs individual positions (only aggregate counts + path)

    Args:
        path: Path to the Schwab Individual-Positions CSV file.

    Returns:
        PortfolioParseResult with equity_holdings and excluded_holdings dicts.

    Raises:
        PortfolioParseError: If file is too short, header row is missing, or
            the file cannot be read.
        FileNotFoundError: If path does not exist (propagated).
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise PortfolioParseError(f"Could not read portfolio CSV: {exc}") from exc

    lines = text.splitlines()
    if len(lines) < 3:
        raise PortfolioParseError(
            f"Schwab CSV has fewer than 3 lines ({len(lines)}); expected header + data"
        )

    header_idx = _find_header_row(lines)
    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))

    # Validate required columns present after DictReader parses the header
    required_cols = {COLUMN_SYMBOL, COLUMN_QTY, COLUMN_MKT_VAL, COLUMN_ASSET_TYPE}
    missing = required_cols - set(reader.fieldnames or [])
    if missing:
        raise PortfolioParseError(
            f"Schwab CSV missing required columns: {sorted(missing)}"
        )

    equity_holdings: dict[str, Holding] = {}
    excluded_holdings: dict[str, ExcludedHolding] = {}
    skipped_rows = 0

    for row in reader:
        symbol = (row.get(COLUMN_SYMBOL) or "").strip()
        if symbol in _SENTINEL_SYMBOLS:
            continue
        asset_type = (row.get(COLUMN_ASSET_TYPE) or "").strip()
        try:
            shares = _parse_quantity(row.get(COLUMN_QTY) or "")
            market_value = _parse_currency(row.get(COLUMN_MKT_VAL) or "")
        except Exception:  # defensive — _parse_* already swallow ValueError
            skipped_rows += 1
            continue

        if asset_type == "Equity":
            # Aggregate duplicates (MEDIUM Codex concern)
            if symbol in equity_holdings:
                equity_holdings[symbol] = Holding(
                    ticker=symbol,
                    shares=equity_holdings[symbol]["shares"] + shares,
                    market_value=equity_holdings[symbol]["market_value"] + market_value,
                )
            else:
                equity_holdings[symbol] = Holding(
                    ticker=symbol,
                    shares=shares,
                    market_value=market_value,
                )
        else:
            # Preserve as excluded so it appears as a gap with reason='non_equity'
            if symbol in excluded_holdings:
                excluded_holdings[symbol] = ExcludedHolding(
                    ticker=symbol,
                    shares=excluded_holdings[symbol]["shares"] + shares,
                    market_value=excluded_holdings[symbol]["market_value"] + market_value,
                    asset_type=asset_type or "Unknown",
                )
            else:
                excluded_holdings[symbol] = ExcludedHolding(
                    ticker=symbol,
                    shares=shares,
                    market_value=market_value,
                    asset_type=asset_type or "Unknown",
                )

    # Privacy-safe log: counts only, never individual positions
    log.info(
        "schwab_csv_parsed",
        path=str(path),
        equity_count=len(equity_holdings),
        excluded_count=len(excluded_holdings),
        skipped_rows=skipped_rows,
        header_row_index=header_idx,
    )
    return PortfolioParseResult(
        equity_holdings=equity_holdings,
        excluded_holdings=excluded_holdings,
    )


async def parse_schwab_csv_async(path: Path) -> PortfolioParseResult:
    """Async wrapper over parse_schwab_csv — runs file read + parse in a thread."""
    return await asyncio.to_thread(parse_schwab_csv, path)


def _compile_entity_patterns(ticker: str) -> list[re.Pattern[str]]:
    """Compile word-boundary regex patterns for a ticker's TICKER_ENTITY_MAP entries.

    Uses \\b...\\b with re.IGNORECASE to prevent false positives like ARM in ALARM.
    """
    substrings = TICKER_ENTITY_MAP.get(ticker, [])
    return [
        re.compile(rf"\b{re.escape(s)}\b", re.IGNORECASE) for s in substrings
    ]


def _match_entity(
    ticker: str,
    entity_results: list[dict],
) -> dict | None:
    """Find the first entity whose name matches any TICKER_ENTITY_MAP pattern for ticker."""
    patterns = _compile_entity_patterns(ticker)
    if not patterns:
        return None
    for entity in entity_results:
        name = str(entity.get("entity_name", ""))
        for pat in patterns:
            if pat.search(name):
                return entity
    return None


async def build_portfolio_impact(
    parse_result: PortfolioParseResult,
    gm: "GraphStateManager",
    cycle_id: str,
) -> PortfolioImpact:
    """Bridge parsed holdings against swarm entity_impact results.

    Per CONTEXT.md D-07, D-08, D-11 and REVIEWS.md consensus fixes:
      - Fetches entity_impact for the cycle
      - Performs WORD-BOUNDARY regex match using TICKER_ENTITY_MAP
      - Returns PortfolioImpact TypedDict with matched_tickers, gap_tickers,
        coverage_summary
      - gap_tickers contains BOTH unmatched equities AND all excluded holdings
        (non-equity)
      - coverage_summary denominator is len(equity_holdings) only (excluded do
        not count)
      - REPLAN-2: market_value_display is computed HERE for every PortfolioGap
        (bridge phase), not stored on Holding/ExcludedHolding. Templates consume
        PortfolioGap only, never raw ExcludedHolding.
      - REPLAN-4: unmatched equity gaps hardcode asset_type="Equity" (Holding
        has no asset_type field); non-equity gaps copy asset_type from the
        ExcludedHolding entry.
      - REPLAN-5: non-equity holdings are INTENTIONALLY emitted as
        reason="non_equity" gaps so users can distinguish fund wrappers from
        uncovered equity. This is the correct UX per CONTEXT <specifics> L97.
      - REPLAN-8: majority signal tie-breaker is HOLD > SELL > BUY via
        TIE_BREAKER_ORDER (conservative default for ambiguous swarm consensus).

    Args:
        parse_result: Output of parse_schwab_csv (equity_holdings + excluded_holdings).
        gm: GraphStateManager for read_entity_impact().
        cycle_id: Simulation cycle id to query.

    Returns:
        PortfolioImpact TypedDict.
    """
    entity_results = await gm.read_entity_impact(cycle_id)

    equity_holdings = parse_result["equity_holdings"]
    excluded_holdings = parse_result["excluded_holdings"]

    matched: list[MatchedPortfolioTicker] = []
    gaps: list[PortfolioGap] = []

    # Pass 1: equities — match or mark as no_simulation_coverage
    for ticker, pos in equity_holdings.items():
        found_entity = _match_entity(ticker, entity_results)
        market_value = float(pos["market_value"])
        market_value_display = f"${market_value:,.2f}"

        if found_entity is not None:
            buy = int(found_entity.get("buy_mentions", 0))
            sell = int(found_entity.get("sell_mentions", 0))
            hold = int(found_entity.get("hold_mentions", 0))
            counts = {"BUY": buy, "SELL": sell, "HOLD": hold}
            # REPLAN-8: tie-breaker is HOLD > SELL > BUY (conservative default).
            # Iterate TIE_BREAKER_ORDER in order; pick the first signal whose
            # count equals the observed maximum. This ensures deterministic
            # behavior when two or three signals are tied.
            max_count = max(counts.values())
            majority_signal = next(
                sig for sig in TIE_BREAKER_ORDER if counts[sig] == max_count
            )
            total = sum(counts.values())
            confidence = (counts[majority_signal] / total) if total else 0.0
            matched.append(MatchedPortfolioTicker(
                ticker=ticker,
                shares=float(pos["shares"]),
                market_value=market_value,
                market_value_display=market_value_display,
                signal=majority_signal,
                confidence=round(confidence, 3),
                entity_name=str(found_entity.get("entity_name", "")),
                avg_sentiment=round(float(found_entity.get("avg_sentiment", 0.0)), 3),
                mention_count=int(found_entity.get("mention_count", 0)),
            ))
        else:
            # REPLAN-4: unmatched equity branch — hardcode asset_type="Equity"
            # because Holding has no asset_type field (all Holdings come from
            # the equity filter in parse_schwab_csv).
            gaps.append(PortfolioGap(
                ticker=ticker,
                shares=float(pos["shares"]),
                market_value=market_value,
                market_value_display=market_value_display,
                reason=REASON_NO_COVERAGE,
                asset_type="Equity",
            ))

    # Pass 2: non-equity holdings — always gaps with reason='non_equity'.
    # REPLAN-4: non-equity branch copies asset_type from ExcludedHolding entry.
    # REPLAN-2: market_value_display is computed here for every PortfolioGap.
    for ticker, excl in excluded_holdings.items():
        market_value = float(excl["market_value"])
        gaps.append(PortfolioGap(
            ticker=ticker,
            shares=float(excl["shares"]),
            market_value=market_value,
            market_value_display=f"${market_value:,.2f}",
            reason=REASON_NON_EQUITY,
            asset_type=str(excl.get("asset_type", "Unknown")),
        ))

    total_equity = len(equity_holdings)
    covered = len(matched)
    coverage_pct = round(covered / total_equity * 100, 1) if total_equity else 0.0

    return PortfolioImpact(
        matched_tickers=matched,
        gap_tickers=gaps,
        coverage_summary=CoverageSummary(
            covered=covered,
            total_equity_holdings=total_equity,
            coverage_pct=coverage_pct,
        ),
    )
