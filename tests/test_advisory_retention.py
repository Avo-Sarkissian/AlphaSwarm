"""The advisory job writes owner-only files and keeps only the newest N.

See docs/DECISIONS.md#adr-advisory-pipeline.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import alphaswarm.web.routes.advisory as advisory_module
from alphaswarm.config import AppSettings
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import ProviderRole
from tests.inference.fakes import FakeInferenceProvider
from tests.support.web_app import CYCLE_A, CYCLE_B, CYCLE_UNKNOWN, route_test_settings


class _FakeReport:
    affected_holdings = 0

    def model_dump_json(self, *, indent: int) -> str:
        return json.dumps({"cycle_id": CYCLE_A, "items": []}, indent=indent)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


def _job_app_state(settings: AppSettings, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """An offline app state whose advisory job writes a fake report through the real path."""
    provider = FakeInferenceProvider(role=ProviderRole.ORCHESTRATOR, model="fake", scripted=[])
    monkeypatch.setattr(
        advisory_module,
        "build_providers",
        lambda *_a, **_k: BuiltProviders(
            orchestrator=provider,  # type: ignore[arg-type]
            worker=provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        ),
    )
    # load_inference_config is NOT patched: route_test_settings points at a missing
    # tmp file, so the real loader returns the local Ollama defaults and the job's
    # cloud re-check passes.

    async def _synthesize(**_kwargs: Any) -> _FakeReport:
        return _FakeReport()

    monkeypatch.setattr(advisory_module, "synthesize", _synthesize)
    # The job asks the shared client for its host and whether the model runs remotely.
    client = SimpleNamespace(
        base_url="http://127.0.0.1:11434",
        is_remote_model=AsyncMock(return_value=False),
    )
    return SimpleNamespace(
        settings=settings,
        graph_manager=object(),
        ollama_client=client,
        model_manager=object(),
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
    app_state = _job_app_state(settings, monkeypatch)
    await advisory_module._run_advisory_synthesis(app_state, CYCLE_A, _portfolio())  # type: ignore[arg-type]
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
    app_state = _job_app_state(settings, monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> list[Path]:
        raise PermissionError("read-only directory")

    monkeypatch.setattr(advisory_module, "prune_old_files", _boom)
    await advisory_module._run_advisory_synthesis(app_state, CYCLE_A, _portfolio())  # type: ignore[arg-type]
    names = sorted(p.name for p in advisory_dir.iterdir())
    assert names == sorted([f"{CYCLE_A}_advisory.json", f"{CYCLE_B}_advisory.json"])


def test_keep_last_default_and_bounds() -> None:
    assert AppSettings(_env_file=None).advisory_keep_last == 20  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, advisory_keep_last=0)  # type: ignore[call-arg]
