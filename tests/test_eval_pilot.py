"""Fast-track pilot runner and scorer, preliminary (docs/DECISIONS.md#adr-eval-harness)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from alphaswarm.evaluation import EvalPaths, OutcomeLabel, normalize_rumor
from tests.support.eval_data import make_events
from tests.support.eval_scripts import load_eval_script

pilot = load_eval_script("pilot")
EVENTS = make_events(6)
SINCE = "2026-10-08T00:00:00Z"


def _rows(signal: str, count: int, rounds: tuple[int, ...] = (1, 2)) -> list[dict[str, Any]]:
    return [
        {
            "agent_id": f"agent_{i:03d}",
            "round": r,
            "signal": signal if i < count else "hold",
            "confidence": 0.8 if i < count else 0.5,
        }
        for r in rounds
        for i in range(100)
    ]


def test_pilot_takes_the_first_five_events_unless_named() -> None:
    assert [e.event_id for e in pilot.pilot_events(EVENTS, ())] == [f"evt-00{i}" for i in range(1, 6)]
    assert [e.event_id for e in pilot.pilot_events(EVENTS, ("evt-006",))] == ["evt-006"]


def test_run_pilot_tops_up_to_three_repeats_and_stops_on_usage_errors(tmp_path: Path) -> None:
    done = [{"cycle_id": "c1", "seed_rumor": EVENTS[0].rumor, "num_rounds": 2, "overall_sentiment": 0.1}] * 2
    codes = iter([0, 0, 0, 2])
    calls: list[tuple[Sequence[str], Mapping[str, str]]] = []

    def runner(argv: Sequence[str], env: Mapping[str, str]) -> int:
        calls.append((argv, env))
        return next(codes)

    inherited = {"ALPHASWARM_NUM_ROUNDS": "3", "ALPHASWARM_SIMULATION__OWN_PRIOR_MEMORY": "false"}
    code = pilot.run_pilot(
        EVENTS[:2],
        read=lambda query, params: done,
        runner=runner,
        paths=EvalPaths(tmp_path),
        since=SINCE,
        inherited=inherited,
        out=lambda line: None,
    )
    assert code == 2 and len(calls) == 4  # 1 top-up for evt-001, then evt-002 stops on its 3rd
    assert calls[0][1]["ALPHASWARM_NUM_ROUNDS"] == "2"
    assert calls[0][1]["ALPHASWARM_SIMULATION__CONTROL_FRACTION"] == "0.0"
    assert "ALPHASWARM_SIMULATION__OWN_PRIOR_MEMORY" not in calls[0][1]
    assert calls[0][0][-1] == str(EvalPaths(tmp_path).fixture("evt-001", "named"))


def test_pilot_scores_and_report() -> None:
    cycles = [
        {
            "cycle_id": "c1",
            "seed_rumor": EVENTS[0].rumor,
            "num_rounds": 2,
            "overall_sentiment": 0.4,
        },
        {
            "cycle_id": "c2",
            "seed_rumor": EVENTS[1].rumor,
            "num_rounds": 2,
            "overall_sentiment": -0.2,
        },
        {
            "cycle_id": "c3",
            "seed_rumor": "unrelated fictional text",
            "num_rounds": 2,
            "overall_sentiment": 0.0,
        },
    ]
    decisions = {"c1": _rows("buy", 70), "c2": _rows("sell", 70)}

    def read(query: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        if query == pilot.PILOT_CYCLES_QUERY:
            return cycles
        return [r for r in decisions[params["cycle_id"]] if r["round"] in params["rounds"]]

    rows, matched = pilot.pilot_scores(read, EVENTS, SINCE)
    assert matched == 2
    assert ("evt-001", "swarm", 0.56) in [(e, n, round(s, 2)) for e, n, s in rows]
    labels = {
        e.event_id: OutcomeLabel(
            event_id=e.event_id,
            abn_ret_1d=0.03 if i == 0 else -0.03,
            abn_ret_5d=0.0,
            vol_scale=0.01,
            label_1d="up" if i == 0 else "down",
            label_5d="flat",
        )
        for i, e in enumerate(EVENTS[:2])
    }
    text = pilot.pilot_report(rows, labels, matched)
    assert text.startswith("## P7.7 pilot (PRELIMINARY")
    assert "| swarm | 1d | 2 | 2 | 1.00 [" in text
    assert normalize_rumor(EVENTS[0].rumor) not in text
