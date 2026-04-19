"""Pure formatter: ContextPacket -> market_context system-message string.

Separated from simulation.py to keep string-templating logic unit-testable
without pulling the full simulation pipeline fixture set into scope.

Behavior contract (Phase 40 D-03, D-08, D-09, Pitfall 5):
- Silently skips MarketSlice/NewsSlice with staleness='fetch_failed'.
- Emits entities in packet.entities ORDER; skips entities with zero data.
- Returns None (not "") when nothing to emit — callers must NOT append an
  empty "Market context:\\n" system message to prompts.
- Decimal fields render via Decimal.__str__ (financial precision guard).

KNOWN LIMITATION (Phase 40, REVIEWS concern #2):
Entities are joined to market slices by exact string equality between
`entity` (from packet.entities) and `MarketSlice.ticker`. The orchestrator
LLM (seed.py:24) emits human-readable entity names ("NVIDIA", "Apple",
"Federal Reserve"), not ticker symbols ("NVDA", "AAPL"). As a result, for
typical real-world rumors the market block will be empty and the entity
block will contain only news headlines. News attaches correctly because
RSSNewsProvider handles company-name queries natively.

Closing this limitation requires a name-to-ticker resolver (deferred to a
future phase). Until then, agents receive headline context for all
entities, and price/fundamentals only when the orchestrator happens to
emit a ticker-shaped entity (uncommon). The infrastructure is in place:
once a resolver lands, no call-site in Phase 40 changes.
"""
from __future__ import annotations

from alphaswarm.ingestion.types import ContextPacket


def format_market_context(
    packet: ContextPacket, *, budget: int = 4000
) -> str | None:
    """Format a ContextPacket into a human-readable market-context string.

    Args:
        packet: The frozen ContextPacket assembled by run_simulation.
        budget: Maximum character length for the returned string. Greedy
            fill drops entities that would overflow the budget (never
            truncates mid-block). Default 4000 matches _format_peer_context
            and SHOCK_TEXT_MAX_LEN conventions.

    Returns:
        A formatted string containing per-entity price, fundamentals, and
        headline blocks separated by blank lines. Returns None when no
        entity produces a renderable block (all fetch_failed, or every
        entity's data is entirely missing). Callers MUST skip appending a
        system message when the return value is None (Pitfall 5).
    """
    market_by_ticker = {
        s.ticker: s for s in packet.market if s.staleness != "fetch_failed"
    }
    news_by_entity = {
        s.entity: s for s in packet.news if s.staleness != "fetch_failed"
    }

    blocks: list[str] = []
    for entity in packet.entities:
        m = market_by_ticker.get(entity)
        n = news_by_entity.get(entity)
        if m is None and n is None:
            continue

        lines: list[str] = [f"== {entity} =="]
        if m is not None and m.price is not None:
            lines.append(f"Price: ${m.price}")
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
            lines.append("Recent headlines:")
            for headline in n.headlines[:5]:  # D-09
                lines.append(f"  - {headline}")

        # D-08 guard: block must have more than just the header
        if len(lines) <= 1:
            continue

        block = "\n".join(lines)
        candidate = "\n\n".join([*blocks, block])
        if len(candidate) > budget:
            break  # greedy-fill: drop remaining entities
        blocks.append(block)

    return "\n\n".join(blocks) if blocks else None
