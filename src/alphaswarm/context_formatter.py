"""Pure formatter: ContextPacket -> market_context system-message string.

Separated from simulation.py to keep string-templating logic unit-testable
without pulling the full simulation pipeline fixture set into scope.

Behavior contract (Phase 40 D-03, D-08, D-09, Pitfall 5):
- Silently skips MarketSlice/NewsSlice with staleness='fetch_failed'.
- Emits entities in packet.entities order (relevance order) and skips a block that
  would overflow the budget; skips entities with zero data.
- Returns None (not "") when nothing to emit — callers must NOT append an
  empty "Market context:\\n" system message to prompts.
- Decimal fields render via Decimal.__str__ (financial precision guard).
- Headlines are third-party text: each one is passed through
  security.sanitize.sanitize_headline() before rendering (F3), so a published title can
  never forge block structure. Headlines that sanitize to "" are dropped, and
  the "Recent headlines:" label is only emitted when at least one survives.

Prices join their company through ContextPacket.entity_tickers, the swarm-resolved
symbols (docs/DECISIONS.md#adr-ticker-resolution); packets without them fall back to
name == ticker.
"""

from __future__ import annotations

from datetime import UTC
from typing import Final

from alphaswarm.ingestion.types import ContextPacket, MarketSlice
from alphaswarm.security.sanitize import sanitize_headline

# Headlines rendered per entity (docs/DECISIONS.md#p40-d-09). Point-in-time fixtures
# store no more than this, so every stored headline reaches the prompt.
HEADLINES_PER_ENTITY: Final = 5


def _price_line(market: MarketSlice) -> str:
    """'Price: $p' plus the quote time and a stale marker when known (docs/DECISIONS.md#p38-d-09)."""
    notes: list[str] = []
    if market.as_of is not None:
        notes.append(f"as of {market.as_of.astimezone(UTC):%Y-%m-%d %H:%M} UTC")
    if market.staleness == "stale":
        notes.append("stale")
    return f"Price: ${market.price}" + (f" ({', '.join(notes)})" if notes else "")


def format_market_context(packet: ContextPacket, *, budget: int = 4000) -> str | None:
    """Format a ContextPacket into the market-context block, or None when nothing renders.

    Args:
        packet: The frozen ContextPacket assembled by alphaswarm.market_context
            (or a recorded point-in-time fixture).
        budget: Maximum character length for the returned string. A block that
            would overflow it is skipped (never truncated mid-block) and later,
            shorter blocks may still fit. Default 4000 matches format_peer_context
            and SHOCK_TEXT_MAX_LEN conventions.

    Returns:
        Per-entity price, fundamentals and headline blocks separated by blank
        lines, or None when no entity produces a renderable block (all
        fetch_failed, or every entity's data is missing). Callers MUST skip the
        block when the return value is None (Pitfall 5).
    """
    market_by_ticker = {s.ticker: s for s in packet.market if s.staleness != "fetch_failed"}
    news_by_entity = {s.entity: s for s in packet.news if s.staleness != "fetch_failed"}
    tickers = dict(packet.entity_tickers)

    blocks: list[str] = []
    for entity in packet.entities:
        ticker = tickers.get(entity, entity)  # legacy packets: the entity name is the ticker
        m = market_by_ticker.get(ticker)
        n = news_by_entity.get(entity)
        if m is None and n is None:
            continue

        lines: list[str] = [f"== {entity} ({ticker}) ==" if ticker != entity else f"== {entity} =="]
        if m is not None and m.price is not None:
            lines.append(_price_line(m))
        if m is not None and m.fundamentals is not None:
            f = m.fundamentals
            parts: list[str] = []
            if f.pe_ratio is not None:
                parts.append(f"P/E: {f.pe_ratio}")
            if f.eps is not None:
                parts.append(f"EPS: {f.eps}")
            if f.market_cap is not None:
                parts.append(f"Mkt Cap: {f.market_cap}")
            if parts:
                lines.append("Fundamentals: " + ", ".join(parts))
        if n is not None and n.headlines:
            # F3: headlines are third-party text. sanitize_headline() is
            # already applied at ingestion (rss_provider); re-applying here is
            # idempotent and covers any NewsProvider that skips it, so this
            # template can never emit a headline that forges "== ENTITY =="
            # headers, extra "  - " bullets, or the worker's data fence.
            headline_lines = [
                f"  - {clean}" for clean in (sanitize_headline(h) for h in n.headlines[:HEADLINES_PER_ENTITY]) if clean
            ]
            if headline_lines:
                lines.append("Recent headlines:")
                lines.extend(headline_lines)

        # D-08 guard: block must have more than just the header
        if len(lines) <= 1:
            continue

        block = "\n".join(lines)
        if len("\n\n".join([*blocks, block])) > budget:
            continue  # skip this entity; later blocks may still fit
        blocks.append(block)

    return "\n\n".join(blocks) if blocks else None
