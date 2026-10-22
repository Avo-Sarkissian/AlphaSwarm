"""Advisory LLM prompt builder — pure function, no I/O, mypy-strict-friendly.

Pitfall 1 mitigation: the builder NEVER accepts a PortfolioSnapshot directly.
Callers pass one dict per held ticker (the ticker plus sector tags); quantities
and cost basis never reach the prompt (docs/DECISIONS.md#p41-d-05).
Pitfall 2 mitigation: all Decimal values arrive as strings; this module never
invokes json.dumps over raw Decimal.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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
      "position_exposure": "0"                // always "0"; the engine fills in the real exposure
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

The portfolio block lists the held tickers with sector tags only; quantities and
cost basis are never shared with you, so do not guess them.

DO NOT output markdown, commentary, or fields outside this schema. Only return
the JSON object."""


_WORKED_EXAMPLE = """EXAMPLE (shape only — use the real data below for the actual output):
{
  "cycle_id": "abc12345",
  "generated_at": "2026-04-19T22:00:00+00:00",
  "portfolio_outlook": "The swarm converged BUY on industrial automation... ...",
  "items": [
    {"ticker": "ZZZT", "consensus_signal": "BUY", "confidence": 0.82,
     "rationale_summary": "Order-book strength reiterated across Quants and Sell-Side.",
     "position_exposure": "0"}
  ],
  "total_holdings": 7,
  "affected_holdings": 1
}"""


def build_advisory_prompt(
    *,
    cycle_id: str,
    seed_rumor: str,
    bracket_summary: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    narratives: Sequence[Mapping[str, Any]],
    entity_impact: Sequence[Mapping[str, Any]],
    top_holdings: list[dict[str, Any]],
) -> list[InferenceMessage]:
    """Build the advisory synthesis messages list (system + user).

    All Decimal values in `top_holdings` are already stringified by the caller
    (docs/DECISIONS.md#p41-d-06). Neo4j payloads are serialized with default=str
    to absorb any Decimal in sentiment/confidence fields.

    Only `top_holdings` (the enriched conviction subset) is sent to the LLM.
    engine.py pads every other holding server-side with HOLD@0.30, so the user
    still sees a full portfolio view without spending prompt tokens on no-signal
    HOLD boilerplate (docs/DECISIONS.md#sweep-b-7).
    """
    system = _SYSTEM_INSTRUCTIONS + "\n\n" + _WORKED_EXAMPLE
    portfolio_block_lines = [
        f"USER PORTFOLIO — {len(top_holdings)} sector-enriched conviction "
        "candidates (engine pads no-signal holdings server-side):",
        "",
        json.dumps(top_holdings, default=str),
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
