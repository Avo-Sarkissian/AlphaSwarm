"""Edge query endpoint for AlphaSwarm web server (D-11)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

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
    cycle_id: str,
    round: int = Query(..., alias="round", ge=1, le=3),
) -> EdgesResponse:
    """Return INFLUENCED_BY edges for a given cycle and round.

    Returns 503 if graph_manager is not available (Neo4j offline).
    """
    app_state = request.app.state.app_state
    graph_manager = app_state.graph_manager
    if graph_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "graph_unavailable", "message": "Neo4j is not connected"},
        )

    edges = await graph_manager.read_influence_edges(cycle_id, round)
    return EdgesResponse(edges=[EdgeItem(**e) for e in edges])
