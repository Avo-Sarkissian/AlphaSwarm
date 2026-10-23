"""GET / serves the built UI, or a page that says how to build it."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.app import mount_frontend


def test_missing_dist_serves_a_build_hint(tmp_path: Path) -> None:
    app = FastAPI()
    mount_frontend(app, tmp_path / "dist")
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "npm ci &amp;&amp; npm run build" in r.text
    assert "alphaswarm doctor" in r.text


def test_built_dist_is_served(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>AlphaSwarm UI</title>", encoding="utf-8")
    app = FastAPI()
    mount_frontend(app, tmp_path)
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "AlphaSwarm UI" in r.text


def test_api_routes_keep_working_without_dist(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/api/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    mount_frontend(app, tmp_path / "dist")
    assert TestClient(app).get("/api/ping").json() == {"status": "ok"}
