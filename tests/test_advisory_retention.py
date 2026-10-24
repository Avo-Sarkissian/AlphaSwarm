"""The advisory job writes owner-only files, keeps only the newest N and writes
nothing when the orchestrator never returns a valid reply.

See docs/DECISIONS.md#adr-advisory-pipeline.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import alphaswarm.services.advisory as advisory_module
from alphaswarm.errors import StructuredOutputError
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.services.advisory import AdvisoryService
from alphaswarm.settings import AppSettings
from tests.inference.fakes import FakeInferenceProvider
from tests.support.web_app import CYCLE_A, CYCLE_B, CYCLE_UNKNOWN, advisory_service_for, route_test_settings


class _FakeReport:
    total_holdings = 1
    affected_holdings = 0

    def model_dump_json(self, *, indent: int) -> str:
        return json.dumps({"cycle_id": CYCLE_A, "items": []}, indent=indent)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


class _SwarmReads:
    """The graph reads the real ``synthesize`` makes, with fictional cycle data."""

    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 52, "sell_count": 21, "hold_count": 24, "parse_error_count": 3, "total": 100}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_final_round_decisions(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


def _job_service(
    settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: FakeInferenceProvider | None = None,
) -> AdvisoryService:
    """An offline AdvisoryService whose job runs the real service path.

    Without *provider* the synthesis is faked and returns a fixed report; with
    one, the real ``synthesize`` runs on *provider* over ``_SwarmReads``.
    """
    orchestrator = provider or FakeInferenceProvider(role=ProviderRole.ORCHESTRATOR, model="fake", scripted=[])
    monkeypatch.setattr(
        "alphaswarm.inference.factory.build_providers",
        lambda *_a, **_k: BuiltProviders(
            orchestrator=orchestrator,  # type: ignore[arg-type]
            worker=orchestrator,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        ),
    )
    # load_inference_config is NOT patched: route_test_settings points at a missing
    # tmp file, so the real loader returns the local Ollama defaults and the job's
    # cloud re-check passes.

    if provider is None:

        async def _synthesize(**_kwargs: Any) -> _FakeReport:
            return _FakeReport()

        monkeypatch.setattr(advisory_module, "synthesize", _synthesize)
    return advisory_service_for(
        settings,
        portfolio=_portfolio(),
        graph=None if provider is None else _SwarmReads(),
    )


def _write_old_advisories(advisory_dir: Path, *cycle_ids: str) -> None:
    advisory_dir.mkdir()
    for offset, cycle_id in enumerate(cycle_ids):
        old = advisory_dir / f"{cycle_id}_advisory.json"
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (1_000 + offset, 1_000 + offset))


async def test_job_writes_owner_only_and_keeps_the_newest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = route_test_settings(tmp_path, advisory_keep_last=2)
    advisory_dir = tmp_path / "advisory"
    _write_old_advisories(advisory_dir, CYCLE_B, CYCLE_UNKNOWN)
    await _job_service(settings, monkeypatch).generate(CYCLE_A)
    names = sorted(p.name for p in advisory_dir.iterdir())
    assert names == sorted([f"{CYCLE_A}_advisory.json", f"{CYCLE_UNKNOWN}_advisory.json"])
    if os.name == "posix":
        new_file = advisory_dir / f"{CYCLE_A}_advisory.json"
        assert stat.S_IMODE(new_file.stat().st_mode) == 0o600


async def test_a_failed_prune_does_not_fail_the_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = route_test_settings(tmp_path, advisory_keep_last=1)
    advisory_dir = tmp_path / "advisory"
    _write_old_advisories(advisory_dir, CYCLE_B)
    service = _job_service(settings, monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> list[Path]:
        raise PermissionError("read-only directory")

    monkeypatch.setattr(advisory_module, "prune_old_files", _boom)
    await service.generate(CYCLE_A)
    names = sorted(p.name for p in advisory_dir.iterdir())
    assert names == sorted([f"{CYCLE_A}_advisory.json", f"{CYCLE_B}_advisory.json"])


async def test_two_invalid_replies_write_no_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job fails before anything is written: no advisory, no temp file, older files kept."""
    # keep_last=1: a written advisory would also have pruned CYCLE_B's file.
    settings = route_test_settings(tmp_path, advisory_keep_last=1)
    advisory_dir = tmp_path / "advisory"
    _write_old_advisories(advisory_dir, CYCLE_B)
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake",
        scripted=[InferenceResult(content="prose, not JSON", model="fake")] * 2,
    )
    service = _job_service(settings, monkeypatch, provider=provider)
    with pytest.raises(StructuredOutputError):
        await service.generate(CYCLE_A)
    assert len(provider.calls) == 2
    assert sorted(p.name for p in advisory_dir.iterdir()) == [f"{CYCLE_B}_advisory.json"]


def test_keep_last_default_and_bounds() -> None:
    assert AppSettings(_env_file=None).advisory_keep_last == 20  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, advisory_keep_last=0)  # type: ignore[call-arg]
