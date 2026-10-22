"""Dead code removed in Phase 1 stays removed.

Each name below had no production caller and was kept alive only by its own
tests. If an assertion here fails, a deleted symbol came back: delete it again,
or give it a real caller and remove its line from this file.
"""

from __future__ import annotations

import inspect


def test_simulation_dead_helpers_are_gone() -> None:
    import alphaswarm.simulation as simulation

    for name in ("_dispatch_round", "RoundDispatchResult", "_push_top_rationales"):
        assert not hasattr(simulation, name), f"alphaswarm.simulation.{name} is back"


def test_run_round1_requires_the_seeded_cycle() -> None:
    from alphaswarm.simulation import run_round1

    param = inspect.signature(run_round1).parameters["pre_injected"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
