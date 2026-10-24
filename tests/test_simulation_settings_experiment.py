"""Experiment knobs on SimulationSettings (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

import json
import os

import pytest
from pydantic import ValidationError

from alphaswarm.settings import AppSettings, SimulationSettings

# Product defaults: market context in every round; holdout off, experiment runs
# set 0.2 (docs/DECISIONS.md#adr-diverse-peer-context).
EXPECTED_MARKET_CONTEXT_ROUNDS = 3
EXPECTED_CONTROL_FRACTION = 0.0


def _clear_simulation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_SIMULATION__"):
            monkeypatch.delenv(key, raising=False)


def test_experiment_knob_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_simulation_env(monkeypatch)
    sim = AppSettings(_env_file=None).simulation  # type: ignore[call-arg]

    assert sim.peer_strategy == "stratified"
    assert sim.own_prior_memory is True
    assert sim.market_context_rounds == EXPECTED_MARKET_CONTEXT_ROUNDS
    assert sim.show_bracket_labels is True
    assert sim.show_confidence is True
    assert sim.uniform_temperature is None
    assert sim.control_fraction == EXPECTED_CONTROL_FRACTION
    assert sim.shock_treatment_split is False
    assert sim.sim_seed is None
    assert sim.experiment_tag is None
    assert sim.retest_round1 is False


def test_experiment_knobs_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_simulation_env(monkeypatch)
    overrides = {
        "PEER_STRATEGY": "random",
        "OWN_PRIOR_MEMORY": "false",
        "MARKET_CONTEXT_ROUNDS": "2",
        "SHOW_BRACKET_LABELS": "false",
        "SHOW_CONFIDENCE": "false",
        "UNIFORM_TEMPERATURE": "0.7",
        "CONTROL_FRACTION": "0.2",
        "SHOCK_TREATMENT_SPLIT": "true",
        "SIM_SEED": "4242",
        "EXPERIMENT_TAG": "p7-3-control",
        "RETEST_ROUND1": "true",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(f"ALPHASWARM_SIMULATION__{key}", value)

    sim = AppSettings(_env_file=None).simulation  # type: ignore[call-arg]

    assert sim.peer_strategy == "random"
    assert sim.own_prior_memory is False
    assert sim.market_context_rounds == 2
    assert (sim.show_bracket_labels, sim.show_confidence) == (False, False)
    assert sim.uniform_temperature == 0.7
    assert sim.control_fraction == 0.2
    assert sim.shock_treatment_split is True
    assert sim.sim_seed == 4242
    assert sim.experiment_tag == "p7-3-control"
    assert sim.retest_round1 is True


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("PEER_STRATEGY", "bandit", "peer_strategy"),
        ("OWN_PRIOR_MEMORY", "maybe", "own_prior_memory"),
        ("MARKET_CONTEXT_ROUNDS", "4", "market_context_rounds"),
        ("MARKET_CONTEXT_ROUNDS", "-1", "market_context_rounds"),
        ("UNIFORM_TEMPERATURE", "2.5", "uniform_temperature"),
        ("CONTROL_FRACTION", "0.6", "control_fraction"),
        ("CONTROL_FRACTION", "-0.1", "control_fraction"),
        ("SIM_SEED", "0", "sim_seed"),
        ("SIM_SEED", "2147483648", "sim_seed"),
        ("SIM_SEED", "abc", "sim_seed"),
        ("EXPERIMENT_TAG", "my tag!", "experiment_tag"),
        ("EXPERIMENT_TAG", "x" * 65, "experiment_tag"),
    ],
)
def test_experiment_knobs_reject_out_of_range(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str, field: str
) -> None:
    """A bad knob fails at settings load and names the field."""
    _clear_simulation_env(monkeypatch)
    monkeypatch.setenv(f"ALPHASWARM_SIMULATION__{key}", value)

    with pytest.raises(ValidationError, match=field):
        AppSettings(_env_file=None)  # type: ignore[call-arg]


def test_model_dump_is_json_and_complete() -> None:
    """The run manifest stores this dump; every knob must be in it."""
    dumped = SimulationSettings().model_dump(mode="json")

    json.dumps(dumped)  # must not raise
    for key in (
        "peer_limit",
        "min_brackets",
        "bracket_cap",
        "personal_boost",
        "peer_budget_chars",
        "peer_strategy",
        "own_prior_memory",
        "market_context_rounds",
        "show_bracket_labels",
        "show_confidence",
        "uniform_temperature",
        "control_fraction",
        "shock_treatment_split",
        "sim_seed",
        "experiment_tag",
        "retest_round1",
    ):
        assert key in dumped
