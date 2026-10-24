"""Per-cycle endpoints: citations and the cycle export. Fictional data."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alphaswarm.export import CycleExport
from alphaswarm.settings import AppSettings
from alphaswarm.web.app import create_app
from alphaswarm.web.routes.cycles import router as cycles_router
from tests.support.export_rows import make_export_rows
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    make_route_app,
    route_test_settings,
)

ROWS: list[dict[str, object]] = [
    {"source_id": "degens_02", "target_id": "sell_side_01", "cited_signal": "sell"},
    {"source_id": "quants_01", "target_id": "macro_01", "cited_signal": "unknown"},
]
CITATIONS_URL = f"/api/cycles/{CYCLE_A}/citations"


def _client(tmp_path: Path, graph: FakeCycleGraph | None) -> TestClient:
    return TestClient(make_route_app(cycles_router, settings=route_test_settings(tmp_path), graph=graph))


def test_returns_the_rounds_citations(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"}, citations={(CYCLE_A, 2): ROWS})
    with _client(tmp_path, graph) as client:
        resp = client.get(CITATIONS_URL, params={"round": 2})
    assert resp.status_code == 200
    assert resp.json() == {"cycle_id": CYCLE_A, "round_num": 2, "citations": ROWS}
    assert graph.citation_calls == [(CYCLE_A, 2)]


def test_running_cycle_is_readable(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "running"}, citations={(CYCLE_A, 2): ROWS[:1]})
    with _client(tmp_path, graph) as client:
        resp = client.get(CITATIONS_URL, params={"round": 2})
    assert resp.status_code == 200
    assert len(resp.json()["citations"]) == 1


def test_unknown_cycle_is_404_without_a_read(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"})
    with _client(tmp_path, graph) as client:
        resp = client.get(f"/api/cycles/{CYCLE_UNKNOWN}/citations", params={"round": 2})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "cycle_not_found"
    assert graph.citation_calls == []


@pytest.mark.parametrize("query", ["?round=0", "?round=4", "?round=two", ""])
def test_round_out_of_range_is_a_validation_error(tmp_path: Path, query: str) -> None:
    with _client(tmp_path, FakeCycleGraph({CYCLE_A: "complete"})) as client:
        resp = client.get(f"{CITATIONS_URL}{query}")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "validation_error"


@pytest.mark.parametrize("cycle", ["not-a-uuid", f"{CYCLE_A}%0A"])
def test_malformed_cycle_id_is_a_validation_error(tmp_path: Path, cycle: str) -> None:
    with _client(tmp_path, FakeCycleGraph({CYCLE_A: "complete"})) as client:
        resp = client.get(f"/api/cycles/{cycle}/citations?round=2")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "validation_error"


def test_citations_without_neo4j_returns_503(tmp_path: Path) -> None:
    with _client(tmp_path, None) as client:
        resp = client.get(CITATIONS_URL, params={"round": 2})
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "graph_unavailable"


def test_production_app_registers_the_citations_route(web_test_settings: AppSettings) -> None:
    app = create_app(web_test_settings)
    assert "/api/cycles/{cycle_id}/citations" in {getattr(r, "path", None) for r in app.routes}


EXPORT_URL = f"/api/cycles/{CYCLE_A}/export"


def test_export_returns_the_cycle_under_the_schema_key(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"}, export_rows={CYCLE_A: make_export_rows()})
    with _client(tmp_path, graph) as client:
        resp = client.get(EXPORT_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema"] == "alphaswarm.cycle-export/1"
    assert body["cycle"]["cycle_id"] == CYCLE_A
    assert CycleExport.model_validate(body).cycle.status == "complete"


def test_export_reads_the_report_from_reports_dir(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / f"{CYCLE_A}_report.md").write_text("# Swarm report\n", encoding="utf-8")
    graph = FakeCycleGraph({CYCLE_A: "complete"}, export_rows={CYCLE_A: make_export_rows()})
    with _client(tmp_path, graph) as client:
        resp = client.get(EXPORT_URL)
    assert resp.json()["report_markdown"] == "# Swarm report\n"


def test_export_of_a_running_cycle_is_422(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "running"}, export_rows={CYCLE_A: make_export_rows()})
    with _client(tmp_path, graph) as client:
        resp = client.get(EXPORT_URL)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "cycle_not_ready"
    assert graph.export_calls == []


def test_export_of_an_unknown_cycle_is_404(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"})
    with _client(tmp_path, graph) as client:
        resp = client.get(f"/api/cycles/{CYCLE_UNKNOWN}/export")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "cycle_not_found"


def test_export_without_neo4j_returns_503(tmp_path: Path) -> None:
    with _client(tmp_path, None) as client:
        resp = client.get(EXPORT_URL)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "graph_unavailable"


def test_production_app_registers_the_export_route(web_test_settings: AppSettings) -> None:
    app = create_app(web_test_settings)
    assert "/api/cycles/{cycle_id}/export" in {getattr(r, "path", None) for r in app.routes}
