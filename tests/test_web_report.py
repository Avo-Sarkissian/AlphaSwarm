"""Report background pipeline: provider lifecycle and the aiofiles static check.

Route tests live in tests/test_report_routes.py.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# GET /api/report/{cycle_id}
# ---------------------------------------------------------------------------


def test_get_report_uses_async_filesystem() -> None:
    """Static check: the GET route must NOT call synchronous Path.exists/Path.stat
    inside the async handler. Verifies we use aiofiles.os.* instead (T-36-14)."""
    from alphaswarm.web.routes import report as report_module

    src = inspect.getsource(report_module.get_report)
    # Must use async filesystem helpers.
    assert "aiofiles.os" in src, "GET handler must use aiofiles.os for non-blocking I/O"
    # Must NOT use blocking stdlib filesystem calls on the Path object directly.
    assert ".exists()" not in src, "Do not use Path.exists() in async handler"
    assert ".stat()" not in src, "Do not use Path.stat() in async handler"


# ---------------------------------------------------------------------------
# Background task pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_generation_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_report_generation runs the exact sequence:
    provider.prepare -> engine.run -> assembler.assemble ->
    write_report -> provider.teardown.
    Mirrors cli.py _handle_report (D-03).

    Uses build_providers seam: monkeypatches build_providers in the report module
    to return a fake provider so the test exercises the prepare/teardown lifecycle
    without touching Ollama or cloud credentials.
    """
    monkeypatch.chdir(tmp_path)
    from alphaswarm.web.routes import report as report_module

    call_order: list[str] = []

    class _FakeProvider:
        role = "orchestrator"
        model = "fake-orch"

        async def prepare(self) -> None:
            call_order.append("load_model")

        async def teardown(self) -> None:
            call_order.append("unload_model")

        async def aclose(self) -> None:
            pass

        async def chat(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
            return MagicMock()

    fake_provider = _FakeProvider()

    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.factory import BuiltProviders

    fake_built = BuiltProviders(
        orchestrator=fake_provider,  # type: ignore[arg-type]
        worker=fake_provider,  # type: ignore[arg-type]
        budget_meter=BudgetMeter(None, {}),
    )

    mock_gm = AsyncMock()
    mock_gm.read_shock_event = AsyncMock(return_value=None)

    mock_app_state = MagicMock()
    mock_app_state.model_manager = AsyncMock()
    mock_app_state.graph_manager = mock_gm
    mock_app_state.ollama_client = MagicMock()
    mock_app_state.settings = MagicMock()

    async def _fake_run(_cid: str) -> list:
        call_order.append("engine_run")
        return []

    def _fake_assemble(_obs: list, _cid: str) -> str:
        call_order.append("assemble")
        return "# Report content"

    async def _fake_write_report(_path: Path, _content: str) -> None:
        call_order.append("write_report")

    with (
        patch.object(report_module, "build_providers", return_value=fake_built),
        patch.object(report_module, "load_inference_config", return_value=MagicMock()),
        patch.object(report_module, "ReportEngine") as mock_engine,
        patch.object(report_module, "ReportAssembler") as mock_assembler,
        patch.object(report_module, "write_report", side_effect=_fake_write_report),
    ):
        engine_instance = MagicMock()
        engine_instance.run = _fake_run
        mock_engine.return_value = engine_instance
        assembler_instance = MagicMock()
        assembler_instance.assemble = _fake_assemble
        mock_assembler.return_value = assembler_instance

        await report_module._run_report_generation(mock_app_state, "abc-123")

    assert call_order == [
        "load_model",
        "engine_run",
        "assemble",
        "write_report",
        "unload_model",
    ]


@pytest.mark.asyncio
async def test_report_generation_unloads_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator teardown runs in finally even when engine.run raises.

    Uses build_providers seam: monkeypatches build_providers in the report module
    so that the fake provider's teardown tracking confirms finally-block execution.
    """
    monkeypatch.chdir(tmp_path)
    from alphaswarm.web.routes import report as report_module

    teardown_called: list[bool] = []

    class _FakeProvider:
        role = "orchestrator"
        model = "fake-orch"

        async def prepare(self) -> None:
            pass

        async def teardown(self) -> None:
            teardown_called.append(True)

        async def aclose(self) -> None:
            pass

        async def chat(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
            return MagicMock()

    fake_provider = _FakeProvider()

    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.factory import BuiltProviders

    fake_built = BuiltProviders(
        orchestrator=fake_provider,  # type: ignore[arg-type]
        worker=fake_provider,  # type: ignore[arg-type]
        budget_meter=BudgetMeter(None, {}),
    )

    mock_app_state = MagicMock()
    mock_app_state.model_manager = AsyncMock()
    mock_app_state.graph_manager = AsyncMock()
    mock_app_state.graph_manager.read_shock_event = AsyncMock(return_value=None)
    mock_app_state.ollama_client = MagicMock()
    mock_app_state.settings = MagicMock()

    async def _raise(_cid: str) -> list:
        raise RuntimeError("boom")

    with (
        patch.object(report_module, "build_providers", return_value=fake_built),
        patch.object(report_module, "load_inference_config", return_value=MagicMock()),
        patch.object(report_module, "ReportEngine") as mock_engine,
    ):
        engine_instance = MagicMock()
        engine_instance.run = _raise
        mock_engine.return_value = engine_instance

        with pytest.raises(RuntimeError, match="boom"):
            await report_module._run_report_generation(mock_app_state, "abc-123")

    assert teardown_called == [True], "provider.teardown() must be called in finally"
