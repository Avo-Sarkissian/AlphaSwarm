"""Typed accessors for what the lifespan put on app.state (no FastAPI Depends rewrite).

Routes call these instead of reading untyped app.state attributes
(docs/DECISIONS.md#adr-web-lifespan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaswarm.web.errors import ApiError

if TYPE_CHECKING:
    from fastapi import Request

    from alphaswarm.services.advisory import AdvisoryService
    from alphaswarm.services.jobs import JobInProgressError
    from alphaswarm.services.report import ReportService
    from alphaswarm.services.runtime import Runtime

_NO_GRAPH = "Neo4j is not configured for this server"


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def get_report_service(request: Request) -> ReportService:
    service: ReportService | None = getattr(request.app.state, "report_service", None)
    if service is None:
        raise ApiError(503, "graph_unavailable", _NO_GRAPH)
    return service


def get_advisory_service(request: Request) -> AdvisoryService:
    service: AdvisoryService | None = getattr(request.app.state, "advisory_service", None)
    if service is None:
        raise ApiError(503, "graph_unavailable", _NO_GRAPH)
    return service


def job_conflict(exc: JobInProgressError) -> ApiError:
    """409 ``{kind}_generation_in_progress`` naming the job that holds the orchestrator."""
    return ApiError(409, exc.code, f"A {exc.kind} generation is already running; retry when it completes")
