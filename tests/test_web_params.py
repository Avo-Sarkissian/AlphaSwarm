"""Validated request input types in web/params.py (docs/DECISIONS.md#adr-background-tasks)."""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from alphaswarm.web.errors import install_error_handlers
from alphaswarm.web.params import CYCLE_ID_PATTERN, CycleId, CycleIdQuery, SeedText, ShockText

GOOD = "00000000-0000-4000-8000-0000000000a1"


class _Seed(BaseModel):
    seed: SeedText


class _Shock(BaseModel):
    shock_text: ShockText


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/c/{cycle_id}")
    async def by_path(cycle_id: CycleId) -> dict[str, str]:
        return {"cycle_id": cycle_id}

    @app.get("/q")
    async def by_query(cycle_id: CycleIdQuery) -> dict[str, str]:
        return {"cycle_id": cycle_id}

    @app.post("/seed")
    async def seed(body: _Seed) -> dict[str, str]:
        return {"seed": body.seed}

    @app.post("/shock")
    async def shock(body: _Shock) -> dict[str, str]:
        return {"shock_text": body.shock_text}

    return TestClient(app)


def test_pattern_matches_uuid4_strings() -> None:
    assert re.match(CYCLE_ID_PATTERN, str(uuid.uuid4()))


def test_cycle_id_path_accepts_uuid4() -> None:
    r = _client().get(f"/c/{GOOD}")
    assert r.status_code == 200
    assert r.json() == {"cycle_id": GOOD}


@pytest.mark.parametrize(
    "bad",
    [f"{GOOD}%0A", "abc-123", "cycle_01", GOOD.upper(), GOOD + "0"],
)
def test_cycle_id_path_rejects_non_uuid(bad: str) -> None:
    r = _client().get(f"/c/{bad}")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


def test_cycle_id_query_rejects_trailing_newline() -> None:
    client = _client()
    assert client.get("/q", params={"cycle_id": GOOD}).status_code == 200
    assert client.get("/q", params={"cycle_id": GOOD + "\n"}).status_code == 422


@pytest.mark.parametrize("seed", ["", "          ", "nine char", "x" * 2001])
def test_seed_rejects_empty_short_and_oversized(seed: str) -> None:
    r = _client().post("/seed", json={"seed": seed})
    assert r.status_code == 422
    assert r.json()["detail"]["fields"][0]["loc"] == ["body", "seed"]


def test_seed_is_stripped_before_length_check() -> None:
    client = _client()
    assert client.post("/seed", json={"seed": "  ten chars! "}).json() == {"seed": "ten chars!"}
    assert client.post("/seed", json={"seed": "x" * 2000}).status_code == 200


@pytest.mark.parametrize("text", ["too short", "x" * 1001])
def test_shock_rejects_short_and_oversized(text: str) -> None:
    assert _client().post("/shock", json={"shock_text": text}).status_code == 422


def test_shock_accepts_up_to_1000_chars() -> None:
    assert _client().post("/shock", json={"shock_text": "y" * 1000}).status_code == 200
