"""alphaswarm.metrics: citation validity, influence, flips, intervals (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alphaswarm.metrics import (
    bootstrap_diff_ci,
    bootstrap_mean_ci,
    bracket_citation_rates,
    citation_validity_rate,
    exposure_normalized_influence,
    filter_citations,
    filter_round_citations,
    retest_metrics,
    round_experiment_metrics,
    split_flips,
)
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.types import AgentDecision, SignalType

PERSONAS = generate_personas(DEFAULT_BRACKETS)
BUY, SELL, HOLD, ERR = SignalType.BUY, SignalType.SELL, SignalType.HOLD, SignalType.PARSE_ERROR


def _d(signal: SignalType, cited: list[str] | None = None) -> AgentDecision:
    return AgentDecision(signal=signal, confidence=0.5, cited_agents=cited or [])


class TestFilterCitations:
    def test_keeps_shown_peers_in_first_mention_order(self) -> None:
        assert filter_citations(["degens_02", "quants_01"], ("quants_01", "degens_02"), "macro_01") == (
            ["degens_02", "quants_01"],
            0,
        )

    def test_drops_unseen_self_and_duplicates(self) -> None:
        kept, invalid = filter_citations(
            ["quants_01", "macro_01", "ghost_99", "quants_01", "shorts_04"],
            ("quants_01", "degens_02"),
            "macro_01",
        )

        assert (kept, invalid) == (["quants_01"], 4)

    def test_case_and_whitespace_variants_map_to_the_shown_id(self) -> None:
        """' Sell_Side_03 ' names the peer that was shown."""
        kept, invalid = filter_citations([" Sell_Side_03 ", "SELL_SIDE_03"], ("sell_side_03",), "macro_01")

        assert (kept, invalid) == (["sell_side_03"], 1)

    def test_nothing_shown_makes_every_citation_invalid(self) -> None:
        assert filter_citations(["quants_01", "degens_02"], (), "macro_01") == ([], 2)

    @given(
        cited=st.lists(st.sampled_from(["a_01", "b_02", "c_03", "d_04", "self_05", " A_01"]), max_size=8),
        shown=st.lists(st.sampled_from(["a_01", "b_02", "c_03"]), unique=True),
    )
    def test_properties(self, cited: list[str], shown: list[str]) -> None:
        kept, invalid = filter_citations(cited, shown, "self_05")

        assert set(kept) <= set(shown)
        assert len(kept) == len(set(kept))
        assert "self_05" not in kept
        assert len(kept) + invalid == len(cited)


def test_filter_round_citations_replaces_only_the_citations() -> None:
    first = AgentDecision(
        signal=BUY, confidence=0.7, sentiment=0.3, rationale="r", cited_agents=["degens_02", "ghost_99"]
    )
    decisions = [("quants_01", first), ("degens_02", _d(SELL))]

    filtered, invalid = filter_round_citations(decisions, {"quants_01": ("degens_02",), "degens_02": ()})

    assert filtered[0][1].cited_agents == ["degens_02"]
    assert filtered[0][1].model_dump(exclude={"cited_agents"}) == first.model_dump(exclude={"cited_agents"})
    assert filtered[1] == decisions[1]
    assert invalid == {"quants_01": 1, "degens_02": 0}


@pytest.mark.parametrize(("valid", "invalid", "expected"), [(3, 1, 0.75), (0, 2, 0.0), (0, 0, None)])
def test_citation_validity_rate(valid: int, invalid: int, expected: float | None) -> None:
    assert citation_validity_rate(valid, invalid) == expected


def test_exposure_normalized_influence_is_a_beta_posterior_mean() -> None:
    exposures = {"r1": ("a_01", "b_02"), "r2": ("a_01",), "r3": ()}
    decisions = [("r1", _d(BUY, ["a_01"])), ("r2", _d(BUY, ["a_01"])), ("r3", _d(BUY))]

    assert exposure_normalized_influence(exposures, decisions) == pytest.approx({"a_01": 3 / 4, "b_02": 1 / 3})


def test_unseen_agents_are_left_out_and_priors_must_be_positive() -> None:
    assert exposure_normalized_influence({"r1": ()}, [("r1", _d(BUY))]) == {}
    with pytest.raises(ValueError, match="prior"):
        exposure_normalized_influence({}, [], prior_a=0.0)


def test_bracket_citation_rates_pool_by_bracket() -> None:
    exposures = {
        "quants_01": ("sell_side_01", "sell_side_02", "degens_01"),
        "quants_02": ("sell_side_01",),
    }
    decisions = [("quants_01", _d(BUY, ["sell_side_01"])), ("quants_02", _d(BUY))]

    assert bracket_citation_rates(exposures, decisions, PERSONAS) == pytest.approx(
        {"degens": 1 / 3, "sell_side": 2 / 5}
    )


def test_split_flips_by_group() -> None:
    prev = [("a", _d(BUY)), ("b", _d(BUY)), ("c", _d(HOLD)), ("d", _d(SELL))]
    curr = [("a", _d(SELL)), ("b", _d(BUY)), ("c", _d(SELL)), ("d", _d(SELL))]

    assert split_flips(prev, curr, {"a"}) == (1, 1)


def test_parse_error_on_either_side_is_not_a_flip() -> None:
    """A failed decision on either side of a round is no observation."""
    prev = [("a", _d(ERR)), ("b", _d(BUY)), ("c", _d(BUY))]
    curr = [("a", _d(BUY)), ("b", _d(ERR)), ("c", _d(SELL)), ("new", _d(SELL))]

    assert split_flips(prev, curr, {"a", "b"}) == (0, 1)


def test_retest_metrics_count_valid_pairs_only() -> None:
    first = [("a", _d(BUY)), ("b", _d(SELL)), ("c", _d(ERR)), ("d", _d(HOLD))]
    second = [("a", _d(BUY)), ("b", _d(BUY)), ("c", _d(BUY)), ("d", _d(ERR))]

    assert retest_metrics(first, second) == {
        "r1_retest_pairs": 2,
        "r1_retest_flips": 1,
        "r1_retest_flip_rate": 0.5,
    }


def test_retest_without_pairs_has_no_rate() -> None:
    assert retest_metrics([("a", _d(ERR))], [("a", _d(BUY))]) == {
        "r1_retest_pairs": 0,
        "r1_retest_flips": 0,
    }


def test_round_one_keys() -> None:
    out = round_experiment_metrics(
        1,
        decisions=[("quants_01", _d(BUY)), ("degens_01", _d(SELL))],
        prev_decisions=None,
        exposures={"quants_01": (), "degens_01": ()},
        control_ids=frozenset({"degens_01"}),
        citations_invalid={"quants_01": 2, "degens_01": 0},
        personas=PERSONAS,
    )

    assert out == {"r1_citations_invalid": 2, "r1_control_agents": 1, "r1_citation_validity_rate": 0.0}


def test_round_two_keys_split_flips_rates_and_shock_arm() -> None:
    prev = [("quants_01", _d(BUY)), ("degens_01", _d(BUY)), ("macro_01", _d(HOLD))]
    curr = [("quants_01", _d(SELL, ["degens_01"])), ("degens_01", _d(SELL)), ("macro_01", _d(HOLD))]

    out = round_experiment_metrics(
        2,
        decisions=curr,
        prev_decisions=prev,
        exposures={"quants_01": ("degens_01", "macro_01"), "degens_01": (), "macro_01": ("quants_01",)},
        control_ids=frozenset({"degens_01"}),
        citations_invalid={"quants_01": 1, "degens_01": 0, "macro_01": 0},
        personas=PERSONAS,
        shock_treated_ids=frozenset({"quants_01"}),
    )

    assert out["r2_citations_invalid"] == 1
    assert out["r2_citation_validity_rate"] == 0.5
    assert out["r2_control_agents"] == 1
    assert (out["r2_flips_control"], out["r2_flips_treated"]) == (1, 1)
    assert out["r2_cite_rate_degens"] == pytest.approx(2 / 3, abs=1e-6)
    assert out["r2_cite_rate_macro"] == pytest.approx(1 / 3, abs=1e-6)
    assert out["r2_cite_rate_quants"] == pytest.approx(1 / 3, abs=1e-6)
    assert (
        out["r2_shock_treated_agents"],
        out["r2_pivots_shock_treated"],
        out["r2_pivots_shock_untreated"],
    ) == (1, 1, 1)


def test_bootstrap_mean_ci_is_seeded_and_brackets_the_mean() -> None:
    values = [0.0, 1.0] * 20

    first = bootstrap_mean_ci(values, rng=random.Random(1), n_boot=500)

    assert first == bootstrap_mean_ci(values, rng=random.Random(1), n_boot=500)
    assert first is not None and first[0] <= 0.5 <= first[1]


def test_bootstrap_needs_two_values_per_group() -> None:
    assert bootstrap_mean_ci([1.0], rng=random.Random(1)) is None
    assert bootstrap_diff_ci([1.0, 0.0], [1.0], rng=random.Random(1)) is None


def test_bootstrap_diff_ci_of_identical_groups_contains_zero() -> None:
    group = [0.0, 1.0, 1.0, 0.0] * 10

    ci = bootstrap_diff_ci(group, list(group), rng=random.Random(3), n_boot=500)

    assert ci is not None and ci[0] <= 0.0 <= ci[1]


@pytest.mark.parametrize(("n_boot", "alpha"), [(0, 0.05), (100, 0.0), (100, 1.0)])
def test_bootstrap_rejects_bad_arguments(n_boot: int, alpha: float) -> None:
    with pytest.raises(ValueError):
        bootstrap_mean_ci([0.0, 1.0], rng=random.Random(1), n_boot=n_boot, alpha=alpha)
