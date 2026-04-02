"""Interview data types and conversation engine for post-simulation agent interviews."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from alphaswarm.config import JSON_OUTPUT_INSTRUCTIONS

log = structlog.get_logger(component="interview")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoundDecision:
    """Immutable record of an agent's decision in a single simulation round."""

    round_num: int
    signal: str
    confidence: float
    sentiment: float
    rationale: str


@dataclass(frozen=True)
class InterviewContext:
    """Immutable context bundle for an agent interview session.

    Reconstructed from Neo4j at interview start. Contains persona identity,
    decision narrative summary, and per-round decision details.
    """

    agent_id: str
    agent_name: str
    bracket: str
    interview_system_prompt: str  # persona system_prompt with JSON instructions stripped
    decision_narrative: str  # pre-computed from Agent node (Phase 11)
    decisions: list[RoundDecision]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _strip_json_instructions(system_prompt: str) -> str:
    """Remove JSON_OUTPUT_INSTRUCTIONS from a persona system prompt.

    Interviews are conversational prose, not JSON-structured decisions (D-05).
    """
    return system_prompt.replace(JSON_OUTPUT_INSTRUCTIONS, "").rstrip()
