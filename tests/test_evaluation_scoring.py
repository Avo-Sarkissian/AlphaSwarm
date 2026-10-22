"""Scoring statistics on hand-built cases (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

import math

import pytest

from alphaswarm.evaluation import (
    Interval,
    OutcomeLabel,
    average_ranks,
    boot_rng,
    brier,
    brier_by_event,
    cluster_bootstrap,
    fmt,
    fmt_interval,
    fmt_rate,
    lean3,
    log_loss,
    markdown_table,
    mean_by_event,
    p_up,
    paired_difference,
    reliability_bins,
    score_forecaster,
    spearman_rho,
    verdict,
    wilson_interval,
)


def _label(event_id: str, label_1d: str, abn: float) -> OutcomeLabel:
    return OutcomeLabel.model_validate(
        {
            "event_id": event_id,
            "abn_ret_1d": abn,
            "abn_ret_5d": abn,
            "vol_scale": 0.01,
            "label_1d": label_1d,
            "label_5d": label_1d,
        }
    )


LABELS = {
    "evt-001": _label("evt-001", "up", 0.03),
    "evt-002": _label("evt-002", "down", -0.02),
    "evt-003": _label("evt-003", "flat", 0.001),
    "evt-004": _label("evt-004", "up", 0.05),
}


def test_probability_and_losses() -> None:
    assert p_up(0.6) == pytest.approx(0.8)
    assert p_up(-2.0) == 0.0
    assert brier(0.8, up=True) == pytest.approx(0.04)
    assert brier(0.8, up=False) == pytest.approx(0.64)
    assert log_loss(1.0, up=True) == pytest.approx(-math.log(0.99))
    assert log_loss(1.0, up=False) == pytest.approx(-math.log(0.01))


def test_wilson_interval_matches_the_textbook_value() -> None:
    interval = wilson_interval(8, 10)
    assert interval is not None
    assert interval[0] == pytest.approx(0.4902, abs=1e-3)
    assert interval[1] == pytest.approx(0.9433, abs=1e-3)


def test_spearman_with_ties() -> None:
    assert average_ranks([3.0, 1.0, 3.0, 2.0]) == [3.5, 1.0, 3.5, 2.0]
    assert spearman_rho([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)
    assert spearman_rho([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_degenerate_inputs_return_none() -> None:
    assert wilson_interval(0, 0) is None
    assert spearman_rho([1.0, 2.0], [1.0, 2.0]) is None
    assert spearman_rho([0.5, 0.5, 0.5], [0.1, 0.2, 0.3]) is None
    assert cluster_bootstrap({}, rng=boot_rng("t")) is None
    assert cluster_bootstrap({"evt-001": []}, rng=boot_rng("t")) is None
    single = cluster_bootstrap({"evt-001": [0.2, 0.4]}, rng=boot_rng("t"))
    assert single == Interval(mean=pytest.approx(0.3), lo=None, hi=None, n_clusters=1, n_units=2)
    flat_only = {"evt-003": LABELS["evt-003"]}
    result = score_forecaster("swarm", {"evt-003": 0.4}, flat_only, "1d", deadband=0.15)
    assert (result.n_events, result.n_directional) == (1, 0)
    assert result.hit_rate is None and result.hit_ci is None
    assert result.brier is None and result.log_loss is None and result.spearman is None
    assert result.accuracy3 == 0.0
    zero = score_forecaster("swarm", {"evt-001": 0.0}, LABELS, "1d", deadband=0.15)
    assert zero.hits == 0  # S = 0 is a miss, never a coin flip
    assert "nan" not in markdown_table(["a"], [[fmt(None)], [fmt_interval(None)]]).lower()


def test_score_forecaster_end_to_end() -> None:
    scores = {"evt-001": 0.5, "evt-002": 0.2, "evt-003": 0.05, "evt-004": 0.3, "evt-999": 0.9}
    result = score_forecaster("swarm", scores, LABELS, "1d", deadband=0.15)
    assert (result.n_events, result.n_directional, result.hits) == (4, 3, 2)
    assert result.hit_rate == pytest.approx(2 / 3)
    expected_brier = (brier(0.75, True) + brier(0.6, False) + brier(0.65, True)) / 3
    assert result.brier == pytest.approx(expected_brier)
    assert result.spearman is not None
    # lean: up, up, flat, up vs labels up, down, flat, up -> 3 of 4
    assert result.accuracy3 == pytest.approx(0.75)


def test_mean_by_event_and_lean() -> None:
    assert mean_by_event([("evt-001", 0.2), ("evt-001", 0.4), ("evt-002", -0.1)]) == {
        "evt-001": pytest.approx(0.3),
        "evt-002": -0.1,
    }
    assert [lean3(s, 0.15) for s in (0.2, -0.2, 0.15, -0.1)] == ["up", "down", "flat", "flat"]


def test_reliability_bins_cover_the_unit_interval() -> None:
    bins = reliability_bins([(0.1, False), (0.15, True), (0.9, True), (1.0, True)])
    assert [b.n for b in bins] == [2, 0, 0, 0, 2]
    assert bins[0].mean_p == pytest.approx(0.125) and bins[0].freq == pytest.approx(0.5)
    assert bins[1].mean_p is None and bins[1].freq is None


def test_cluster_bootstrap_is_deterministic_and_brackets_the_mean() -> None:
    clusters = {f"evt-{i:03d}": [0.1 * i, 0.1 * i + 0.05] for i in range(1, 9)}
    first = cluster_bootstrap(clusters, rng=boot_rng("cell"))
    second = cluster_bootstrap(clusters, rng=boot_rng("cell"))
    assert first == second
    assert first is not None and first.lo is not None and first.hi is not None
    assert first.lo < first.mean < first.hi
    assert (first.n_clusters, first.n_units) == (8, 16)


def test_paired_difference_and_verdict() -> None:
    a = brier_by_event({"evt-001": 0.9, "evt-002": -0.9, "evt-004": 0.9}, LABELS, "1d")
    b = brier_by_event({"evt-001": -0.9, "evt-002": 0.9, "evt-004": -0.9}, LABELS, "1d")
    assert set(a) == {"evt-001", "evt-002", "evt-004"}
    diff = paired_difference(a, b, rng=boot_rng("pair"))
    assert diff is not None and diff.hi is not None and diff.hi < 0
    assert verdict(diff) == "swarm better"
    assert verdict(None) == "insufficient data"
    assert verdict(Interval(0.0, -0.1, 0.1, 5, 5)) == "inconclusive"


def test_formatting() -> None:
    assert fmt(0.12345) == "0.123"
    assert fmt_interval(Interval(0.1, -0.05, 0.25, 4, 4)) == "+0.100 [-0.050, +0.250]"
    assert fmt_interval(Interval(0.1, None, None, 1, 1)) == "+0.100 [n/a]"
    assert fmt_rate(None, None) == "n/a"
    assert fmt_rate(0.5, (0.2, 0.8)) == "0.50 [0.20, 0.80]"
    assert markdown_table(["a", "b"], [["1", "2"]]) == "| a | b |\n|---|---|\n| 1 | 2 |\n"
