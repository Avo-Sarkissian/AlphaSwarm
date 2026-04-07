"""Bracket-tailored market data enrichment for agent prompts (Phase 18).

Provides format_market_block() and build_enriched_user_message() for injecting
bracket-specific market data into agent prompt context. Each bracket group
(Technicals, Fundamentals, Earnings/Insider) sees a different slice of data
formatted as compact key-value strings under a per-bracket char cap.
"""

from __future__ import annotations

import structlog

from alphaswarm.types import BracketType, MarketDataSnapshot

logger = structlog.get_logger(component="enrichment")

# ---------------------------------------------------------------------------
# Bracket slice groupings (D-04)
# ---------------------------------------------------------------------------
# NOTE re: Codex review blocker #2 (Macro-agent spec mismatch):
# ROADMAP says "Macro agents see sector-level data" but CONTEXT.md D-04 (locked)
# places Macro in Earnings/Insider slice. D-04 governs. The Earnings/Insider slice
# provides macro-relevant data (earnings surprises, EPS, market cap, news headlines)
# which IS how Macro analysts assess sectors. No contradiction.

TECHNICALS_BRACKETS: frozenset[BracketType] = frozenset({
    BracketType.QUANTS, BracketType.DEGENS, BracketType.WHALES,
})
FUNDAMENTALS_BRACKETS: frozenset[BracketType] = frozenset({
    BracketType.SUITS, BracketType.SOVEREIGNS, BracketType.POLICY_WONKS,
})
EARNINGS_INSIDER_BRACKETS: frozenset[BracketType] = frozenset({
    BracketType.INSIDERS, BracketType.MACRO, BracketType.AGENTS, BracketType.DOOM_POSTERS,
})

# ---------------------------------------------------------------------------
# Per-bracket char caps (D-03)
# ---------------------------------------------------------------------------

MAX_MARKET_BLOCK_CHARS: dict[BracketType, int] = {}
for _bt in TECHNICALS_BRACKETS:
    MAX_MARKET_BLOCK_CHARS[_bt] = 900
for _bt in FUNDAMENTALS_BRACKETS:
    MAX_MARKET_BLOCK_CHARS[_bt] = 1000
for _bt in EARNINGS_INSIDER_BRACKETS:
    MAX_MARKET_BLOCK_CHARS[_bt] = 2000


# ---------------------------------------------------------------------------
# Human-readable number formatting
# ---------------------------------------------------------------------------

def _format_large_number(value: float | None) -> str:
    """Format large numbers with human-readable suffixes ($3.0T, $400B, $97B)."""
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.1f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.0f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.0f}M"
    return f"{sign}${abs_val:,.0f}"


def _fmt(value: float | None, fmt_str: str) -> str:
    """Format a float or return 'N/A' if None."""
    if value is None:
        return "N/A"
    return fmt_str.format(value)


# ---------------------------------------------------------------------------
# Slice formatters
# ---------------------------------------------------------------------------

def _format_technicals(symbol: str, snap: MarketDataSnapshot) -> str:
    """Technical analysis slice: price, momentum, volume, range."""
    close = _fmt(snap.last_close, "${:.2f}")
    d30 = _fmt(snap.price_change_30d_pct, "{:+.1f}%")
    d90 = _fmt(snap.price_change_90d_pct, "{:+.1f}%")
    vol = "N/A" if snap.avg_volume_30d is None else f"{snap.avg_volume_30d / 1e6:.1f}M"
    lo = _fmt(snap.fifty_two_week_low, "${:.2f}")
    hi = _fmt(snap.fifty_two_week_high, "${:.2f}")
    return f"{symbol}: close={close}, 30d={d30}, 90d={d90}, vol={vol}, 52w=[{lo}/{hi}]"


def _format_fundamentals(symbol: str, snap: MarketDataSnapshot) -> str:
    """Fundamental analysis slice: valuation, revenue, margins, leverage."""
    pe = _fmt(snap.pe_ratio, "{:.1f}")
    cap = _format_large_number(snap.market_cap)
    rev = _format_large_number(snap.revenue_ttm)
    margin = _fmt(snap.gross_margin_pct, "{:.1f}%")
    de = _fmt(snap.debt_to_equity, "{:.1f}")
    return f"{symbol}: PE={pe}, mktcap={cap}, rev={rev}, margin={margin}, D/E={de}"


def _format_earnings_insider_base(symbol: str, snap: MarketDataSnapshot) -> str:
    """Earnings/insider base line (without headlines)."""
    surprise = _fmt(snap.earnings_surprise_pct, "{:+.1f}%")
    next_earn = snap.next_earnings_date or "N/A"
    eps = _fmt(snap.eps_trailing, "${:.2f}")
    cap = _format_large_number(snap.market_cap)
    return f"{symbol}: surprise={surprise}, next_earnings={next_earn}, EPS={eps}, mktcap={cap}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_market_block(
    snapshots: dict[str, MarketDataSnapshot],
    bracket: BracketType,
) -> str:
    """Format market data for a specific bracket's prompt context.

    Args:
        snapshots: Map of ticker symbol -> MarketDataSnapshot.
        bracket: The agent's bracket type, determines which data slice to show.

    Returns:
        Formatted market data block string, or "" if snapshots is empty.
    """
    if not snapshots:
        return ""

    # Determine slice category
    if bracket in TECHNICALS_BRACKETS:
        lines = ["--- Market Data ---"]
        for symbol in sorted(snapshots):
            lines.append(_format_technicals(symbol, snapshots[symbol]))
        block = "\n".join(lines)

    elif bracket in FUNDAMENTALS_BRACKETS:
        lines = ["--- Market Data ---"]
        for symbol in sorted(snapshots):
            lines.append(_format_fundamentals(symbol, snapshots[symbol]))
        block = "\n".join(lines)

    elif bracket in EARNINGS_INSIDER_BRACKETS:
        # Two-pass: first format base lines, then distribute headline budget
        header = "--- Market Data ---"
        sorted_symbols = sorted(snapshots)

        # Pass 1: Build base lines (structured fields, no headlines)
        base_lines: list[str] = []
        for symbol in sorted_symbols:
            base_lines.append(_format_earnings_insider_base(symbol, snapshots[symbol]))

        base_block = header + "\n" + "\n".join(base_lines)
        cap = MAX_MARKET_BLOCK_CHARS.get(bracket, 2000)
        remaining_budget = cap - len(base_block)

        # Pass 2: Distribute remaining budget across tickers for headlines
        headline_lines: list[str] = []
        if remaining_budget > 50:  # Only add headlines if meaningful budget remains
            tickers_with_headlines = [
                s for s in sorted_symbols if snapshots[s].headlines
            ]
            if tickers_with_headlines:
                per_ticker_budget = remaining_budget // len(tickers_with_headlines)
                for symbol in tickers_with_headlines:
                    snap = snapshots[symbol]
                    selected: list[str] = []
                    used = 0
                    prefix = f"\n{symbol} Headlines: "
                    used += len(prefix)
                    for hl in snap.headlines:
                        truncated_hl = hl[:120]
                        entry_len = len(truncated_hl) + 3  # " | " separator
                        if used + entry_len > per_ticker_budget:
                            break
                        selected.append(truncated_hl)
                        used += entry_len
                    if selected:
                        headline_lines.append(
                            f"{symbol} Headlines: {' | '.join(selected)}"
                        )

        all_lines = [header] + base_lines + headline_lines
        block = "\n".join(all_lines)

    else:
        # Fallback: treat as technicals for unknown brackets
        lines = ["--- Market Data ---"]
        for symbol in sorted(snapshots):
            lines.append(_format_technicals(symbol, snapshots[symbol]))
        block = "\n".join(lines)

    # Truncate to char cap using line-boundary truncation
    limit = MAX_MARKET_BLOCK_CHARS.get(bracket, 1000)
    if len(block) > limit:
        truncated = block[:limit]
        # Cut at last newline to avoid mid-line truncation
        last_nl = truncated.rfind("\n")
        if last_nl > 0:
            block = truncated[:last_nl]
        else:
            block = truncated
        logger.warning(
            "market_block_truncated",
            bracket=bracket.value,
            original_len=len(block),
            cap=limit,
        )

    return block


def build_enriched_user_message(
    rumor: str,
    snapshots: dict[str, MarketDataSnapshot],
    bracket: BracketType,
) -> str:
    """Build the enriched user message with market data context (D-01).

    Args:
        rumor: The raw rumor text.
        snapshots: Map of ticker symbol -> MarketDataSnapshot.
        bracket: The agent's bracket type.

    Returns:
        Enriched message with market data block prepended, or bare rumor
        if snapshots is empty.
    """
    block = format_market_block(snapshots, bracket)
    if not block:
        return rumor
    return f"{block}\n\nRumor: {rumor}"
