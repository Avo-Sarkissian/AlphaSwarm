"""Per-cycle read endpoints (docs/DECISIONS.md#adr-cycle-export).

GET /api/cycles/{cycle_id}/citations?round=N returns who cited whom in round N,
with the signal each cited agent held in round N-1, which is what the citing
agent saw (docs/DECISIONS.md#adr-neo4j-schema). Round 1 and rounds past the
cycle's depth return an empty list. Running cycles are readable, so the live
graph can draw a round as soon as its edges exist.

GET /api/cycles/{cycle_id}/export returns the cycle as alphaswarm.cycle-export/1.
"""

from __future__ import annotations

from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from alphaswarm.export import CycleExport, export_cycle
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import require_graph
from alphaswarm.web.params import CycleId

log = structlog.get_logger(component="web.cycles")

router = APIRouter()

#: ALPHASWARM_NUM_ROUNDS is 2 or 3 (docs/DECISIONS.md#adr-num-rounds).
MAX_ROUND: Final = 3


class RoundCitationItem(BaseModel):
    """One citation (mirrors graph.rows.RoundCitationRow)."""

    source_id: str
    target_id: str
    cited_signal: str


class RoundCitationsResponse(BaseModel):
    """Response for GET /cycles/{cycle_id}/citations."""

    cycle_id: str
    round_num: int
    citations: list[RoundCitationItem]


@router.get("/cycles/{cycle_id}/citations", response_model=RoundCitationsResponse)
async def round_citations(
    cycle_id: CycleId,
    request: Request,
    round_num: Annotated[int, Query(alias="round", ge=1, le=MAX_ROUND)],
) -> RoundCitationsResponse:
    """Citations of one round.

    404 cycle_not_found (checked before any read), 422 validation_error for a
    malformed id or a round outside 1..3, 503 graph_unavailable without Neo4j.
    """
    graph = require_graph(request.app.state.app_state)
    if not await graph.cycle_exists(cycle_id):
        raise ApiError(404, "cycle_not_found", f"No cycle {cycle_id}")
    rows = await graph.read_round_citations(cycle_id, round_num)
    log.debug("round_citations_served", cycle_id=cycle_id, round_num=round_num, count=len(rows))
    return RoundCitationsResponse(
        cycle_id=cycle_id,
        round_num=round_num,
        citations=[RoundCitationItem.model_validate(r) for r in rows],
    )


@router.get("/cycles/{cycle_id}/export", response_model=CycleExport)
async def cycle_export(cycle_id: CycleId, request: Request) -> CycleExport:
    """The cycle as alphaswarm.cycle-export/1 (docs/DECISIONS.md#adr-cycle-export).

    404 cycle_not_found, 422 cycle_not_ready while the cycle is still running,
    422 validation_error for a malformed id, 503 graph_unavailable.
    """
    app_state = request.app.state.app_state
    graph = require_graph(app_state)
    settings = app_state.settings
    export = await export_cycle(graph, cycle_id, reports_dir=settings.resolve_path(settings.reports_dir))
    log.info("cycle_export_served", cycle_id=cycle_id, rounds=len(export.rounds))
    return export
