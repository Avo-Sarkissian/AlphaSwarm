"""Advisory LLM prompt builder — pure function, no I/O, mypy-strict-friendly.

Pitfall 1 mitigation: the builder NEVER accepts a PortfolioSnapshot directly.
Callers MUST pre-serialize to minimal dicts (ticker/qty/cost_basis as strings).
Pitfall 2 mitigation: all Decimal values arrive as strings; this module never
invokes json.dumps over raw Decimal.
"""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_INSTRUCTIONS = """You are the orchestrator of a 100-agent AI trading swarm.
A simulation cycle has just completed. Using the prefetched swarm data and the
user's portfolio, produce a JSON advisory with the EXACT schema below.

SCHEMA:
{
  "cycle_id": string,
  "generated_at": ISO-8601 UTC string,
  "portfolio_outlook": string (1-3 thorough paragraphs covering the swarm's
                               overall market reading and its implications for
                               this portfolio — substantive, NOT a one-liner),
  "items": [
    {
      "ticker": string,                       // exact ticker as supplied in holdings
      "consensus_signal": "BUY" | "SELL" | "HOLD",
      "confidence": number in [0.0, 1.0],
      "rationale_summary": string (1-2 sentences),
      "position_exposure": string (Decimal cost_basis for this holding)
    }
  ],
  "total_holdings": integer (count of holdings supplied),
  "affected_holdings": integer
}

CRITICAL — ONE ITEM PER HOLDING. NEVER OMIT A HOLDING.
For every holding in the USER PORTFOLIO list below you MUST emit one
items[] entry. The user wants to see their FULL portfolio context, even
where the swarm has no strong directional view.

For holdings without a clear directional signal from the swarm, use:
    consensus_signal = "HOLD"
    confidence in the range 0.20..0.40 (placeholder for low-conviction)
    rationale_summary = a brief note that no strong signal emerged.

Strong-conviction items (BUY/SELL with confidence > 0.4 OR any non-HOLD
signal) still drive the headline narrative in portfolio_outlook.

`affected_holdings` is the COUNT of items where consensus_signal != "HOLD"
OR confidence > 0.4 — i.e. items with a directional or high-conviction
view. It is DISTINCT from total_holdings (which equals len(items) when
the one-item-per-holding rule is honored).

DO NOT output markdown, commentary, or fields outside this schema. Only return
the JSON object."""


_WORKED_EXAMPLE = """EXAMPLE (shape only — use the real data below for the actual output):
{
  "cycle_id": "abc12345",
  "generated_at": "2026-04-19T22:00:00+00:00",
  "portfolio_outlook": "The swarm converged BUY on AI infrastructure... ...",
  "items": [
    {"ticker": "NVDA", "consensus_signal": "BUY", "confidence": 0.82,
     "rationale_summary": "Data-center demand reiterated across Quants and Whales.",
     "position_exposure": "12500.00"}
  ],
  "total_holdings": 7,
  "affected_holdings": 1
}"""


def build_advisory_prompt(
    *,
    cycle_id: str,
    seed_rumor: str,
    bracket_summary: dict[str, Any],
    timeline: list[dict[str, Any]],
    narratives: list[dict[str, Any]],
    entity_impact: list[dict[str, Any]],
    holdings: list[dict[str, Any]] | None = None,
    top_holdings: list[dict[str, Any]] | None = None,
    rest_holdings: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Build the advisory synthesis messages list (system + user).

    All Decimal values in `holdings` are already stringified by the caller
    (D-06, Pitfall 2). Neo4j payloads are serialized with default=str to
    absorb any Decimal in sentiment/confidence fields.

    ITEM 6 of quick task 260512-jqn: callers may now split the portfolio
    into top_holdings (full enrichment, sent to the LLM with sector fields)
    and rest_holdings (sector tag only, sent to ensure the
    one-item-per-holding rule is honored). The legacy `holdings` kwarg is
    still accepted for callers that don't enrich — those holdings are
    treated as top_holdings with no enrichment data.
    """
    # Resolve which holdings list(s) to render. Order of precedence:
    #   1. Explicit top_holdings + rest_holdings (preferred — engine.py path).
    #   2. Legacy `holdings` alone — treated as a single un-split list.
    resolved_top = top_holdings if top_holdings is not None else (holdings or [])
    resolved_rest = rest_holdings if rest_holdings is not None else []
    total_count = len(resolved_top) + len(resolved_rest)

    system = _SYSTEM_INSTRUCTIONS + "\n\n" + _WORKED_EXAMPLE
    portfolio_block_lines = [
        f"USER PORTFOLIO — {total_count} holdings (one items[] entry per holding REQUIRED):",
        "",
        "TOP HOLDINGS (sector-enriched — focus your conviction items here):",
        json.dumps(resolved_top, default=str),
    ]
    if resolved_rest:
        portfolio_block_lines.extend(
            [
                "",
                "OTHER HOLDINGS (sector tag only — emit HOLD@0.20-0.40 if no strong view):",
                json.dumps(resolved_rest, default=str),
            ]
        )
    user = "\n".join(
        [
            f"CYCLE_ID: {cycle_id}",
            f"SEED_RUMOR: {seed_rumor}",
            "",
            "PREFETCHED SWARM DATA:",
            f"  bracket_summary: {json.dumps(bracket_summary, default=str)}",
            f"  round_timeline: {json.dumps(timeline, default=str)}",
            f"  bracket_narratives: {json.dumps(narratives, default=str)}",
            f"  entity_impact: {json.dumps(entity_impact, default=str)}",
            "",
            *portfolio_block_lines,
            "",
            "Return the JSON advisory now.",
        ]
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
