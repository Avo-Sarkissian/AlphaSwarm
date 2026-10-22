"""HTTP error envelope and exception handlers for the AlphaSwarm API.

Every error response has the shape ``{"detail": {"error": <code>, "message": <text>, ...}}``.
FastAPI's ``detail`` wrapper is kept because the frontend reads ``detail.error``.
Messages are fixed sentences: they never contain exception text, file paths, keys
or holdings. Unexpected exceptions become a 500 with a request id that is logged
together with the traceback (docs/DECISIONS.md#adr-background-tasks).
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from typing import Any, Final

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from neo4j.exceptions import DriverError
from starlette.exceptions import HTTPException as StarletteHTTPException

from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.web.replay_manager import (
    NoReplayActiveError,
    ReplayAlreadyActiveError,
    SimulationActiveError,
)
from alphaswarm.web.simulation_manager import (
    NoSimulationRunningError,
    PostRunJobsInProgressError,
    ReplayActiveError,
    ShockAlreadyQueuedError,
    ShockWindowClosedError,
    SimulationAlreadyRunningError,
)

log = structlog.get_logger(component="web.errors")

_RESERVED_KEYS: Final = frozenset({"error", "message", "request_id"})
_HTTP_CODES: Final[dict[int, str]] = {404: "not_found", 405: "method_not_allowed"}

#: Domain exceptions raised by the managers -> (HTTP status, stable error code).
DOMAIN_ERROR_STATUS: dict[type[Exception], tuple[int, str]] = {
    SimulationAlreadyRunningError: (409, "simulation_already_running"),
    ReplayActiveError: (409, "replay_active"),
    PostRunJobsInProgressError: (409, "post_run_jobs_in_progress"),
    NoSimulationRunningError: (409, "no_simulation_running"),
    ShockAlreadyQueuedError: (409, "shock_already_queued"),
    ShockWindowClosedError: (409, "shock_window_closed"),
    ReplayAlreadyActiveError: (409, "replay_already_active"),
    SimulationActiveError: (409, "simulation_in_progress"),
    NoReplayActiveError: (409, "no_replay_active"),
}


class ApiError(Exception):
    """An error with a stable HTTP status and code, rendered as the envelope."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra: dict[str, object] = dict(extra or {})


def error_body(
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build ``{"detail": {...}}``; ``extra`` can never override the reserved keys."""
    detail: dict[str, object] = {"error": code, "message": message}
    for key, value in (extra or {}).items():
        if key not in _RESERVED_KEYS:
            detail[key] = value
    if request_id is not None:
        detail["request_id"] = request_id
    return {"detail": detail}


def validation_fields(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
    """Reduce pydantic error dicts to ``loc``/``msg``/``type`` (never the rejected input)."""
    return [
        {
            "loc": list(err.get("loc", ())),
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in errors
    ]


def _respond(
    status: int,
    body: dict[str, object],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=dict(headers or {}))


async def _api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _respond(exc.status, error_body(exc.code, exc.message, extra=exc.extra))


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _respond(
        422,
        error_body(
            "validation_error",
            "Request validation failed",
            extra={"fields": validation_fields(exc.errors())},
        ),
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    headers = getattr(exc, "headers", None)
    if isinstance(exc.detail, Mapping):
        return _respond(exc.status_code, {"detail": dict(exc.detail)}, headers)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return _respond(exc.status_code, error_body(code, str(exc.detail)), headers)


async def _graph_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    log.warning(
        "request_failed_graph_unavailable",
        path=request.url.path,
        exc_type=exc.__class__.__name__,
        op=getattr(exc, "op", None),
    )
    return _respond(
        503,
        error_body(
            "graph_unavailable",
            "Neo4j is unavailable; start it with `docker compose up -d neo4j`",
        ),
    )


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    for exc_type in type(exc).__mro__:
        mapped = DOMAIN_ERROR_STATUS.get(exc_type)
        if mapped is not None:
            status, code = mapped
            return _respond(status, error_body(code, str(exc)))
    return await _unhandled_handler(request, exc)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = secrets.token_hex(6)
    log.error(
        "request_failed_unhandled",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        exc_info=exc,
    )
    return _respond(
        500,
        error_body("internal_error", "Internal server error", request_id=request_id),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on *app*; call once from ``create_app`` (and test apps)."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Neo4jUnavailableError, _graph_unavailable_handler)
    app.add_exception_handler(DriverError, _graph_unavailable_handler)
    for exc_type in DOMAIN_ERROR_STATUS:
        app.add_exception_handler(exc_type, _domain_error_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
