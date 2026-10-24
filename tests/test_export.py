"""CycleExport assembly and export_cycle. Fictional data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from alphaswarm.errors import CycleNotFoundError, CycleNotReadyError
from alphaswarm.export import EXPORT_SCHEMA, CycleExport, build_export, export_cycle, export_json
from alphaswarm.personas import BRACKET_DISPLAY_NAMES
from tests.support.export_rows import EXPORT_CYCLE_ID, EXPORT_SHOCK, make_export_rows
from tests.support.manifests import make_manifest
from tests.support.web_app import CYCLE_UNKNOWN, FakeCycleGraph


def _export(**kwargs: Any) -> CycleExport:
    return build_export(make_export_rows(**kwargs), status="complete", report_markdown=None)


def test_archival_agents_sort_after_the_roster() -> None:
    export = _export()
    assert [a.id for a in export.roster] == ["sell_side_01", "quants_01", "legacy_whale_01"]
    assert [a.display_name for a in export.roster] == [
        BRACKET_DISPLAY_NAMES["sell_side"],
        BRACKET_DISPLAY_NAMES["quants"],
        "whales",
    ]
    assert [d.agent_id for d in export.rounds[0].decisions] == [
        "sell_side_01",
        "quants_01",
        "legacy_whale_01",
    ]


def test_rounds_carry_decisions_citations_and_shocks() -> None:
    export = _export()
    first, second = export.rounds
    quants = next(d for d in second.decisions if d.agent_id == "quants_01")
    assert quants.cited_agent_ids == ["sell_side_01"]
    assert quants.peer_ids == ["sell_side_01", "legacy_whale_01"]
    assert next(d for d in second.decisions if d.agent_id == "sell_side_01").control is True
    assert first.citations == []
    assert [c.model_dump() for c in second.citations] == [
        {"source_id": "quants_01", "target_id": "sell_side_01", "cited_signal": "sell"},
    ]
    assert [(s.text, s.injected_before_round) for s in export.shocks] == [(EXPORT_SHOCK, 2)]
    assert export.cycle.metrics["git_dirty"] is False
    assert export.cycle.metrics["final_sell"] == 2


def test_num_rounds_falls_back_to_the_last_round() -> None:
    assert _export(num_rounds=None).cycle.num_rounds == 2


def test_stored_manifest_is_parsed() -> None:
    manifest = make_manifest(cycle_id=EXPORT_CYCLE_ID)
    export = _export(run_manifest_json=manifest.model_dump_json(by_alias=True))
    assert export.cycle.manifest == manifest


def test_unreadable_manifest_becomes_null() -> None:
    with capture_logs() as logs:
        export = _export(run_manifest_json='{"schema": "alphaswarm.run-manifest/99"}')
    assert export.cycle.manifest is None
    assert [e["event"] for e in logs] == ["export_manifest_unreadable"]


def test_export_round_trips_with_the_schema_alias() -> None:
    export = _export()
    payload = export_json(export)
    data = json.loads(payload)
    assert data["schema"] == EXPORT_SCHEMA
    assert "schema_id" not in data
    assert CycleExport.model_validate_json(payload) == export


def test_export_json_keeps_utf8() -> None:
    payload = export_json(_export())
    assert "—" in payload
    assert "\\u2014" not in payload
    assert ": " not in payload.split('"rationale"')[0]  # compact separators


def _property_names(schema: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        names.update(schema.get("properties", {}))
        for value in schema.values():
            names |= _property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= _property_names(value)
    return names


def test_export_model_has_no_portfolio_or_prompt_fields() -> None:
    forbidden = {
        "holding",
        "holdings",
        "portfolio",
        "ticker",
        "tickers",
        "qty",
        "quantity",
        "shares",
        "cost_basis",
        "account",
        "peer_context_received",
        "modifiers_json",
    }
    assert _property_names(CycleExport.model_json_schema()).isdisjoint(forbidden)


async def test_export_cycle_refuses_an_unknown_cycle(tmp_path: Path) -> None:
    graph = FakeCycleGraph({})
    with pytest.raises(CycleNotFoundError):
        await export_cycle(graph, CYCLE_UNKNOWN, reports_dir=tmp_path)  # type: ignore[arg-type]
    assert graph.export_calls == []


async def test_export_cycle_refuses_a_running_cycle(tmp_path: Path) -> None:
    graph = FakeCycleGraph({EXPORT_CYCLE_ID: "running"}, export_rows={EXPORT_CYCLE_ID: make_export_rows()})
    with pytest.raises(CycleNotReadyError) as exc_info:
        await export_cycle(graph, EXPORT_CYCLE_ID, reports_dir=tmp_path)  # type: ignore[arg-type]
    assert exc_info.value.status == "running"
    assert graph.export_calls == []


async def test_export_cycle_reads_the_report_and_keeps_the_status(tmp_path: Path) -> None:
    (tmp_path / f"{EXPORT_CYCLE_ID}_report.md").write_text("# Swarm report\n", encoding="utf-8")
    graph = FakeCycleGraph({EXPORT_CYCLE_ID: "failed"}, export_rows={EXPORT_CYCLE_ID: make_export_rows()})
    export = await export_cycle(graph, EXPORT_CYCLE_ID, reports_dir=tmp_path)  # type: ignore[arg-type]
    assert export.report_markdown == "# Swarm report\n"
    assert export.cycle.status == "failed"


async def test_export_cycle_without_a_report(tmp_path: Path) -> None:
    graph = FakeCycleGraph({EXPORT_CYCLE_ID: "complete"}, export_rows={EXPORT_CYCLE_ID: make_export_rows()})
    export = await export_cycle(graph, EXPORT_CYCLE_ID, reports_dir=tmp_path)  # type: ignore[arg-type]
    assert export.report_markdown is None
