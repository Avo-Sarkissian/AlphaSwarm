"""Edge query endpoint (D-11): INFLUENCED_BY edges for one cycle and round."""

from __future__ import annotations

from typing import Annotated, Final

import fastapi
import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from alphaswarm.web.guards import require_graph
from alphaswarm.web.params import CYCLE_ID_PATTERN

log = structlog.get_logger(component="web.edges")

router = APIRouter()

# "current" (the latest cycle) is still accepted until the frontend keys edge
# fetches by the frame's cycle id; any other value must be a cycle uuid.
EDGES_CYCLE_ID_PATTERN: Final = rf"^(?:current|{CYCLE_ID_PATTERN[1:-1]})$"
EdgesCycleId = Annotated[str, fastapi.Path(pattern=EDGES_CYCLE_ID_PATTERN)]


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
    cycle_id: EdgesCycleId,
    round: int = Query(..., alias="round", ge=1, le=3),
) -> EdgesResponse:
    """Return INFLUENCED_BY edges for *cycle_id* and *round*; 503 without Neo4j."""
    graph = require_graph(request.app.state.app_state)
    resolved = cycle_id
    if cycle_id == "current":
        latest = await graph.read_latest_cycle_id()
        if latest is None:
            return EdgesResponse(edges=[])
        resolved = latest
    edges = await graph.read_influence_edges(resolved, round)
    return EdgesResponse(edges=[EdgeItem(**e) for e in edges])
