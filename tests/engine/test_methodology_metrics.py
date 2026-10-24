"""run_simulation writes metrics_version 3 with the methodology keys (docs/DECISIONS.md#adr-consensus-estimators)."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from alphaswarm import simulation
from tests.engine.scenario import RunScenario

SIGNALS = ("buy", "sell", "hold")
ROUND_KEYS = (
    "net_score_headcount",
    "net_score_reach",
    "net_score_bracket_equal",
    "net_score_ci_low",
    "net_score_ci_high",
    "entropy",
    "polarization",
    "stdev",
)


def _metrics(fake_graph: MagicMock) -> dict[str, object]:
    return dict(fake_graph.write_cycle_metrics.await_args_list[-1].args[1])


async def test_cycle_metrics_carry_methodology_v3(run_scenario: RunScenario, fake_graph: MagicMock) -> None:
    await run_scenario()
    metrics = _metrics(fake_graph)
    assert metrics["metrics_version"] == 3
    for n in (1, 2, 3):
        for key in ROUND_KEYS:
            assert f"r{n}_{key}" in metrics, f"r{n}_{key}"
    assert not any(k.startswith("r1_trans_") for k in metrics)
    for n in (2, 3):
        cells = [metrics[f"r{n}_trans_{a}_{b}"] for a in SIGNALS for b in SIGNALS]
        assert 0 < sum(cells) <= 100  # type: ignore[operator]
        assert metrics[f"r{n}_net_score_ci_low"] <= metrics[f"r{n}_net_score_headcount"]  # type: ignore[operator]
    assert all(not isinstance(v, float) or math.isfinite(v) for v in metrics.values())


async def test_two_round_cycle_has_no_round_three_methodology(
    run_scenario: RunScenario,
    fake_graph: MagicMock,
) -> None:
    await run_scenario(num_rounds=2)
    metrics = _metrics(fake_graph)
    assert "r2_net_score_headcount" in metrics
    assert not any(k.startswith("r3_") and "net_score" in k for k in metrics)


async def test_a_methodology_failure_keeps_the_other_metrics(
    run_scenario: RunScenario, fake_graph: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> dict[str, float | int]:
        raise RuntimeError("estimator bug")

    monkeypatch.setattr(simulation, "methodology_metrics", boom)
    await run_scenario(num_rounds=2)
    metrics = _metrics(fake_graph)
    assert metrics["metrics_version"] == 3
    assert "r2_flips" in metrics
    assert not any("net_score" in k for k in metrics)
