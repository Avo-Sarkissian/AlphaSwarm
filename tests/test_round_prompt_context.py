"""build_round_context: peer strategies, control holdout, own priors (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

from alphaswarm.peers import (
    build_peer_contexts,
    build_random_peer_contexts,
    build_round_context,
    select_control_ids,
)
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.settings import SimulationSettings
from alphaswarm.types import AgentDecision, SignalType

PERSONAS = generate_personas(DEFAULT_BRACKETS)
RUN_SEED = "4242"


def _decisions(*, failed: frozenset[str] = frozenset()) -> list[tuple[str, AgentDecision]]:
    return [
        (
            p.id,
            AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0)
            if p.id in failed
            else AgentDecision(
                signal=SignalType.BUY if i % 3 else SignalType.SELL,
                confidence=0.6,
                rationale=f"view {i} on the ZZZT deal",
            ),
        )
        for i, p in enumerate(PERSONAS)
    ]


def test_round_one_has_no_peers_no_priors_but_a_control_set() -> None:
    ctx = build_round_context(PERSONAS, (), 1, sim=SimulationSettings(control_fraction=0.2), run_seed=RUN_SEED)

    assert ctx.peer_blocks == (None,) * 100
    assert ctx.own_prior_lines == (None,) * 100
    assert ctx.exposures == ((),) * 100
    assert len(ctx.control_ids) == 20


def test_stratified_without_holdout_or_memory_equals_the_peer_builder() -> None:
    sim = SimulationSettings(own_prior_memory=False, control_fraction=0.0)
    decisions = _decisions()

    ctx = build_round_context(PERSONAS, decisions, 2, sim=sim, run_seed=RUN_SEED)
    peers = build_peer_contexts(PERSONAS, decisions, 1, sim=sim, run_seed=RUN_SEED)

    assert ctx.peer_blocks == tuple(peers.contexts)
    assert ctx.exposures == tuple(peers.exposures)
    assert ctx.own_prior_lines == (None,) * 100
    assert ctx.control_ids == frozenset()


def test_control_readers_see_no_peers_but_keep_their_own_prior() -> None:
    decisions = _decisions()
    with_holdout = build_round_context(
        PERSONAS, decisions, 2, sim=SimulationSettings(control_fraction=0.2), run_seed=RUN_SEED
    )
    without = build_round_context(
        PERSONAS, decisions, 2, sim=SimulationSettings(control_fraction=0.0), run_seed=RUN_SEED
    )
    control = select_control_ids(PERSONAS, fraction=0.2, run_seed=RUN_SEED)

    assert with_holdout.control_ids == control
    for i, persona in enumerate(PERSONAS):
        if persona.id in control:
            assert with_holdout.peer_blocks[i] is None
            assert with_holdout.exposures[i] == ()
            assert with_holdout.own_prior_lines[i] is not None
        else:
            assert with_holdout.peer_blocks[i] == without.peer_blocks[i]
            assert with_holdout.exposures[i] == without.exposures[i]


def test_holdout_is_the_same_set_in_every_round() -> None:
    sim = SimulationSettings(control_fraction=0.2)
    decisions = _decisions()

    r2 = build_round_context(PERSONAS, decisions, 2, sim=sim, run_seed=RUN_SEED)
    r3 = build_round_context(PERSONAS, decisions, 3, sim=sim, run_seed=RUN_SEED)

    assert r2.control_ids == r3.control_ids


def test_own_priors_follow_previous_decisions_and_skip_failures() -> None:
    failed = frozenset({PERSONAS[0].id})
    ctx = build_round_context(PERSONAS, _decisions(failed=failed), 2, sim=SimulationSettings(), run_seed=RUN_SEED)

    assert ctx.own_prior_lines[0] is None
    assert ctx.own_prior_lines[1] is not None
    assert ctx.own_prior_lines[1].startswith("Your Round 1 position: ")


def test_strategy_none_shows_nobody_anything() -> None:
    ctx = build_round_context(
        PERSONAS, _decisions(), 2, sim=SimulationSettings(peer_strategy="none"), run_seed=RUN_SEED
    )

    assert ctx.peer_blocks == (None,) * 100
    assert ctx.exposures == ((),) * 100


def test_random_strategy_samples_eligible_peers_deterministically() -> None:
    failed = frozenset({PERSONAS[5].id, PERSONAS[50].id})
    decisions = _decisions(failed=failed)
    sim = SimulationSettings(peer_strategy="random")

    first = build_random_peer_contexts(PERSONAS, decisions, 1, sim=sim, run_seed=RUN_SEED)
    again = build_random_peer_contexts(PERSONAS, decisions, 1, sim=sim, run_seed=RUN_SEED)
    stratified = build_peer_contexts(PERSONAS, decisions, 1, sim=sim, run_seed=RUN_SEED)

    assert first == again
    assert first.exposures != stratified.exposures
    for persona, shown in zip(PERSONAS, first.exposures, strict=True):
        assert persona.id not in shown
        assert not set(shown) & failed
        assert len(shown) <= sim.peer_limit
        assert len(set(shown)) == len(shown)
