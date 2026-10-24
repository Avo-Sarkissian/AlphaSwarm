"""Instructions appended to every persona system prompt: the decision JSON format."""

from __future__ import annotations

from typing import Final

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
