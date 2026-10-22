"""Fast-track knobs: own-prior memory and the control holdout.

See docs/DECISIONS.md#adr-diverse-peer-context.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from alphaswarm.config import AppSettings

# Product default: holdout off; experiment runs set 0.2
# (docs/DECISIONS.md#adr-diverse-peer-context).
EXPECTED_CONTROL_FRACTION = 0.0


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_SIMULATION__"):
            monkeypatch.delenv(key, raising=False)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    sim = AppSettings(_env_file=None).simulation  # type: ignore[call-arg]

    assert sim.own_prior_memory is True
    assert sim.control_fraction == EXPECTED_CONTROL_FRACTION


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("ALPHASWARM_SIMULATION__OWN_PRIOR_MEMORY", "false")
    monkeypatch.setenv("ALPHASWARM_SIMULATION__CONTROL_FRACTION", "0.2")

    sim = AppSettings(_env_file=None).simulation  # type: ignore[call-arg]

    assert (sim.own_prior_memory, sim.control_fraction) == (False, 0.2)


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("CONTROL_FRACTION", "0.6", "control_fraction"),
        ("CONTROL_FRACTION", "-0.1", "control_fraction"),
        ("OWN_PRIOR_MEMORY", "maybe", "own_prior_memory"),
    ],
)
def test_bad_values_fail_at_load(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str, field: str
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv(f"ALPHASWARM_SIMULATION__{key}", value)

    with pytest.raises(ValidationError, match=field):
        AppSettings(_env_file=None)  # type: ignore[call-arg]
