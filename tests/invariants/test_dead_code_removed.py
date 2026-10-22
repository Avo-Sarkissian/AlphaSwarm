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


def test_dead_graph_methods_are_gone() -> None:
    import alphaswarm.graph as graph

    assert not hasattr(graph, "PeerDecision"), "alphaswarm.graph.PeerDecision is back"
    assert hasattr(graph, "RankedPost"), "RankedPost is still used by peer formatting"
    dead = ("create_cycle", "read_ranked_posts", "write_read_post_edges", "read_peer_decisions")
    for name in dead:
        assert not hasattr(graph.GraphStateManager, name), f"GraphStateManager.{name} is back"


def test_ollama_generate_and_parse_error_are_gone() -> None:
    import alphaswarm.errors as errors
    from alphaswarm.ollama_client import OllamaClient

    assert not hasattr(OllamaClient, "generate"), "narratives use provider.chat"
    assert not hasattr(OllamaClient, "_generate_with_backoff")
    assert not hasattr(errors, "ParseError"), "parse failures are PARSE_ERROR decisions"


def test_drain_rationales_shim_is_gone() -> None:
    from alphaswarm.state import StateStore

    assert not hasattr(StateStore, "drain_rationales"), "snapshots carry the rationale window"


def test_report_sentinel_and_missing_template_mapping_are_gone() -> None:
    import alphaswarm.report as report

    assert not hasattr(report, "write_sentinel"), "nothing reads .alphaswarm/last_report.json"
    assert "portfolio_impact" not in report.TOOL_TO_TEMPLATE, "10_portfolio_impact.j2 never existed"
    assert "portfolio_impact" not in report.SECTION_ORDER
