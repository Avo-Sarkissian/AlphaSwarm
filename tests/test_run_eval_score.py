"""run_eval.py score: the accuracy table from stored cycles (docs/methodology.md §5-8)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from alphaswarm.consensus import NET_SCORE_DEADBAND, net_score
from alphaswarm.evaluation import (
    BaselineRecord,
    EvalEvent,
    OutcomeLabel,
    ProbeRecord,
    advise_g20,
    headcount_score,
    sim_seed_for,
)
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.types import AgentDecision, SignalType
from tests.support.eval_data import make_events
from tests.support.eval_scripts import load_eval_script

run_eval = load_eval_script("run_eval")
PERSONAS = generate_personas(load_bracket_configs())
EVENTS = make_events(3)
BLOCK = "== ZZZT ==\nPrice: $50.00"
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _props(
    event: EvalEvent,
    arm_name: str,
    seed: int,
    cycle_id: str,
    *,
    status: str = "complete",
    block: str = BLOCK,
    simulation: dict[str, Any] | None = None,
    rumor: str | None = None,
) -> dict[str, Any]:
    arm = run_eval.ARMS[arm_name]
    manifest = {
        "num_rounds": arm.num_rounds,
        "sim_seed": sim_seed_for(seed),
        "experiment_tag": arm.tag,
        "market_context": block,
        "simulation": simulation if simulation is not None else run_eval.expected_simulation(arm, seed),
    }
    return {
        "cycle_id": cycle_id,
        "experiment_tag": arm.tag,
        "sim_seed": sim_seed_for(seed),
        "seed_rumor": rumor if rumor is not None else event.rumor_for(arm.variant),
        "status": status,
        "num_rounds": arm.num_rounds,
        "final_round": arm.num_rounds,
        "overall_sentiment": 0.4,
        "run_manifest_json": json.dumps(manifest),
    }


def _decisions(signal: str, count: int, confidence: float, rounds: tuple[int, ...] = (1, 2)) -> list[dict[str, Any]]:
    """The first *count* personas vote *signal*, the rest hold; same in every round."""
    return [
        {
            "agent_id": p.id,
            "round": r,
            "signal": signal if i < count else "hold",
            "confidence": confidence if i < count else 0.5,
        }
        for r in rounds
        for i, p in enumerate(PERSONAS)
    ]


class FakeGraph:
    def __init__(self, cycles: list[dict[str, Any]], decisions: Mapping[str, list[dict[str, Any]]]) -> None:
        self.cycles = cycles
        self.decisions = decisions

    def read(self, query: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        if query == run_eval.CYCLES_QUERY:
            return [{"props": p} for p in self.cycles if p["experiment_tag"] in params["tags"]]
        assert query == run_eval.DECISIONS_QUERY
        return [r for r in self.decisions.get(params["cycle_id"], []) if r["round"] in params["rounds"]]


def _label(event_id: str, label: str, abn: float) -> OutcomeLabel:
    return OutcomeLabel.model_validate(
        {
            "event_id": event_id,
            "abn_ret_1d": abn,
            "abn_ret_5d": abn,
            "vol_scale": 0.01,
            "label_1d": label,
            "label_5d": label,
        }
    )


def _baseline(event_id: str, seed: int, score: float, n_valid: int) -> BaselineRecord:
    return BaselineRecord(
        event_id=event_id,
        variant="named",
        kind="single_k5",
        seed=seed,
        k=5,
        n_valid=n_valid,
        score=score,
        model="fake-worker",
        created_at=NOW,
    )


def _scenario() -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, OutcomeLabel],
    list[BaselineRecord],
    list[ProbeRecord],
]:
    e1, e2, e3 = EVENTS
    cycles = [
        _props(e1, "swarm", 1, "c-old"),
        _props(e1, "swarm", 1, "c-11"),
        _props(e1, "swarm", 2, "c-12"),
        _props(e1, "swarm", 3, "c-13", block="== ZZZT ==\nPrice: $99.00"),
        _props(e2, "swarm", 1, "c-21"),
        _props(e2, "swarm", 2, "c-22", status="running"),
        _props(e2, "swarm", 3, "c-23", simulation={"personal_boost": 0.9}),
        _props(e3, "swarm", 1, "c-31"),
        _props(e1, "swarm", 2, "c-orphan", rumor="An unrelated fictional rumor about nothing."),
        _props(e1, "anon", 1, "c-a1"),
    ]
    decisions = {
        "c-old": _decisions("buy", 70, 0.8),
        "c-11": _decisions("buy", 70, 0.8),
        "c-12": _decisions("buy", 70, 0.8),
        "c-13": _decisions("buy", 70, 0.8),
        "c-21": _decisions("sell", 70, 0.8),
        "c-31": _decisions("buy", 60, 0.8),
        "c-a1": _decisions("buy", 50, 0.6),
    }
    labels = {"evt-001": _label("evt-001", "up", 0.03), "evt-002": _label("evt-002", "down", -0.02)}
    baselines = [_baseline("evt-001", 1, 0.2, 5), _baseline("evt-001", 2, 0.9, 2), _baseline("evt-002", 1, -0.4, 5)]
    probes = [
        ProbeRecord(
            event_id="evt-001", recalled=True, direction="up", parse_failed=False, model="fake-worker", created_at=NOW
        ),
        ProbeRecord(
            event_id="evt-002",
            recalled=False,
            direction="unknown",
            parse_failed=False,
            model="fake-worker",
            created_at=NOW,
        ),
    ]
    return cycles, decisions, labels, baselines, probes


def test_score_tolerates_missing_labels_partial_seeds_and_drift() -> None:
    cycles, decisions, labels, baselines, probes = _scenario()
    inputs = run_eval.collect_eval_inputs(
        FakeGraph(cycles, decisions).read,
        EVENTS,
        labels,
        baselines,
        probes,
        PERSONAS,
        labels_sha256="0" * 64,
    )
    report = inputs.report
    assert (report.matched, report.incomplete, report.orphans, report.duplicates) == (5, 1, 1, 1)
    assert dict(report.excluded) == {
        "settings drift": 1,
        "context drift": 1,
        "single_k5: too few valid samples": 1,
    }
    swarm = run_eval.forecaster_scores(inputs.rows, "swarm")
    assert swarm == {"evt-001": pytest.approx(0.56), "evt-002": pytest.approx(-0.56), "evt-003": pytest.approx(0.48)}
    assert run_eval.forecaster_scores(inputs.rows, "r1_only") == swarm
    assert run_eval.forecaster_scores(inputs.rows, "swarm", variant="anon", seed=1) == {"evt-001": pytest.approx(0.3)}
    assert run_eval.forecaster_scores(inputs.rows, "single_k5") == {
        "evt-001": pytest.approx(0.2),
        "evt-002": pytest.approx(-0.4),
    }
    text = run_eval.build_eval_report(inputs, deadband=NET_SCORE_DEADBAND)
    assert "- cycles used: 5" in text
    assert "Events without a label (excluded): evt-003" in text
    assert "| swarm | 2 | 2 | 1.00 [" in text
    assert "swarm - orchestrator" in text
    assert "Suspect events (recalled with the correct direction): evt-001" in text
    assert "G-20 advice: B" in text
    assert "| nan" not in text.lower()


def test_manifest_problems_are_named() -> None:
    arm = run_eval.ARMS["swarm"]
    good = _props(EVENTS[0], "swarm", 1, "c-1")
    assert run_eval.manifest_problem(good, arm, 1)[0] is None
    assert run_eval.manifest_problem({**good, "run_manifest_json": None}, arm, 1)[0] == "no manifest"
    assert run_eval.manifest_problem({**good, "run_manifest_json": "{"}, arm, 1)[0] == "unreadable manifest"
    assert run_eval.manifest_problem(good, arm, 2)[0] == "seed or tag drift"
    assert run_eval.manifest_problem(good, run_eval.ARMS["rounds3"], 1)[0] == "num_rounds drift"
    partial = _props(EVENTS[0], "swarm", 1, "c-1", simulation={"sim_seed": sim_seed_for(1)})
    assert run_eval.manifest_problem(partial, arm, 1)[0] is None


def test_registered_defaults_decide_settings_drift() -> None:
    """A default changed after the runs (a later default change) must not exclude the stored cycles."""
    arm = run_eval.ARMS["swarm"]
    stored = {**run_eval.expected_simulation(arm, 1), "personal_boost": 0.3}
    props = _props(EVENTS[0], "swarm", 1, "c-1", simulation=stored)
    registered = {**stored, "sim_seed": None, "experiment_tag": None}
    assert run_eval.manifest_problem(props, arm, 1, base=registered)[0] is None
    later = {**registered, "personal_boost": 0.05}
    assert run_eval.manifest_problem(props, arm, 1, base=later)[0] == "settings drift"
    assert stored["control_fraction"] == 0.0  # the run-wide pin is part of every arm


def test_headcount_score_matches_the_consensus_estimator() -> None:
    signals = [SignalType.BUY, SignalType.SELL, SignalType.HOLD, SignalType.PARSE_ERROR]
    pairs = [(p.id, AgentDecision(signal=signals[i % 4], confidence=(i % 10) / 10)) for i, p in enumerate(PERSONAS)]
    assert headcount_score([d for _, d in pairs])[0] == pytest.approx(net_score(pairs, PERSONAS, weighting="headcount"))


def test_report_without_any_data_is_all_n_a() -> None:
    inputs = run_eval.EvalInputs(EVENTS, {}, [], [], run_eval.MatchReport(), None)
    text = run_eval.build_eval_report(inputs, deadband=NET_SCORE_DEADBAND)
    assert "| swarm | 0 | 0 | n/a |" in text
    assert "G-20 advice: B (insufficient data" in text


def test_g20_advice_follows_the_registered_rule() -> None:
    lean_hold = {"evt-001": 0.1, "evt-002": -0.05, "evt-003": 0.4}
    assert advise_g20(lean_hold, 0.6, deadband=0.15).branch == "A"
    assert advise_g20(lean_hold, 0.5, deadband=0.15).branch == "B"
    assert advise_g20({"evt-001": 0.5}, 0.9, deadband=0.15).branch == "B"
    assert advise_g20({}, None, deadband=0.15).branch == "B"


def test_outputs_are_written(tmp_path: Path) -> None:
    cycles, decisions, labels, baselines, probes = _scenario()
    inputs = run_eval.collect_eval_inputs(
        FakeGraph(cycles, decisions).read,
        EVENTS,
        labels,
        baselines,
        probes,
        PERSONAS,
    )
    written = run_eval.write_outputs("# table\n", inputs, tmp_path, parquet=False)
    names = {p.name for p in written}
    assert {"eval_table.md", "forecasts.jsonl", "reliability_1d_swarm.svg"} <= names
    assert "forecasts.parquet" not in names
    lines = (tmp_path / "forecasts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(inputs.rows)
    assert {"event_id", "forecaster", "p_up", "label_1d", "post_cutoff"} <= set(json.loads(lines[0]))
    svg = (tmp_path / "reliability_1d_swarm.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "swarm: 1-day reliability (n=2)" in svg


def test_parquet_round_trip(tmp_path: Path) -> None:
    pq = pytest.importorskip("pyarrow.parquet")
    records = [{"event_id": "evt-001", "score": 0.5, "label_1d": None}]
    run_eval.write_parquet(records, tmp_path / "f.parquet")
    assert pq.read_table(tmp_path / "f.parquet").to_pylist() == records
