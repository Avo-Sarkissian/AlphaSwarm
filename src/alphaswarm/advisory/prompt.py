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

_SYSTEM_INSTRUCTIONS = """You are the orchestrator of a 100-agent AI market-simulation swarm.
A simulation cycle has just completed. Using the prefetched swarm data and the
user's holdings list, write a portfolio advisory as ONE JSON object with exactly
these keys:

{
  "portfolio_outlook": string  (1-3 substantive paragraphs: the swarm's overall
                                reading and what it implies for these holdings),
  "items": [
    {
      "ticker": string          (one of the tickers in the holdings list, exactly as given),
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number in [0.0, 1.0],
      "rationale": string       (1-2 sentences grounded in the swarm data),
      "risk": string            (one short sentence: the main downside),
      "upside": string          (one short sentence: the main upside)
    }
  ]
}

EMIT CONVICTION ITEMS ONLY.
Include a holding only when the swarm produced a CLEAR directional view: a BUY or
SELL signal, or HOLD with confidence above 0.4. The engine pads every other
holding after you reply, so the user still sees the full portfolio.

YOUR OWN READING.
Your "signal" is recorded as your own reading of each holding. The application
compares it with what the agents that referenced the company imply and flags a
disagreement, so give your honest reading.

Do not output markdown, commentary or any other key. Return only the JSON object."""


_WORKED_EXAMPLE = """EXAMPLE (shape only; ZZZT is a placeholder ticker, use the real data below):
{
  "portfolio_outlook": "The swarm converged on BUY for industrial automation names...",
  "items": [
    {"ticker": "ZZZT", "signal": "BUY", "confidence": 0.82,
     "rationale": "Event-Driven and Sell-Side agents read the deal as accretive.",
     "risk": "Regulatory review could delay closing.",
     "upside": "A completed deal re-rates the combined margin profile."}
  ]
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
    swarm_consensus: str | None = None,
) -> list[InferenceMessage]:
    """Build the advisory synthesis messages list (system + user).

    All Decimal values in `top_holdings` are already stringified by the caller
    (docs/DECISIONS.md#p41-d-06). Neo4j payloads are serialized with default=str
    to absorb any Decimal in sentiment/confidence fields.

    Only `top_holdings` (the enriched conviction subset) is sent to the LLM.
    engine.py pads every other holding server-side with HOLD@0.30, so the user
    still sees a full portfolio view without spending prompt tokens on no-signal
    HOLD boilerplate (docs/DECISIONS.md#sweep-b-7).

    `swarm_consensus` is the final round's net-score line over all decided agents
    (docs/DECISIONS.md#adr-consensus-estimators); it carries no holdings data.
    Per-holding swarm evidence is deliberately not a parameter: it is joined to
    the reply server-side (docs/DECISIONS.md#adr-grounded-advisory).
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
            f"  swarm_consensus (final round): {swarm_consensus or 'unavailable'}",
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
