"""run_simulation stays a short loop over run_round (docs/DECISIONS.md#adr-round-runner)."""

from __future__ import annotations

import inspect

import pytest

from alphaswarm import simulation

MAX_LINES = 100


@pytest.mark.parametrize("name", ["run_simulation", "_run_simulation"])
def test_run_simulation_stays_short(name: str) -> None:
    lines, _ = inspect.getsourcelines(getattr(simulation, name))
    assert len(lines) <= MAX_LINES, f"{name} is {len(lines)} lines; move round work into rounds.py or a helper"
