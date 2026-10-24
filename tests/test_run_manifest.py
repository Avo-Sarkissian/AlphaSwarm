"""Run seed, per-call seeds, provenance and RunManifest (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from alphaswarm.inference.types import ProviderRole
from alphaswarm.manifest import (
    MAX_SEED,
    RunManifest,
    brackets_hash,
    build_run_manifest,
    derive_call_seed,
    derive_sim_seed,
    provenance_from_providers,
)
from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import BracketType
from tests.inference.fakes import FakeInferenceProvider

CYCLE_ID = "00000000-0000-4000-8000-000000000001"
FIXED_TS = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
ORCH = ProviderRole.ORCHESTRATOR
WORKER = ProviderRole.WORKER


def _provider(role: ProviderRole, model: str, *, local: bool) -> FakeInferenceProvider:
    return FakeInferenceProvider(role, model, scripted=[], is_local=local)


def _manifest(**overrides: Any) -> RunManifest:
    kwargs: dict[str, Any] = {
        "cycle_id": CYCLE_ID,
        "settings": AppSettings(_env_file=None),  # type: ignore[call-arg]
        "brackets": DEFAULT_BRACKETS,
        "provenance": provenance_from_providers(
            _provider(ORCH, "alphaswarm-orchestrator", local=True),
            _provider(WORKER, "alphaswarm-worker", local=True),
        ),
        "prompt_hashes": {"json_output_instructions": "a" * 64},
        "modifiers": {BracketType.QUANTS: "basis-trade specialist on the ZZZT deal"},
        "modifier_parse_tier": 1,
        "market_context": None,
        "sim_seed": 4242,
        "git_sha": "0" * 40,
        "git_dirty": False,
        "created_at": FIXED_TS,
    }
    kwargs.update(overrides)
    return build_run_manifest(**kwargs)


class TestSeeds:
    def test_call_seed_matches_pinned_values(self) -> None:
        """Pinned: a refactor must not silently change every run's model seeds."""
        assert derive_call_seed(42, "sell_side_01", 2) == 166941579
        assert derive_call_seed(42, "sell_side_01", 3) == 319804692
        assert derive_call_seed(42, "sell_side_01", 0) == 1237272625

    def test_sim_seed_matches_pinned_value(self) -> None:
        assert derive_sim_seed(CYCLE_ID) == 2059916226

    @pytest.mark.parametrize("agent_id", ["quants_01", "degens_15", "allocators_05"])
    @pytest.mark.parametrize("round_num", [0, 1, 2, 3])
    def test_call_seed_is_a_positive_int32(self, agent_id: str, round_num: int) -> None:
        assert 1 <= derive_call_seed(7, agent_id, round_num) <= MAX_SEED

    def test_call_seed_differs_by_each_input(self) -> None:
        base = derive_call_seed(42, "quants_01", 2)

        assert derive_call_seed(43, "quants_01", 2) != base
        assert derive_call_seed(42, "quants_02", 2) != base
        assert derive_call_seed(42, "quants_01", 3) != base


class TestProvenanceFromProviders:
    @pytest.mark.parametrize(
        ("orch_local", "worker_local", "labels", "mode"),
        [
            (True, True, ("ollama", "ollama"), "local"),
            (True, False, ("ollama", "cloud"), "mixed"),
            (False, True, ("cloud", "ollama"), "mixed"),
            (False, False, ("cloud", "cloud"), "cloud"),
        ],
    )
    def test_labels_and_mode(self, orch_local: bool, worker_local: bool, labels: tuple[str, str], mode: str) -> None:
        prov = provenance_from_providers(
            _provider(ORCH, "o-model", local=orch_local), _provider(WORKER, "w-model", local=worker_local)
        )

        assert (prov.orchestrator.provider, prov.worker.provider) == labels
        assert (prov.orchestrator.model, prov.worker.model) == ("o-model", "w-model")
        assert prov.orchestrator.digest is None and prov.worker.digest is None
        assert prov.inference_mode == mode


class TestBracketsHash:
    def test_stable_and_hex(self) -> None:
        first = brackets_hash(DEFAULT_BRACKETS)

        assert first == brackets_hash(list(DEFAULT_BRACKETS))
        assert len(first) == 64 and int(first, 16) >= 0

    def test_changes_with_the_table(self) -> None:
        changed = [DEFAULT_BRACKETS[0].model_copy(update={"temperature": 0.9}), *DEFAULT_BRACKETS[1:]]

        assert brackets_hash(changed) != brackets_hash(DEFAULT_BRACKETS)


class TestBuildRunManifest:
    def test_fills_every_field(self) -> None:
        m = _manifest()

        assert m.schema_id == "alphaswarm.run-manifest/1"
        assert (m.cycle_id, m.created_at, m.sim_seed) == (CYCLE_ID, FIXED_TS, 4242)
        assert m.alphaswarm_version
        assert (m.git_sha, m.git_dirty) == ("0" * 40, False)
        assert m.inference_mode == "local"
        assert (m.orchestrator.model, m.worker.model) == ("alphaswarm-orchestrator", "alphaswarm-worker")
        assert m.brackets_hash == brackets_hash(DEFAULT_BRACKETS)
        assert m.prompt_hashes == {"json_output_instructions": "a" * 64}
        assert set(m.modifiers) == {b.bracket_type.value for b in DEFAULT_BRACKETS}
        assert m.modifiers["quants"] == "basis-trade specialist on the ZZZT deal"
        assert m.modifiers["degens"] == ""
        assert m.modifier_parse_tier == 1
        assert m.num_rounds == 3
        assert m.simulation["peer_limit"] == 10
        assert "control_fraction" in m.simulation
        assert m.experiment_tag is None

    def test_no_modifiers_gives_empty_strings(self) -> None:
        m = _manifest(modifiers=None, modifier_parse_tier=None)

        assert set(m.modifiers.values()) == {""}
        assert m.modifier_parse_tier is None

    def test_experiment_tag_comes_from_settings(self) -> None:
        settings = AppSettings(  # type: ignore[call-arg]
            _env_file=None, simulation=SimulationSettings(experiment_tag="p7-3-control")
        )

        assert _manifest(settings=settings).experiment_tag == "p7-3-control"

    def test_json_uses_the_schema_alias_and_round_trips(self) -> None:
        m = _manifest(market_context="ZZZT Holdings: price 12.34 (fictional)")
        payload = json.loads(m.model_dump_json(by_alias=True))

        assert payload["schema"] == "alphaswarm.run-manifest/1"
        assert "schema_id" not in payload
        assert RunManifest.model_validate_json(m.model_dump_json(by_alias=True)) == m

    def test_unknown_fields_are_rejected(self) -> None:
        payload = json.loads(_manifest().model_dump_json(by_alias=True))

        with pytest.raises(ValidationError):
            RunManifest.model_validate({**payload, "api_key": "sk-not-allowed"})
