"""The decision prompt: JSON instructions for the system prompt, focal line for the task."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from alphaswarm.security.sanitize import sanitize_entity_name
from alphaswarm.types import EntityType, SeedEntity

# ---------------------------------------------------------------------------
# JSON output instructions (appended to every persona system prompt)
# ---------------------------------------------------------------------------

# Reasoning first, then the vote (docs/DECISIONS.md#adr-decision-prompt).
JSON_OUTPUT_INSTRUCTIONS: Final = (
    "\n\nRespond ONLY with a JSON object. Write the rationale first, then choose the "
    "signal that follows from it:\n"
    '{"rationale": "one or two sentences", "signal": "buy"|"sell"|"hold", '
    '"confidence": 0.0-1.0, "sentiment": -1.0 to 1.0, "cited_agents": []}\n'
    'Keep "rationale" to one or two sentences of at most 40 words, and list at '
    'most 5 agent ids in "cited_agents".\n'
    "Confidence calibration (use the full scale honestly): 0.9+ means "
    "exceptional conviction you would stake your reputation on; 0.6-0.8 a "
    "solid thesis with real evidence; 0.4-0.6 a weak lean; below 0.4 little "
    "more than a guess."
)

# Neutral on purpose: each bracket keeps its own reading of buy/sell/hold, so the
# Narrators' crowd-direction framing stands (docs/DECISIONS.md#adr-decision-prompt).
FOCAL_INSTRUCTION: Final = (
    "Instrument in focus: {ticker} ({name}). Your signal refers to this instrument; "
    "read buy/sell/hold for it the way your role instructions define them."
)


@dataclass(frozen=True)
class FocalInstrument:
    ticker: str
    name: str


def focal_instrument(entities: Sequence[SeedEntity]) -> FocalInstrument | None:
    """The highest-relevance company with a resolved ticker; ties keep emission order."""
    best: SeedEntity | None = None
    for entity in entities:
        if entity.type is not EntityType.COMPANY or entity.ticker is None:
            continue
        if best is None or entity.relevance > best.relevance:
            best = entity
    if best is None or best.ticker is None:
        return None
    return FocalInstrument(ticker=best.ticker, name=sanitize_entity_name(best.name))


def render_decision_task(message: str, focal: FocalInstrument | None) -> str:
    """The round's decision message plus the focal-instrument line, when there is one."""
    if focal is None:
        return message
    return f"{message}\n\n" + FOCAL_INSTRUCTION.format(ticker=focal.ticker, name=focal.name)
