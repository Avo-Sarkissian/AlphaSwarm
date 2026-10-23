"""Builders for interview tests: graph rows as GraphStateManager returns them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from alphaswarm.graph import AgentDecisionRow

if TYPE_CHECKING:
    from alphaswarm.graph import AgentInterviewRows
    from alphaswarm.types import BracketType


def interview_rows(
    agent_id: str = "quants_01",
    *,
    decisions: Sequence[AgentDecisionRow] = (),
    modifiers: Mapping[BracketType, str] | None = None,
    narrative: str = "",
) -> AgentInterviewRows:
    """Rows for a roster agent; defaults match a legacy cycle (no modifiers, no narrative)."""
    rows: AgentInterviewRows = {
        "agent_id": agent_id,
        "name": agent_id,
        "bracket": agent_id.rsplit("_", 1)[0],
        "modifiers": dict(modifiers) if modifiers is not None else None,
        "narrative": narrative,
        "decisions": list(decisions),
    }
    return rows


def decision_row(
    *,
    round_num: int,
    signal: str,
    confidence: float,
    sentiment: float,
    rationale: str,
    cited_agents: Sequence[str] = (),
) -> AgentDecisionRow:
    return AgentDecisionRow(
        round_num=round_num,
        signal=signal,
        confidence=confidence,
        sentiment=sentiment,
        rationale=rationale,
        cited_agents=list(cited_agents),
    )
