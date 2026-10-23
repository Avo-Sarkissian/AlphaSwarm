"""StateSink is exactly the engine-facing StateStore surface (docs/DECISIONS.md#adr-round-runner)."""

from __future__ import annotations

import inspect

from alphaswarm.state import StateSink, StateStore

ENGINE_METHODS = {
    "set_phase",
    "set_round",
    "update_agent_state",
    "push_rationale",
    "set_bracket_summaries",
    "record_tokens",
    "set_cycle",
    "set_num_rounds",
    "bump_edges_version",
    "begin_run",
    "record_applied_shock",
}


def _sink_methods() -> set[str]:
    return {name for name, value in vars(StateSink).items() if inspect.isfunction(value) and not name.startswith("_")}


def test_sink_lists_exactly_the_engine_methods() -> None:
    assert _sink_methods() == ENGINE_METHODS


def test_store_matches_every_sink_method() -> None:
    for name in sorted(ENGINE_METHODS):
        sink_fn, store_fn = getattr(StateSink, name), getattr(StateStore, name)
        assert inspect.iscoroutinefunction(sink_fn) == inspect.iscoroutinefunction(store_fn), name
        sink_params = [(p.name, p.kind, p.default) for p in inspect.signature(sink_fn).parameters.values()]
        store_params = [(p.name, p.kind, p.default) for p in inspect.signature(store_fn).parameters.values()]
        assert sink_params == store_params, name


def test_web_side_calls_stay_off_the_sink() -> None:
    assert not {"set_last_error", "set_pending_shock", "set_job_status"} & _sink_methods()
