"""Run-scoped log context (docs/DECISIONS.md#adr-security-2026-08)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import structlog

import alphaswarm.web.routes.advisory as advisory_module
import alphaswarm.web.routes.report as report_module
from alphaswarm.batch_dispatcher import dispatch_wave
from alphaswarm.config import GovernorSettings
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.types import WorkerPersonaConfig
from tests.inference.fakes import FakeInferenceProvider
from tests.support.controllers import ImmediateController
from tests.support.web_app import CYCLE_A, route_test_settings

_BUY = '{"signal": "buy", "confidence": 0.8, "sentiment": 0.4, "rationale": "ok", "cited_agents": []}'


class _StopError(Exception):
    """Raised by a patched dependency once the context has been recorded."""


def _persona(agent_id: str, bracket: str) -> WorkerPersonaConfig:
    return {
        "agent_id": agent_id,
        "bracket": bracket,
        "influence_weight": 0.5,
        "temperature": 0.5,
        "system_prompt": "p",
        "risk_profile": "0.5",
    }


def _record_then_stop(seen: list[dict[str, Any]]) -> Any:
    def _load(*_args: Any, **_kwargs: Any) -> object:
        seen.append(dict(structlog.contextvars.get_contextvars()))
        raise _StopError

    return _load


def _app_state(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        settings=route_test_settings(tmp_path),
        graph_manager=object(),
        ollama_client=object(),
        model_manager=object(),
    )


async def test_each_agent_task_binds_round_and_agent_id() -> None:
    seen: list[dict[str, Any]] = []

    def _script(**_kwargs: Any) -> InferenceResult:
        seen.append(dict(structlog.contextvars.get_contextvars()))
        return InferenceResult(content=_BUY, model="fake")

    provider = FakeInferenceProvider(role=ProviderRole.WORKER, model="fake", scripted=_script)
    await dispatch_wave(
        [_persona("quants_01", "quants"), _persona("macro_01", "macro")],
        ImmediateController(),
        provider,
        "rumor",
        GovernorSettings(jitter_min_seconds=0.0, jitter_max_seconds=0.0),
        round_num=2,
    )
    assert sorted((c["round"], c["agent_id"]) for c in seen) == [(2, "macro_01"), (2, "quants_01")]
    assert "round" not in structlog.contextvars.get_contextvars()  # caller's context untouched


async def test_advisory_job_binds_cycle_and_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(advisory_module, "load_inference_config", _record_then_stop(seen))
    with pytest.raises(_StopError):
        await advisory_module._run_advisory_synthesis(_app_state(tmp_path), CYCLE_A, object())  # type: ignore[arg-type]
    assert (seen[0]["cycle_id"], seen[0]["job"]) == (CYCLE_A, "advisory")


async def test_report_job_binds_cycle_and_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(report_module, "load_inference_config", _record_then_stop(seen))
    with pytest.raises(_StopError):
        await report_module._run_report_generation(_app_state(tmp_path), CYCLE_A)  # type: ignore[arg-type]
    assert (seen[0]["cycle_id"], seen[0]["job"]) == (CYCLE_A, "report")
