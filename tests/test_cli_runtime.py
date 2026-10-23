"""CLI smoke tests: every subcommand goes through open_runtime, offline.

No Ollama, no Neo4j and no network: the runtime is the offline one, its
providers are scripted fakes and the graph is a fake or an autospec.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

import alphaswarm.cli as cli
from alphaswarm.graph import GraphStateManager
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.services.runtime import Runtime
from alphaswarm.settings import AppSettings
from tests.inference.fakes import FakeInferenceProvider
from tests.support.report_fakes import REPORT_CYCLE, FakeReportGraph
from tests.support.web_app import offline_runtime

NARRATIVE = json.dumps({"summary": "Consensus ended BUY.", "moments": [], "dissent": [], "followups": []})
SEED = json.dumps(
    {
        "entities": [{"name": "ZZZT Holdings", "type": "company", "relevance": 0.9, "sentiment": 0.6}],
        "overall_sentiment": 0.5,
    }
)
RUMOR = "ZZZT Holdings is in talks to acquire QQQX"


@pytest.fixture(autouse=True)
def _keep_session_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake runtime skips open_runtime's configure_logging; _handle_web's is stubbed."""
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)


def _run_on_a_private_loop(coro: Coroutine[Any, Any, Any]) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


@pytest.fixture(autouse=True)
def _private_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handlers call asyncio.run(), which would also clear the thread's current
    event loop and orphan the one pytest-asyncio installed (it then leaks as an
    unclosed socket and fails a later test under filterwarnings = error)."""
    monkeypatch.setattr(asyncio, "run", _run_on_a_private_loop)


def _use_runtime(
    monkeypatch: pytest.MonkeyPatch,
    graph: Any,
    replies: list[str],
    *,
    ready: bool = True,
) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def _open(settings: AppSettings, **kwargs: Any) -> AsyncIterator[Runtime]:
        runtime = replace(offline_runtime(settings, graph=graph), neo4j_ready=ready)
        orchestrator = FakeInferenceProvider(
            ProviderRole.ORCHESTRATOR,
            "fake-orch",
            scripted=[InferenceResult(content=r, model="fake-orch") for r in replies],
        )

        async def _operation(name: str) -> BuiltProviders:
            seen.setdefault("operations", []).append(name)
            return BuiltProviders(
                orchestrator=orchestrator,
                worker=FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=[]),
                budget_meter=BudgetMeter(None, {}),
            )

        monkeypatch.setattr(runtime.inference, "open_operation", _operation)
        monkeypatch.setattr(runtime.inference, "build_controller", AsyncMock(return_value=MagicMock()))
        seen["runtime"] = runtime
        seen["orchestrator"] = orchestrator
        yield runtime
        seen["closed"] = True

    monkeypatch.setattr(cli, "open_runtime", _open)
    return seen


@pytest.fixture
def reports_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHASWARM_REPORTS_DIR", str(tmp_path / "reports"))
    return tmp_path / "reports"


def test_report_command_runs_through_the_runtime(
    monkeypatch: pytest.MonkeyPatch,
    reports_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen = _use_runtime(monkeypatch, FakeReportGraph(), [NARRATIVE])
    monkeypatch.setattr(sys, "argv", ["alphaswarm", "report", "--cycle", REPORT_CYCLE])
    cli.main()
    assert (reports_env / f"{REPORT_CYCLE}_report.md").is_file()
    assert (reports_env / f"{REPORT_CYCLE}_report.json").is_file()
    assert seen["operations"] == ["report"] and seen["closed"] is True
    assert len(seen["orchestrator"].calls) == 1
    assert "Report generated:" in capsys.readouterr().out


def test_report_command_defaults_to_the_latest_complete_cycle(
    monkeypatch: pytest.MonkeyPatch,
    reports_env: Path,
    tmp_path: Path,
) -> None:
    class Graph(FakeReportGraph):
        async def read_latest_cycle_id(self, **_: Any) -> str:
            return REPORT_CYCLE

    _use_runtime(monkeypatch, Graph(), [NARRATIVE])
    extra = tmp_path / "copy.md"
    monkeypatch.setattr(sys, "argv", ["alphaswarm", "report", "--output", str(extra)])
    cli.main()
    assert extra.read_text(encoding="utf-8").startswith("# Post-Simulation Analysis Report")
    assert (reports_env / f"{REPORT_CYCLE}_report.md").is_file()


def test_report_command_exits_1_when_neo4j_is_down(
    monkeypatch: pytest.MonkeyPatch,
    reports_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_runtime(monkeypatch, FakeReportGraph(), [], ready=False)
    monkeypatch.setattr(sys, "argv", ["alphaswarm", "report", "--cycle", REPORT_CYCLE])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "Neo4j is not reachable" in capsys.readouterr().err


def test_inject_command_runs_through_the_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    graph = create_autospec(GraphStateManager, instance=True)
    graph.create_cycle_with_seed_event.return_value = REPORT_CYCLE
    seen = _use_runtime(monkeypatch, graph, [SEED])
    monkeypatch.setattr(sys, "argv", ["alphaswarm", "inject", RUMOR])
    cli.main()
    out = capsys.readouterr().out
    assert REPORT_CYCLE in out and "Seed Injection Complete" in out
    assert seen["operations"] == ["inject"]
    # No run follows an inject, so its cycle must not read as running
    # (docs/DECISIONS.md#adr-cycle-metrics).
    graph.set_cycle_status.assert_awaited_once_with(REPORT_CYCLE, "failed")


def test_run_command_runs_through_the_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider

    seen = _use_runtime(monkeypatch, create_autospec(GraphStateManager, instance=True), [])
    captured: dict[str, Any] = {}

    async def _fake_run(rumor: str, deps: Any, personas: Any, brackets: Any, **kwargs: Any) -> Any:
        captured.update(deps=deps, kwargs=kwargs, personas=personas)
        return MagicMock()

    monkeypatch.setattr("alphaswarm.cli.run_simulation", _fake_run)
    monkeypatch.setattr(cli, "_print_simulation_summary", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["alphaswarm", "run", RUMOR])
    cli.main()
    deps = captured["deps"]
    assert deps.orchestrator is seen["orchestrator"]
    assert isinstance(deps.market, YFinanceMarketDataProvider)
    assert isinstance(deps.news, RSSNewsProvider)
    assert deps.context_fixture is None
    assert callable(captured["kwargs"]["on_round_complete"])
    assert len(captured["personas"]) == 100
    assert seen["operations"] == ["simulation"]


@pytest.mark.parametrize("mode", ["context_fixture", "no_market_context"])
def test_point_in_time_runs_get_no_live_providers(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """A fixture or --no-market-context run hands no yfinance/RSS provider to the
    engine, so nothing is fetched; the fixture is what reaches run_simulation
    (docs/DECISIONS.md#adr-eval-harness)."""
    from alphaswarm.ingestion.fixture import build_fixture_packet

    packet = build_fixture_packet(
        event_id="evt-001",
        as_of=datetime(2026, 2, 3, 14, 0, tzinfo=UTC),
        ticker="ZZZT",
        close=Decimal("123.45"),
        volume=1_000_000,
    )
    _use_runtime(monkeypatch, create_autospec(GraphStateManager, instance=True), [])
    captured: dict[str, Any] = {}

    async def _fake_run(rumor: str, deps: Any, personas: Any, brackets: Any, **kwargs: Any) -> Any:
        captured["deps"] = deps
        return MagicMock()

    monkeypatch.setattr("alphaswarm.cli.run_simulation", _fake_run)
    monkeypatch.setattr(cli, "_print_simulation_summary", lambda *a, **k: None)
    run_kwargs: dict[str, Any] = {"context_fixture": packet} if mode == "context_fixture" else {"market_context": False}
    cli._handle_run(RUMOR, **run_kwargs)
    deps = captured["deps"]
    assert (deps.market, deps.news) == (None, None)
    assert deps.context_fixture is (packet if mode == "context_fixture" else None)


def test_web_launcher_is_factory_mode_with_one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    cli._handle_web("127.0.0.1", 8123)
    assert calls == [
        (
            ("alphaswarm.web.app:create_app",),
            {"factory": True, "host": "127.0.0.1", "port": 8123, "workers": 1, "log_config": None},
        )
    ]


def test_importing_the_web_app_constructs_nothing() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALPHASWARM_")}
    env["ALPHASWARM_LOG_LEVEL"] = "NOT-A-LEVEL"  # AppSettings() would raise if built at import
    proc = subprocess.run(
        [sys.executable, "-c", "import alphaswarm.web.app as m; print(hasattr(m, 'app'))"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"
