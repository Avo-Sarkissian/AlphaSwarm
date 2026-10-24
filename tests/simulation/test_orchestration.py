"""run_simulation's public surface (signature, SimulationDeps, no eager narratives).

Market-context assembly is tested in tests/test_market_context.py.

The run itself (rounds, model lifecycle, shocks, metrics) is tested on the scripted
harness in tests/engine/.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from alphaswarm.settings import AppSettings
from alphaswarm.simulation import SimulationDeps, run_simulation


def test_run_simulation_makes_no_eager_narrative_calls() -> None:
    """Narratives are generated lazily on first interview, never in the run."""
    from alphaswarm import simulation
    from alphaswarm.graph import GraphStateManager

    assert "generate_narratives" not in inspect.signature(simulation.run_simulation).parameters
    assert not hasattr(simulation, "_generate_decision_narratives")
    assert not hasattr(GraphStateManager, "write_decision_narratives")


def test_run_simulation_takes_deps_and_optional_callbacks() -> None:
    params = inspect.signature(run_simulation).parameters
    assert list(params)[:4] == ["rumor", "deps", "personas", "brackets"]
    assert params["on_round_complete"].default is None
    assert params["consume_shock"].default is None
    assert not {"ollama_client", "model_manager", "orchestrator_provider", "worker_provider"} & set(params)


def test_simulation_deps_requires_both_providers() -> None:
    with pytest.raises(TypeError):
        SimulationDeps(  # type: ignore[call-arg]
            settings=AppSettings(_env_file=None),  # type: ignore[call-arg]
            graph=MagicMock(),
            controller=MagicMock(),
        )


def test_simulation_deps_is_the_rounds_type_reexported() -> None:
    from alphaswarm import rounds, simulation

    assert simulation.SimulationDeps is rounds.SimulationDeps
    assert "SimulationDeps" in simulation.__all__
