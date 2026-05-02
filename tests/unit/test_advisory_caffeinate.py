"""NR-7: caffeinate wake-lock lifecycle tests for advisory synthesis.

These tests assert that `_run_advisory_synthesis` wraps the synthesize() call
in a `caffeinate -i` subprocess (macOS idle-sleep inhibitor) and ALWAYS
terminates the handle in the finally block — even on exception. On non-macOS
platforms (caffeinate binary absent) the wrapper logs a warning and continues
without raising, so Linux/CI pipelines are not broken.

Test surface follows the unit-test pattern in this repo (no TestClient needed,
pure mocks of the route's dependencies).
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_app_state() -> SimpleNamespace:
    """Build a minimal app_state surface that _run_advisory_synthesis reads."""
    settings = SimpleNamespace(
        ollama=SimpleNamespace(orchestrator_model_alias="alphaswarm-orchestrator"),
    )
    model_manager = SimpleNamespace(
        load_model=AsyncMock(),
        unload_model=AsyncMock(),
    )
    return SimpleNamespace(
        settings=settings,
        model_manager=model_manager,
        graph_manager=MagicMock(),
        ollama_client=MagicMock(),
    )


class _FakeAsyncFile:
    """Minimal async-file stand-in for aiofiles.open(...) context manager."""

    async def __aenter__(self) -> "_FakeAsyncFile":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def write(self, _content: str) -> None:
        return None


def _fake_aiofiles_open(*_args: object, **_kwargs: object) -> _FakeAsyncFile:
    return _FakeAsyncFile()


def _fake_report_obj() -> MagicMock:
    obj = MagicMock()
    obj.model_dump_json = lambda **_kw: "{}"
    obj.affected_holdings = []
    return obj


async def test_caffeinate_started_on_synthesis() -> None:
    """Popen called with ['caffeinate', '-i']; terminate() called on success."""
    from alphaswarm.web.routes import advisory as advisory_mod

    app_state = _make_app_state()
    portfolio = MagicMock()

    popen_handle = MagicMock()
    popen_handle.pid = 12345

    with (
        patch.object(advisory_mod.shutil, "which", return_value="/usr/bin/caffeinate"),
        patch.object(advisory_mod.subprocess, "Popen", return_value=popen_handle) as popen_mock,
        patch.object(advisory_mod, "synthesize", new=AsyncMock(return_value=_fake_report_obj())),
        patch.object(advisory_mod.aiofiles.os, "makedirs", new=AsyncMock()),
        patch.object(advisory_mod.aiofiles, "open", side_effect=_fake_aiofiles_open),
    ):
        await advisory_mod._run_advisory_synthesis(app_state, "cyc-1", portfolio)

    popen_mock.assert_called_once_with(
        ["caffeinate", "-i"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    popen_handle.terminate.assert_called_once()


async def test_caffeinate_terminated_on_synthesize_exception() -> None:
    """terminate() must fire even when synthesize() raises (finally guard)."""
    from alphaswarm.web.routes import advisory as advisory_mod

    app_state = _make_app_state()
    portfolio = MagicMock()

    popen_handle = MagicMock()

    with (
        patch.object(advisory_mod.shutil, "which", return_value="/usr/bin/caffeinate"),
        patch.object(advisory_mod.subprocess, "Popen", return_value=popen_handle),
        patch.object(advisory_mod, "synthesize", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        with pytest.raises(RuntimeError):
            await advisory_mod._run_advisory_synthesis(app_state, "cyc-2", portfolio)

    popen_handle.terminate.assert_called_once()


async def test_caffeinate_missing_logs_warning_no_raise() -> None:
    """Linux/CI path: shutil.which returns None → no Popen, synthesis still runs."""
    from alphaswarm.web.routes import advisory as advisory_mod

    app_state = _make_app_state()
    portfolio = MagicMock()

    with (
        patch.object(advisory_mod.shutil, "which", return_value=None),
        patch.object(advisory_mod.subprocess, "Popen") as popen_mock,
        patch.object(advisory_mod, "synthesize", new=AsyncMock(return_value=_fake_report_obj())),
        patch.object(advisory_mod.aiofiles.os, "makedirs", new=AsyncMock()),
        patch.object(advisory_mod.aiofiles, "open", side_effect=_fake_aiofiles_open),
    ):
        # No raise — synthesis path completes even without caffeinate.
        await advisory_mod._run_advisory_synthesis(app_state, "cyc-3", portfolio)

    popen_mock.assert_not_called()
