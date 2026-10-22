"""Edge query endpoint (D-11): INFLUENCED_BY edges for one cycle and round."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from alphaswarm.web.guards import require_graph
from alphaswarm.web.params import CycleId

log = structlog.get_logger(component="web.edges")

router = APIRouter()


class EdgeItem(BaseModel):
    """Single INFLUENCED_BY edge in the response."""

    source_id: str
    target_id: str
    weight: float


class EdgesResponse(BaseModel):
    """Response model for GET /edges/{cycle_id} (D-13)."""

    edges: list[EdgeItem]


@router.get("/edges/{cycle_id}", response_model=EdgesResponse)
async def get_edges(
    request: Request,
    cycle_id: CycleId,
    round: int = Query(..., alias="round", ge=1, le=3),
) -> EdgesResponse:
    """Return INFLUENCED_BY edges for *cycle_id* and *round*; 503 without Neo4j.

    The dashboard keys every fetch on the frame's cycle id, so the former
    "current" alias (newest completed cycle) is gone and fails validation (422).
    """
    graph = require_graph(request.app.state.app_state)
    edges = await graph.read_influence_edges(cycle_id, round)
    return EdgesResponse(edges=[EdgeItem(**e) for e in edges])
