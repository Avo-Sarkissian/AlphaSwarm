"""Error envelope and exception handlers (C-WEB-11)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from pydantic import BaseModel, Field

from alphaswarm.errors import Neo4jConnectionError, Neo4jUnavailableError
from alphaswarm.web.errors import ApiError, error_body, install_error_handlers
from alphaswarm.web.replay_manager import NoReplayActiveError
from alphaswarm.web.simulation_manager import SimulationAlreadyRunningError


class _Body(BaseModel):
    seed: str = Field(min_length=10)


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/api-error")
    async def api_error() -> None:
        raise ApiError(409, "thing_busy", "Thing is busy", extra={"cycle_id": "c", "error": "x"})

    @app.post("/validate")
    async def validate(body: _Body) -> dict[str, str]:
        return {"seed": body.seed}

    @app.get("/graph-down")
    async def graph_down() -> None:
        raise Neo4jUnavailableError("refused at /Users/someone/x", op="read_cycle_status")

    @app.get("/legacy-graph-down")
    async def legacy_graph_down() -> None:
        raise Neo4jConnectionError("refused at /Users/someone/x")

    @app.get("/driver-down")
    async def driver_down() -> None:
        raise ServiceUnavailable("connection refused")

    @app.get("/conflict")
    async def conflict() -> None:
        raise SimulationAlreadyRunningError("Simulation already running")

    @app.get("/replay-race")
    async def replay_race() -> None:
        raise NoReplayActiveError("No replay active")

    @app.get("/legacy")
    async def legacy() -> None:
        raise HTTPException(status_code=409, detail={"error": "legacy_code", "message": "m"})

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret path /Users/someone/.secrets/inference.json")

    return app


def test_error_body_shape_and_reserved_keys() -> None:
    body = error_body("x_code", "X happened", request_id="abc", extra={"error": "nope", "n": 1})
    assert body == {
        "detail": {"error": "x_code", "message": "X happened", "n": 1, "request_id": "abc"},
    }


def test_api_error_renders_envelope_with_extra() -> None:
    r = TestClient(_app()).get("/api-error")
    assert r.status_code == 409
    assert r.json() == {
        "detail": {"error": "thing_busy", "message": "Thing is busy", "cycle_id": "c"},
    }


def test_validation_error_is_422_envelope_without_input_values() -> None:
    r = TestClient(_app()).post("/validate", json={"seed": "short-x"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "validation_error"
    assert detail["message"] == "Request validation failed"
    assert detail["fields"] == [
        {
            "loc": ["body", "seed"],
            "msg": "String should have at least 10 characters",
            "type": "string_too_short",
        },
    ]
    assert "short-x" not in r.text


@pytest.mark.parametrize("path", ["/graph-down", "/legacy-graph-down", "/driver-down"])
def test_graph_errors_map_to_503(path: str) -> None:
    r = TestClient(_app()).get(path)
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "graph_unavailable"
    assert "/Users" not in r.text


@pytest.mark.parametrize(
    ("path", "code"),
    [("/conflict", "simulation_already_running"), ("/replay-race", "no_replay_active")],
)
def test_domain_conflicts_map_to_409(path: str, code: str) -> None:
    r = TestClient(_app()).get(path)
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == code


def test_http_exception_with_dict_detail_keeps_shape() -> None:
    r = TestClient(_app()).get("/legacy")
    assert r.status_code == 409
    assert r.json() == {"detail": {"error": "legacy_code", "message": "m"}}


def test_unknown_route_404_uses_envelope() -> None:
    r = TestClient(_app()).get("/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": {"error": "not_found", "message": "Not Found"}}


def test_unhandled_exception_is_500_with_request_id_and_no_text() -> None:
    # Starlette re-raises after the catch-all handler responds, so the client
    # must not re-raise server exceptions for this assertion.
    r = TestClient(_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail["error"] == "internal_error"
    assert detail["message"] == "Internal server error"
    assert re.fullmatch(r"[0-9a-f]{12}", detail["request_id"])
    assert "secrets" not in r.text


def test_create_app_installs_error_handlers() -> None:
    from alphaswarm.web.app import create_app

    app = create_app()
    assert ApiError in app.exception_handlers
    assert Exception in app.exception_handlers
