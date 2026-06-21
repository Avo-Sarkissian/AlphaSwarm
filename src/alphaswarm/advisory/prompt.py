"""Advisory LLM prompt builder — pure function, no I/O, mypy-strict-friendly.

Pitfall 1 mitigation: the builder NEVER accepts a PortfolioSnapshot directly.
Callers MUST pre-serialize to minimal dicts (ticker/qty/cost_basis as strings).
Pitfall 2 mitigation: all Decimal values arrive as strings; this module never
invokes json.dumps over raw Decimal.
"""
from __future__ import annotations

import json
from typing import Any

from alphaswarm.inference.types import InferenceMessage

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

EMIT CONVICTION ITEMS ONLY.
Emit one items[] entry for each holding where the swarm produced a CLEAR
directional view — BUY/SELL signal, or HOLD with confidence > 0.4.
Skip holdings the swarm had no strong view on; the engine pads those in
after you return so the user still sees their full portfolio. This saves
prompt tokens for the conviction cases you DO have something to say about.

`affected_holdings` = count of items you actually emit.
`total_holdings` will be overwritten by the engine to match the full
portfolio count; emit whatever — it will be replaced.

DO NOT output markdown, commentary, or fields outside this schema. Only return
the JSON object."""


_WORKED_EXAMPLE = """EXAMPLE (shape only — use the real data below for the actual output):
{
  "cycle_id": "abc12345",
  "generated_at": "2026-04-19T22:00:00+00:00",
  "portfolio_outlook": "The swarm converged BUY on AI infrastructure... ...",
  "items": [
    {"ticker": "NVDA", "consensus_signal": "BUY", "confidence": 0.82,
     "rationale_summary": "Data-center demand reiterated across Quants and Sell-Side.",
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
) -> list[InferenceMessage]:
    """Build the advisory synthesis messages list (system + user).

    All Decimal values in `holdings` are already stringified by the caller
    (D-06, Pitfall 2). Neo4j payloads are serialized with default=str to
    absorb any Decimal in sentiment/confidence fields.

    Only `top_holdings` (or legacy `holdings`) is sent to the LLM — the rest
    of the portfolio is padded server-side with HOLD@0.30 by `engine.py` so
    the user still sees a full portfolio view without burning prompt tokens
    on no-signal HOLD boilerplate (SWEEP-260528 B-7). `rest_holdings` is still
    accepted for backward compatibility but is now ignored.
    """
    # Only the enriched conviction subset reaches the LLM. Anything outside
    # this list is filled in by engine.py after the LLM returns.
    resolved_top = top_holdings if top_holdings is not None else (holdings or [])
    _ = rest_holdings  # accepted for back-compat, intentionally unused

    system = _SYSTEM_INSTRUCTIONS + "\n\n" + _WORKED_EXAMPLE
    portfolio_block_lines = [
        f"USER PORTFOLIO — {len(resolved_top)} sector-enriched conviction "
        "candidates (engine pads no-signal holdings server-side):",
        "",
        json.dumps(resolved_top, default=str),
    ]
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
