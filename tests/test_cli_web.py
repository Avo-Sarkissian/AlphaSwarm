"""`alphaswarm web` configures logging first and lets uvicorn use it (docs/DECISIONS.md#adr-security-2026-08)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi import FastAPI

from alphaswarm.logging import BRIDGE_HANDLER_NAME


@pytest.fixture(autouse=True)
def _restore_structlog() -> Iterator[None]:
    # _handle_web configures structlog globally; put the prior config back so
    # loggers cached earlier in the session keep working.
    saved = structlog.get_config()
    yield
    structlog.configure(**saved)


def test_handle_web_bridges_uvicorn_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from alphaswarm import cli

    calls: dict[str, Any] = {}

    def _fake_run(app: object, **kwargs: Any) -> None:
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    cli._handle_web("127.0.0.1", 8123)
    assert isinstance(calls["app"], FastAPI)
    assert calls["log_config"] is None
    assert (calls["host"], calls["port"]) == ("127.0.0.1", 8123)
    assert BRIDGE_HANDLER_NAME in [h.get_name() for h in logging.getLogger().handlers]
