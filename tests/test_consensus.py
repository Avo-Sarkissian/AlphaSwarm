"""Consensus estimators on hand-built distributions (docs/DECISIONS.md#adr-consensus-estimators)."""

from __future__ import annotations

import math
import random

import pytest

from alphaswarm.consensus import (
    NET_SCORE_DEADBAND,
    WEIGHTINGS,
    Dispersion,
    Vote,
    bootstrap_ci,
    bootstrap_ci_votes,
    consensus_rng,
    dispersion,
    estimate_consensus,
    lean_from_score,
    net_score,
    votes_from_decisions,
)
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.types import AgentDecision, AgentPersona, SignalType

PERSONAS: list[AgentPersona] = generate_personas(load_bracket_configs())


def _d(signal: SignalType, confidence: float) -> AgentDecision:
    return AgentDecision(signal=signal, confidence=confidence, sentiment=0.0, rationale="fictional")


# 3 Sell-Side BUY@0.8, 1 Shorts SELL@0.6, 1 Quants HOLD@0.5, 1 Degens PARSE_ERROR.
MIXED: list[tuple[str, AgentDecision]] = [
    ("sell_side_01", _d(SignalType.BUY, 0.8)),
    ("sell_side_02", _d(SignalType.BUY, 0.8)),
    ("sell_side_03", _d(SignalType.BUY, 0.8)),
    ("shorts_01", _d(SignalType.SELL, 0.6)),
    ("quants_01", _d(SignalType.HOLD, 0.5)),
    ("degens_01", _d(SignalType.PARSE_ERROR, 0.0)),
]


def test_votes_exclude_parse_errors_and_unknown_agents() -> None:
    votes = votes_from_decisions([*MIXED, ("whales_01", _d(SignalType.BUY, 0.9))], PERSONAS)
    assert [v.agent_id for v in votes] == [
        "sell_side_01",
        "sell_side_02",
        "sell_side_03",
        "shorts_01",
        "quants_01",
    ]
    assert votes[0] == Vote("sell_side_01", "sell_side", SignalType.BUY, 0.8, 0.75)


def test_net_score_under_each_weighting() -> None:
    # headcount: (3*0.8 - 0.6 + 0) / 5
    assert net_score(MIXED, PERSONAS, weighting="headcount") == pytest.approx(0.36)
    # reach: (0.75*0.8*3 - 0.6*0.6) / (0.75*3 + 0.6 + 0.55)
    assert net_score(MIXED, PERSONAS, weighting="reach") == pytest.approx(1.44 / 3.4)
    # bracket_equal: each bracket weighs 1 in total -> (0.8 - 0.6 + 0) / 3
    assert net_score(MIXED, PERSONAS, weighting="bracket_equal") == pytest.approx(0.2 / 3)


def test_unanimous_full_confidence_buy_is_plus_one() -> None:
    unanimous = [(p.id, _d(SignalType.BUY, 1.0)) for p in PERSONAS[:20]]
    for weighting in WEIGHTINGS:
        assert net_score(unanimous, PERSONAS, weighting=weighting) == pytest.approx(1.0)


def test_empty_votes_are_neutral() -> None:
    failed = [("degens_01", _d(SignalType.PARSE_ERROR, 0.0))]
    for weighting in WEIGHTINGS:
        assert net_score(failed, PERSONAS, weighting=weighting) == 0.0
    assert dispersion(failed) == Dispersion(entropy=0.0, stdev=0.0)
    assert bootstrap_ci(failed, PERSONAS, weighting="headcount", rng=random.Random(1)) == (0.0, 0.0)
    estimates = estimate_consensus([], rng=random.Random(1))
    assert {e.n for e in estimates.values()} == {0}
    assert all(e.ci_low is None and e.ci_high is None for e in estimates.values())


def test_dispersion_of_the_mixed_round() -> None:
    result = dispersion(MIXED)
    expected_entropy = -(0.6 * math.log(0.6) + 2 * 0.2 * math.log(0.2)) / math.log(3)
    assert result.entropy == pytest.approx(expected_entropy)
    assert result.stdev == pytest.approx(math.sqrt(0.3264))


def test_entropy_extremes() -> None:
    thirds = [
        ("quants_01", _d(SignalType.BUY, 0.5)),
        ("quants_02", _d(SignalType.SELL, 0.5)),
        ("quants_03", _d(SignalType.HOLD, 0.5)),
    ]
    assert dispersion(thirds).entropy == pytest.approx(1.0)
    unanimous = [("quants_01", _d(SignalType.SELL, 0.4)), ("quants_02", _d(SignalType.SELL, 0.9))]
    assert dispersion(unanimous).entropy == 0.0


def test_bootstrap_ci_brackets_the_point_estimate() -> None:
    low, high = bootstrap_ci(MIXED, PERSONAS, weighting="headcount", n_boot=500, rng=random.Random(7))
    assert low <= 0.36 <= high
    assert low < high


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    votes = votes_from_decisions(MIXED, PERSONAS)
    first = bootstrap_ci_votes(votes, weighting="reach", n_boot=200, rng=random.Random(42))
    second = bootstrap_ci_votes(votes, weighting="reach", n_boot=200, rng=random.Random(42))
    assert first == second


def test_bootstrap_of_identical_votes_is_degenerate() -> None:
    same = [(f"quants_{i:02d}", _d(SignalType.BUY, 0.8)) for i in range(1, 6)]
    low, high = bootstrap_ci(same, PERSONAS, weighting="headcount", n_boot=50, rng=random.Random(3))
    assert low == pytest.approx(0.8) and high == pytest.approx(0.8)


@pytest.mark.parametrize(("n_boot", "alpha"), [(0, 0.05), (100, 0.0), (100, 1.0)])
def test_bootstrap_rejects_bad_parameters(n_boot: int, alpha: float) -> None:
    votes = votes_from_decisions(MIXED, PERSONAS)
    with pytest.raises(ValueError):
        bootstrap_ci_votes(votes, weighting="headcount", n_boot=n_boot, alpha=alpha, rng=random.Random(1))


def test_estimate_consensus_ci_only_for_headcount_by_default() -> None:
    estimates = estimate_consensus(votes_from_decisions(MIXED, PERSONAS), rng=random.Random(5), n_boot=100)
    assert set(estimates) == set(WEIGHTINGS)
    assert estimates["headcount"].ci_low is not None and estimates["headcount"].n == 5
    assert estimates["reach"].ci_low is None and estimates["bracket_equal"].ci_high is None


def test_lean_from_score_deadband() -> None:
    assert NET_SCORE_DEADBAND == 0.15
    assert lean_from_score(0.15) == "hold"
    assert lean_from_score(0.1501) == "buy"
    assert lean_from_score(-0.2) == "sell"
    assert lean_from_score(0.0) == "hold"


def test_consensus_rng_is_stable_and_round_specific() -> None:
    assert consensus_rng("101", 2).random() == consensus_rng("101", 2).random()
    assert consensus_rng("101", 2).random() != consensus_rng("101", 3).random()
