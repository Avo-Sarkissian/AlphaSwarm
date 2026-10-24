"""A deterministic RunManifest for graph and engine tests (fictional values only)."""

from __future__ import annotations

from datetime import UTC, datetime

from alphaswarm.inference.types import ProviderRole
from alphaswarm.manifest import RunManifest, build_run_manifest, provenance_from_providers
from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.settings import AppSettings, SimulationSettings
from tests.inference.fakes import FakeInferenceProvider

DEFAULT_MANIFEST_CYCLE_ID = "00000000-0000-4000-8000-0000000000aa"


def make_manifest(*, cycle_id: str = DEFAULT_MANIFEST_CYCLE_ID, tag: str | None = None) -> RunManifest:
    settings = AppSettings(  # type: ignore[call-arg]
        _env_file=None, simulation=SimulationSettings(experiment_tag=tag)
    )
    orchestrator = FakeInferenceProvider(ProviderRole.ORCHESTRATOR, "alphaswarm-orchestrator", scripted=[])
    worker = FakeInferenceProvider(ProviderRole.WORKER, "alphaswarm-worker", scripted=[])
    return build_run_manifest(
        cycle_id=cycle_id,
        settings=settings,
        brackets=DEFAULT_BRACKETS,
        provenance=provenance_from_providers(orchestrator, worker),
        prompt_hashes={"json_output_instructions": "0" * 64},
        modifiers=None,
        modifier_parse_tier=None,
        market_context=None,
        sim_seed=4242,
        git_sha="0" * 40,
        git_dirty=False,
        created_at=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
    )
