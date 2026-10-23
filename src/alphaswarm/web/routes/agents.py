"""Per-agent read endpoints.

GET /api/agents/{agent_id}/decisions?cycle_id=... returns every stored
decision of one agent in one cycle, ascending by round, so the interview
takeover shows the full history instead of the 50-entry live window
(docs/DECISIONS.md#p14-d-06). Running cycles are readable: rounds appear as
they are persisted.
"""

from __future__ import annotations

from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Path, Request
from pydantic import BaseModel

from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import require_graph
from alphaswarm.web.params import CycleIdQuery

log = structlog.get_logger(component="web.agents")

router = APIRouter()

AGENT_ID_PATTERN: Final = r"^[a-z]+(?:_[a-z]+)*_\d{2}$"
AgentId = Annotated[str, Path(pattern=AGENT_ID_PATTERN, max_length=40)]


class AgentDecisionItem(BaseModel):
    """One stored decision (mirrors graph.AgentDecisionRow)."""

    round_num: int
    signal: str
    confidence: float
    sentiment: float
    rationale: str
    cited_agents: list[str]


class AgentDecisionsResponse(BaseModel):
    """Response for GET /agents/{agent_id}/decisions."""

    agent_id: str
    cycle_id: str
    decisions: list[AgentDecisionItem]


@router.get("/agents/{agent_id}/decisions", response_model=AgentDecisionsResponse)
async def agent_decisions(
    agent_id: AgentId,
    cycle_id: CycleIdQuery,
    request: Request,
) -> AgentDecisionsResponse:
    """Stored decisions for *agent_id* in *cycle_id*.

    503 graph_unavailable without Neo4j; 404 agent_not_found for an id outside
    the roster; 404 cycle_not_found for an unknown cycle; 422 validation_error
    for a malformed id. An existing cycle without rows for the agent yet
    returns an empty list.
    """
    app_state = request.app.state.app_state
    graph = require_graph(app_state)
    if not any(p.id == agent_id for p in app_state.personas):
        raise ApiError(404, "agent_not_found", f"No agent {agent_id} in the roster")
    if not await graph.cycle_exists(cycle_id):
        raise ApiError(404, "cycle_not_found", f"No cycle {cycle_id}")
    rows = await graph.read_agent_decisions(cycle_id, agent_id)
    log.info("agent_decisions_listed", agent_id=agent_id, cycle_id=cycle_id, count=len(rows))
    return AgentDecisionsResponse(
        agent_id=agent_id,
        cycle_id=cycle_id,
        decisions=[AgentDecisionItem.model_validate(r) for r in rows],
    )
