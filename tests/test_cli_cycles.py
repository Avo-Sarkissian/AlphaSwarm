"""alphaswarm cycles list|export|delete. Fictional data only."""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from alphaswarm import cli
from alphaswarm.export import EXPORT_SCHEMA
from tests.support.export_rows import EXPORT_CYCLE_ID, EXPORT_RUMOR, make_export_rows

UNKNOWN = "00000000-0000-4000-8000-0000000000ff"
ROW: dict[str, Any] = {
    "cycle_id": EXPORT_CYCLE_ID,
    "created_at": "2026-10-03T12:00:00.123456+00:00",
    "seed_rumor": EXPORT_RUMOR,
    "round_count": 3,
    "status": "complete",
    "final_buy": 31,
    "final_sell": 31,
    "final_hold": 32,
    "total_flips": 20,
    "total_seconds": 60.0,
    "agent_count": 100,
}


class CliGraph:
    def __init__(self, *, statuses: dict[str, str] | None = None, rows: list[dict[str, Any]] | None = None) -> None:
        self.statuses = dict(statuses or {})
        self.rows = list(rows or [])
        self.list_calls: list[tuple[int, tuple[str, ...]]] = []
        self.deleted: list[str] = []

    async def read_completed_cycles(
        self, limit: int = 20, *, before: object = None, statuses: tuple[str, ...] = ("complete",)
    ) -> list[dict[str, Any]]:
        self.list_calls.append((limit, tuple(statuses)))
        return list(self.rows)

    async def read_cycle_status(self, cycle_id: str) -> str | None:
        return self.statuses.get(cycle_id)

    async def read_cycle_export_rows(self, cycle_id: str) -> Any:
        return make_export_rows(cycle_id=cycle_id)

    async def delete_cycle(self, cycle_id: str, *, batch_size: int = 1000) -> int:
        self.deleted.append(cycle_id)
        return 10


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def cli_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("ALPHASWARM_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("ALPHASWARM_ADVISORY_DIR", str(tmp_path / "advisory"))
    return tmp_path


def use_graph(monkeypatch: pytest.MonkeyPatch, graph: CliGraph) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_open_runtime(settings: Any, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        seen.update(kwargs)
        # The real runtime routes logs to stderr; capturing them keeps stdout the command's own.
        with capture_logs():
            yield SimpleNamespace(settings=settings, app_state=SimpleNamespace(graph_manager=graph), neo4j_ready=True)

    monkeypatch.setattr(cli, "open_runtime", fake_open_runtime)
    return seen


def test_list_prints_one_row_per_cycle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    graph = CliGraph(rows=[ROW])
    seen = use_graph(monkeypatch, graph)
    assert cli.run_cli(["cycles", "list", "--limit", "5"]) == cli.EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("CYCLE ID")
    assert lines[1].startswith(EXPORT_CYCLE_ID)
    assert "31/31/32" in lines[1] and "2026-10-03T12:00:00" in lines[1]
    assert graph.list_calls == [(5, ("complete",))]
    assert seen.get("with_ollama") is False


def test_list_all_statuses(monkeypatch: pytest.MonkeyPatch, cli_dirs: Path) -> None:
    graph = CliGraph()
    use_graph(monkeypatch, graph)
    assert cli.run_cli(["cycles", "list", "--status", "all"]) == cli.EXIT_OK
    assert graph.list_calls == [(20, ("running", "complete", "failed", "cancelled"))]


@pytest.mark.parametrize(
    "argv",
    [
        ["cycles"],
        ["cycles", "list", "--limit", "0"],
        ["cycles", "list", "--limit", "101"],
        ["cycles", "list", "--status", "done"],
        ["cycles", "export", "not-a-uuid"],
        ["cycles", "delete", f"{EXPORT_CYCLE_ID}\n"],
    ],
)
def test_bad_arguments_exit_2(argv: list[str]) -> None:
    assert cli.run_cli(argv) == cli.EXIT_USAGE


def test_export_writes_only_json_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    use_graph(monkeypatch, CliGraph(statuses={EXPORT_CYCLE_ID: "complete"}))
    assert cli.run_cli(["cycles", "export", EXPORT_CYCLE_ID]) == cli.EXIT_OK
    body = json.loads(capsys.readouterr().out)
    assert body["schema"] == EXPORT_SCHEMA
    assert body["cycle"]["cycle_id"] == EXPORT_CYCLE_ID


def test_export_writes_a_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    use_graph(monkeypatch, CliGraph(statuses={EXPORT_CYCLE_ID: "complete"}))
    target = cli_dirs / "out" / "cycle.json"
    assert cli.run_cli(["cycles", "export", EXPORT_CYCLE_ID, "-o", str(target)]) == cli.EXIT_OK
    assert json.loads(target.read_text(encoding="utf-8"))["cycle"]["status"] == "complete"
    assert f"Exported cycle {EXPORT_CYCLE_ID} to {target}" in capsys.readouterr().out


def test_export_of_an_unknown_cycle_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    use_graph(monkeypatch, CliGraph())
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(["cycles", "export", UNKNOWN])
    assert exc_info.value.code == cli.EXIT_FAILURE
    assert f"No cycle {UNKNOWN}" in capsys.readouterr().err


def test_delete_refuses_a_running_cycle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    graph = CliGraph(statuses={EXPORT_CYCLE_ID: "running"})
    use_graph(monkeypatch, graph)
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID, "--yes"])
    assert exc_info.value.code == cli.EXIT_FAILURE
    assert "still running" in capsys.readouterr().err
    assert graph.deleted == []


def test_delete_needs_yes_without_a_terminal(monkeypatch: pytest.MonkeyPatch, cli_dirs: Path) -> None:
    graph = CliGraph(statuses={EXPORT_CYCLE_ID: "complete"})
    use_graph(monkeypatch, graph)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID])
    assert exc_info.value.code == cli.EXIT_USAGE
    assert graph.deleted == []


def test_delete_asks_for_the_id_prefix(monkeypatch: pytest.MonkeyPatch, cli_dirs: Path) -> None:
    graph = CliGraph(statuses={EXPORT_CYCLE_ID: "failed"})
    use_graph(monkeypatch, graph)
    monkeypatch.setattr("sys.stdin", _Terminal(f"{EXPORT_CYCLE_ID[:8]}\n"))
    assert cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID]) == cli.EXIT_OK
    assert graph.deleted == [EXPORT_CYCLE_ID]


def test_delete_stops_on_a_wrong_answer(monkeypatch: pytest.MonkeyPatch, cli_dirs: Path) -> None:
    graph = CliGraph(statuses={EXPORT_CYCLE_ID: "complete"})
    use_graph(monkeypatch, graph)
    monkeypatch.setattr("sys.stdin", _Terminal("yes\n"))
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID])
    assert exc_info.value.code == cli.EXIT_FAILURE
    assert graph.deleted == []


def test_delete_lists_files_it_kept(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    report = cli_dirs / "reports" / f"{EXPORT_CYCLE_ID}_report.md"
    report.parent.mkdir()
    report.write_text("# Swarm report\n", encoding="utf-8")
    use_graph(monkeypatch, CliGraph(statuses={EXPORT_CYCLE_ID: "complete"}))
    assert cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID, "--yes"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert f"Deleted cycle {EXPORT_CYCLE_ID} (10 nodes)." in out
    assert str(report) in out
    assert report.exists()


def test_delete_prints_what_it_removes_before_deleting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    use_graph(monkeypatch, CliGraph(statuses={EXPORT_CYCLE_ID: "complete"}))
    assert cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID, "--yes"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    summary = out.index("Deletes: 6 decisions")
    assert f"Cycle {EXPORT_CYCLE_ID} (complete, created 2026-10-03T12:00:00, 2 rounds)" in out
    assert "1 shock event(s)" in out and "Keeps: every agent" in out
    assert summary < out.index(f"Deleted cycle {EXPORT_CYCLE_ID}")


def test_declined_delete_still_shows_the_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    graph = CliGraph(statuses={EXPORT_CYCLE_ID: "complete"})
    use_graph(monkeypatch, graph)
    monkeypatch.setattr("sys.stdin", _Terminal("no\n"))
    with pytest.raises(SystemExit):
        cli.run_cli(["cycles", "delete", EXPORT_CYCLE_ID])
    assert "Deletes: 6 decisions" in capsys.readouterr().out
    assert graph.deleted == []


def test_delete_of_an_unknown_cycle_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cli_dirs: Path
) -> None:
    graph = CliGraph()
    use_graph(monkeypatch, graph)
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(["cycles", "delete", UNKNOWN, "--yes"])
    assert exc_info.value.code == cli.EXIT_FAILURE
    assert f"No cycle {UNKNOWN}" in capsys.readouterr().err
    assert graph.deleted == []
