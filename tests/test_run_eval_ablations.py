"""run_eval.py ablations and the rounds and boost rules (docs/methodology.md §9)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from alphaswarm.consensus import NET_SCORE_DEADBAND
from alphaswarm.evaluation import (
    EvalEvent,
    Interval,
    OutcomeLabel,
    ablation_subset,
    advise_g15,
    advise_g16,
    sim_seed_for,
)
from alphaswarm.personas import generate_personas, load_bracket_configs
from tests.support.eval_data import make_events
from tests.support.eval_scripts import load_eval_script

run_eval = load_eval_script("run_eval")
PERSONAS = generate_personas(load_bracket_configs())
EVENTS = make_events(16)
SUBSET = ablation_subset([e.event_id for e in EVENTS])


def _label(event_id: str, label: str) -> OutcomeLabel:
    return OutcomeLabel.model_validate(
        {
            "event_id": event_id,
            "abn_ret_1d": 0.02,
            "abn_ret_5d": 0.02,
            "vol_scale": 0.01,
            "label_1d": label,
            "label_5d": label,
        }
    )


def _props(event: EvalEvent, arm_name: str, seed: int, *, peers: int, status: str = "complete") -> dict[str, Any]:
    arm = run_eval.ARMS[arm_name]
    final = arm.num_rounds
    manifest = {
        "num_rounds": final,
        "sim_seed": sim_seed_for(seed),
        "experiment_tag": arm.tag,
        "market_context": "== X ==\nPrice: $1.00",
        "simulation": run_eval.expected_simulation(arm, seed),
    }
    props: dict[str, Any] = {
        "cycle_id": f"{arm_name}-{event.event_id}-{seed}",
        "experiment_tag": arm.tag,
        "sim_seed": sim_seed_for(seed),
        "seed_rumor": event.rumor,
        "status": status,
        "num_rounds": final,
        "final_round": final,
        "overall_sentiment": 0.1,
        "run_manifest_json": json.dumps(manifest),
        "agent_count": 100,
        "total_seconds": 300.0 * final,
        f"r{final}_entropy": 0.6,
        f"r{final}_citation_gini": 0.3,
        f"r{final}_distinct_peers_shown": peers,
    }
    for n in range(2, final + 1):
        props[f"r{n}_flips"] = 10
    return props


def _decisions(cycle_id: str, rounds: int) -> list[dict[str, Any]]:
    return [
        {"agent_id": p.id, "round": r, "signal": "buy" if i < 70 else "hold", "confidence": 0.8 if i < 70 else 0.5}
        for r in range(1, rounds + 1)
        for i, p in enumerate(PERSONAS)
    ]


class FakeGraph:
    def __init__(self, cycles: list[dict[str, Any]]) -> None:
        self.cycles = cycles
        self.decisions = {c["cycle_id"]: _decisions(c["cycle_id"], c["num_rounds"]) for c in cycles}

    def read(self, query: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        if query == run_eval.CYCLES_QUERY:
            return [{"props": p} for p in self.cycles if p["experiment_tag"] in params["tags"]]
        assert query == run_eval.DECISIONS_QUERY
        return [r for r in self.decisions[params["cycle_id"]] if r["round"] in params["rounds"]]


def test_pair_metrics_reads_the_final_round_keys() -> None:
    arm = run_eval.ARMS["rounds3"]
    props = {
        "final_round": 3,
        "r3_entropy": 0.7,
        "r3_citation_gini": 0.4,
        "r3_distinct_peers_shown": 55,
        "r2_flips": 10,
        "r3_flips": 6,
        "agent_count": 100,
        "total_seconds": 900.0,
    }
    labels = {"evt-001": _label("evt-001", "up")}
    metrics = run_eval.pair_metrics(run_eval.CycleRun(arm, "evt-001", 1, "c-1", props, {}), 0.5, labels)
    assert metrics == {
        "net_score": 0.5,
        "brier_1d": pytest.approx(0.0625),
        "entropy": 0.7,
        "citation_gini": 0.4,
        "distinct_peers": 55.0,
        "seconds": 900.0,
        "flip_rate": pytest.approx(0.08),
    }
    legacy = run_eval.CycleRun(arm, "evt-002", 1, "c-2", {"final_round": 3}, {})
    assert run_eval.pair_metrics(legacy, None, labels) == {}


def test_compare_arm_pairs_by_event_and_seed() -> None:
    arm = {
        ("evt-001", 1): {"net_score": 0.5, "seconds": 900.0},
        ("evt-001", 2): {"net_score": 0.1},
        ("evt-002", 1): {"net_score": -0.3},
    }
    ref = {
        ("evt-001", 1): {"net_score": 0.4, "seconds": 600.0},
        ("evt-001", 2): {"net_score": 0.3},
        ("evt-003", 1): {"net_score": 0.9},
    }
    result = run_eval.compare_arm(arm, ref, arm="x", reference="y", deadband=0.15)
    assert result.pairs == 2
    net = result.deltas["net_score"]
    assert net is not None and net.mean == pytest.approx(-0.05) and net.n_clusters == 1
    seconds = result.deltas["seconds"]
    assert seconds is not None and seconds.mean == pytest.approx(300.0)
    assert result.deltas["entropy"] is None
    assert result.lean_agreement == pytest.approx(0.5)  # up/up agree, flat/up differ


def test_g16_and_g15_rules() -> None:
    tight = Interval(0.02, 0.0, 0.05, 5, 15)
    assert advise_g16(tight, 0.9, None).branch == "B"
    assert advise_g16(Interval(0.1, 0.05, 0.2, 5, 15), 0.9, None).branch == "A"
    assert advise_g16(tight, 0.7, None).branch == "A"
    assert advise_g16(tight, 0.9, Interval(-0.08, -0.12, -0.02, 5, 9)).branch == "A"
    assert advise_g16(None, None, None).branch == "A"
    gain = Interval(12.0, 4.0, 20.0, 5, 15)
    small_gain = Interval(3.0, 1.0, 5.0, 5, 15)
    costly = Interval(0.08, 0.01, 0.12, 5, 9)
    assert advise_g15({0.0: (gain, None), 0.05: (small_gain, None)}).value == 0.0
    assert advise_g15({0.0: (gain, costly), 0.05: (small_gain, None)}).value == 0.05
    assert advise_g15({0.0: (Interval(5.0, -1.0, 9.0, 5, 15), None)}).branch == "A"
    assert advise_g15({}).branch == "A"


def test_ablation_pairs_only_complete_matches() -> None:
    cycles: list[dict[str, Any]] = []
    for event in EVENTS:
        if event.event_id not in SUBSET:
            continue
        for seed in (1, 2, 3):
            cycles.append(_props(event, "swarm", seed, peers=40))
            running = event.event_id == SUBSET[0] and seed == 1
            cycles.append(_props(event, "rounds3", seed, peers=40, status="running" if running else "complete"))
            cycles.append(_props(event, "boost_0", seed, peers=60))
    text = run_eval.collect_ablations(FakeGraph(cycles).read, EVENTS, {}, PERSONAS, deadband=NET_SCORE_DEADBAND)
    assert "- not complete: 1" in text
    assert "| rounds3 | swarm | 14 |" in text
    assert "| boost_0 | rounds3 | 14 |" in text
    assert "| R3 vs R2 (rounds3 cycles) | same cycle, Round 2 | 14 |" in text
    assert "G-16 advice: B" in text
    assert "G-15 advice: B (boost 0.0" in text
    assert "Arms without runs: peer_random, peer_none, boost_005, own_prior_off, uniform_temp" in text
