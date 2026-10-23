"""Advisory errors never carry holdings values (docs/DECISIONS.md#adr-holdings-isolation).

A pydantic ValidationError echoes the model's input in str() and repr(), so logs,
retry prompts and HTTP bodies carry error locations and types only.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import alphaswarm.services.advisory as advisory_module
import alphaswarm.services.jobs as jobs_module
import alphaswarm.services.post_run as post_run_module
from alphaswarm.advisory import AdvisoryReport, synthesize
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.logging import validation_error_summary
from alphaswarm.services.advisory import AdvisoryService
from alphaswarm.services.post_run import AdvisoryGate, PostRunPipeline
from tests.inference.fakes import FakeInferenceProvider
from tests.support.web_app import CYCLE_A, advisory_service_for, route_test_settings

# Three failures: confidence > 1, an unparsable exposure, and an invented top-level key.
_INVALID = json.dumps(
    {
        "cycle_id": "c1",
        "generated_at": "2026-10-03T12:00:00+00:00",
        "portfolio_outlook": "x",
        "items": [
            {
                "ticker": "ZZZT",
                "consensus_signal": "BUY",
                "confidence": "12.3456",
                "rationale_summary": "x",
                "position_exposure": "1234.56 USD",
            }
        ],
        "total_holdings": 1,
        "affected_holdings": 0,
        "ZZZT": "an invented top-level key",
    }
)
_VALID = json.dumps(
    {
        "cycle_id": "c1",
        "generated_at": "2026-10-03T12:00:00+00:00",
        "portfolio_outlook": "Flat.",
        "items": [],
        "total_holdings": 1,
        "affected_holdings": 0,
    }
)
_VALUES = ("ZZZT", "12.3456", "1234.56")
# The orchestrator's reply model (AdvisoryLLMOutput): an unparsable confidence and
# a signal outside the enum, both carrying fictional position values.
_INVALID_LLM_REPLY = json.dumps(
    {
        "portfolio_outlook": "x",
        "items": [
            {
                "ticker": "ZZZT",
                "signal": "BUY 1234.56 USD",
                "confidence": "12.3456 shares",
                "rationale": "x",
            }
        ],
        "ZZZT": "an invented top-level key",
    }
)


def _validation_error() -> ValidationError:
    try:
        AdvisoryReport.model_validate_json(_INVALID)
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


class _Graph:
    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 0, "sell_count": 0, "hold_count": 1, "total": 1}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return ""


class _RecordingLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, kwargs))

    info = warning = error = debug = exception = _record

    def kwargs_for(self, event: str) -> dict[str, Any]:
        matches = [kw for name, kw in self.events if name == event]
        assert len(matches) == 1, f"expected one {event!r} event, got {len(matches)}"
        return matches[0]


def _assert_no_values(fields: dict[str, Any]) -> None:
    rendered = json.dumps(fields, default=str)
    for value in _VALUES:
        assert value not in rendered


def test_summary_has_locations_and_types_but_no_values() -> None:
    summary = validation_error_summary(_validation_error())
    _assert_no_values(summary)
    assert summary["error_count"] == 3
    locations = summary["error_locations"]
    assert isinstance(locations, list)
    assert "items.0.position_exposure" in locations
    assert "items.0.confidence" in locations
    assert summary["error_types"] == ["decimal_parsing", "extra_forbidden", "less_than_equal"]


def test_extra_keys_are_masked() -> None:
    locations = validation_error_summary(_validation_error())["error_locations"]
    assert isinstance(locations, list)
    assert "<extra>" in locations


def test_other_exceptions_have_no_summary() -> None:
    assert validation_error_summary(RuntimeError("ZZZT 1234.56")) == {}


def test_summary_follows_the_exception_chain() -> None:
    try:
        try:
            raise _validation_error()
        except ValidationError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        summary = validation_error_summary(outer)
    assert summary["error_count"] == 3
    _assert_no_values(summary)


async def test_retry_prompt_names_locations_not_values() -> None:
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="test-orch",
        scripted=[
            InferenceResult(content=_INVALID_LLM_REPLY, model="test-orch"),
            InferenceResult(content=_VALID, model="test-orch"),
        ],
    )
    portfolio = PortfolioSnapshot(
        holdings=(Holding(ticker="QQQX", qty=Decimal("40"), cost_basis=Decimal("860.43")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )
    await synthesize(
        cycle_id="c1",
        portfolio=portfolio,
        graph_manager=_Graph(),  # type: ignore[arg-type]
        provider=provider,
    )
    retry = provider.calls[1]["messages"][-1]["content"]
    assert retry.startswith("Your previous reply did not match the required JSON schema.")
    assert "items.0.confidence" in retry and "items.0.signal" in retry
    for value in ("1234.56", "12.3456", "ZZZT"):
        assert value not in retry


def _validation_failing_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AdvisoryService:
    """An offline AdvisoryService whose synthesis raises the fictional ValidationError."""
    provider = FakeInferenceProvider(role=ProviderRole.ORCHESTRATOR, model="fake", scripted=[])
    monkeypatch.setattr(
        "alphaswarm.inference.factory.build_providers",
        lambda *_a, **_k: BuiltProviders(
            orchestrator=provider,  # type: ignore[arg-type]
            worker=provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        ),
    )
    # load_inference_config is NOT patched: route_test_settings points at a missing
    # tmp file, so the real loader returns the local Ollama defaults; the client is
    # a loopback server that reports the orchestrator model as local.

    async def _synthesize(**_kwargs: Any) -> Any:
        raise _validation_error()

    monkeypatch.setattr(advisory_module, "synthesize", _synthesize)
    return advisory_service_for(route_test_settings(tmp_path), portfolio=SimpleNamespace(holdings=("fictional",)))


async def test_service_failure_log_has_no_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RecordingLog()
    monkeypatch.setattr(advisory_module, "log", recorder)
    service = _validation_failing_service(tmp_path, monkeypatch)
    with pytest.raises(ValidationError):
        await service.generate(CYCLE_A)
    failed = recorder.kwargs_for("advisory_generation_failed")
    assert "error" not in failed
    assert "exc_info" not in failed
    assert failed["exc_type"] == "ValidationError"
    assert "items.0.position_exposure" in failed["error_locations"]
    _assert_no_values(failed)


async def _failed_task(exc: BaseException) -> asyncio.Task[None]:
    async def _fail() -> None:
        raise exc

    task: asyncio.Task[None] = asyncio.get_running_loop().create_task(_fail())
    await asyncio.wait({task})
    return task


async def test_job_runner_logs_a_validation_error_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RecordingLog()
    monkeypatch.setattr(jobs_module, "log", recorder)
    service = _validation_failing_service(tmp_path, monkeypatch)

    with pytest.raises(ValidationError):
        await service.start(CYCLE_A)

    recorded = recorder.kwargs_for("job_failed")
    assert "exc_info" not in recorded
    assert recorded["exc_type"] == "ValidationError"
    assert recorded["error_count"] == 3
    _assert_no_values(recorded)
    assert service.jobs.error_for("advisory", CYCLE_A) == "advisory_generation_failed"


class _FailingAdvisoryJobs:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def advisory_gate(self, cycle_id: str) -> AdvisoryGate:
        return "run"

    async def run_advisory(self, cycle_id: str) -> None:
        raise self._exc

    async def run_report(self, cycle_id: str) -> None:
        return None


async def test_post_run_logs_a_validation_error_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RecordingLog()
    monkeypatch.setattr(post_run_module, "log", recorder)

    outcome = await PostRunPipeline(jobs=_FailingAdvisoryJobs(_validation_error())).on_complete(CYCLE_A)

    assert (outcome.advisory, outcome.report) == ("failed", "ran")
    failed = recorder.kwargs_for("auto_advisory_failed")
    assert "exc_info" not in failed
    assert failed["exc_type"] == "ValidationError"
    assert failed["error_count"] == 3
    _assert_no_values(failed)
