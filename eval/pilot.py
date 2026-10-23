#!/usr/bin/env python3
"""Fast-track accuracy pilot: about 5 events, 3 repeats, two free baselines. PRELIMINARY.

Pre-Phase-5 layout: no sim_seed, experiment tag or run manifest yet, so pilot cycles
are found by rumor text and a start time. eval/run_eval.py replaces this script once
seeded runs exist; its events are never reused by the registered evaluation
(docs/DECISIONS.md#adr-eval-harness).

    uv run python eval/pilot.py run [--events evt-001,evt-002]
    uv run python eval/pilot.py score

The pilot is valid only if, in the shell that runs it (repo root):
  - the web server is stopped: this layout has no instance lock, so a UI run would
    share Ollama and Neo4j with the pilot's cycles;
  - .env sets no ALPHASWARM_SIMULATION__* key: the child still reads .env, and only
    ALPHASWARM_NUM_ROUNDS and ALPHASWARM_SIMULATION__CONTROL_FRACTION are pinned over it;
  - no pilot rumor is run by any other route while the pilot is open: every complete
    cycle with the same rumor text created since eval/results/pilot_started_at.txt
    counts as a pilot repeat, even one run with live market context.
The first `run` or `score` writes eval/results/pilot_started_at.txt, which fixes the
start of that window; delete it to start a fresh pilot.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from alphaswarm.evaluation import (
    EvalEvent,
    EvalPaths,
    Horizon,
    OutcomeLabel,
    fmt,
    fmt_rate,
    headcount_score,
    markdown_table,
    mean_by_event,
    normalize_rumor,
    read_jsonl,
    read_jsonl_if_exists,
    score_forecaster,
)
from alphaswarm.types import AgentDecision, SignalType

EVAL_DIR: Final = Path(__file__).resolve().parent
REPO_ROOT: Final = EVAL_DIR.parent
PATHS: Final = EvalPaths(EVAL_DIR)
PILOT_EVENTS: Final = 5
REPEATS: Final = 3
PILOT_ROUNDS: Final = 2
DEADBAND: Final = 0.15  # the consensus net-score deadband; no shared constant exists yet
MIN_VALID_VOTES: Final = 50
HORIZONS: Final[tuple[Horizon, ...]] = ("1d", "5d")
STARTED_AT: Final = PATHS.results / "pilot_started_at.txt"

PILOT_CYCLES_QUERY: Final = """
MATCH (c:Cycle)
WHERE c.created_at >= datetime($since) AND c.metrics_recorded_at IS NOT NULL
RETURN c.cycle_id AS cycle_id, c.seed_rumor AS seed_rumor, c.num_rounds AS num_rounds,
       c.overall_sentiment AS overall_sentiment
ORDER BY c.created_at
"""

DECISIONS_QUERY: Final = """
MATCH (a:Agent)-[:MADE]->(d:Decision)
WHERE d.cycle_id = $cycle_id AND d.round IN $rounds
RETURN a.id AS agent_id, d.round AS round, d.signal AS signal, d.confidence AS confidence
"""

Read = Callable[[str, Mapping[str, Any]], list[dict[str, Any]]]
Runner = Callable[[Sequence[str], Mapping[str, str]], int]


def pilot_events(events: Sequence[EvalEvent], only: Sequence[str]) -> list[EvalEvent]:
    if only:
        return [e for e in events if e.event_id in only]
    return list(events[:PILOT_EVENTS])


def run_pilot(
    events: Sequence[EvalEvent],
    *,
    read: Read,
    runner: Runner,
    paths: EvalPaths,
    since: str,
    inherited: Mapping[str, str],
    out: Callable[[str], object] = print,
) -> int:
    """Top every event up to REPEATS complete cycles; stop on a usage error (exit 2)."""
    done: dict[str, int] = {}
    for row in read(PILOT_CYCLES_QUERY, {"since": since}):
        key = normalize_rumor(str(row.get("seed_rumor") or ""))
        done[key] = done.get(key, 0) + 1
    env = {
        k: v
        for k, v in inherited.items()
        if k != "ALPHASWARM_NUM_ROUNDS" and not k.startswith("ALPHASWARM_SIMULATION__")
    }
    env["ALPHASWARM_NUM_ROUNDS"] = str(PILOT_ROUNDS)
    # No control holdout in the pilot either: every agent is peer-exposed and under test
    # (docs/DECISIONS.md#adr-eval-harness).
    env["ALPHASWARM_SIMULATION__CONTROL_FRACTION"] = "0.0"
    failures = 0
    for event in events:
        for repeat in range(done.get(normalize_rumor(event.rumor), 0) + 1, REPEATS + 1):
            out(f"[run] {event.event_id} repeat {repeat}")
            argv = [
                sys.executable,
                "-m",
                "alphaswarm",
                "run",
                event.rumor,
                "--context-fixture",
                str(paths.fixture(event.event_id, "named")),
            ]
            code = runner(argv, env)
            if code == 2:
                out(f"[stop] {event.event_id}: usage or configuration error")
                return 2
            if code != 0:
                out(f"[fail] {event.event_id} repeat {repeat}: exit {code}")
                failures += 1
    return 1 if failures else 0


def pilot_scores(
    read: Read, events: Sequence[EvalEvent], since: str
) -> tuple[list[tuple[str, str, float]], int]:
    """(event_id, forecaster, score) for every complete pilot cycle, and the matched count."""
    by_text = {normalize_rumor(e.rumor): e.event_id for e in events}
    rows: list[tuple[str, str, float]] = []
    matched = 0
    for cycle in read(PILOT_CYCLES_QUERY, {"since": since}):
        event_id = by_text.get(normalize_rumor(str(cycle.get("seed_rumor") or "")))
        if event_id is None:
            continue
        matched += 1
        final = int(cycle.get("num_rounds") or PILOT_ROUNDS)
        by_round: dict[int, list[AgentDecision]] = {}
        params = {"cycle_id": cycle["cycle_id"], "rounds": sorted({1, final})}
        for row in read(DECISIONS_QUERY, params):
            decision = AgentDecision(
                signal=SignalType(str(row["signal"]).lower()),
                confidence=float(row["confidence"] or 0.0),
            )
            by_round.setdefault(int(row["round"]), []).append(decision)
        for name, round_num in (("swarm", final), ("r1_only", 1)):
            score, n_valid = headcount_score(by_round.get(round_num, []))
            if n_valid >= MIN_VALID_VOTES:
                rows.append((event_id, name, score))
        sentiment = cycle.get("overall_sentiment")
        if isinstance(sentiment, int | float) and not isinstance(sentiment, bool):
            rows.append((event_id, "orchestrator", float(sentiment)))
    return rows, matched


def pilot_report(
    rows: Sequence[tuple[str, str, float]], labels: Mapping[str, OutcomeLabel], cycles: int
) -> str:
    body: list[list[str]] = []
    for name in ("swarm", "r1_only", "orchestrator"):
        scores = mean_by_event((e, s) for e, n, s in rows if n == name)
        for horizon in HORIZONS:
            result = score_forecaster(name, scores, labels, horizon, deadband=DEADBAND)
            body.append(
                [
                    name,
                    horizon,
                    str(result.n_events),
                    str(result.n_directional),
                    fmt_rate(result.hit_rate, result.hit_ci),
                    fmt(result.brier),
                    fmt(result.spearman, "+.2f"),
                ]
            )
    header = [
        "forecaster",
        "horizon",
        "events",
        "directional",
        "hit rate [95% CI]",
        "Brier",
        "Spearman rho",
    ]
    return "\n".join(
        [
            "## P7.7 pilot (PRELIMINARY: fast track, few events, unseeded repeats)",
            "",
            f"Complete pilot cycles matched: {cycles}.",
            "",
            markdown_table(header, body),
        ]
    )


def _open_reader() -> tuple[Read, Callable[[], None]]:
    from neo4j import GraphDatabase

    from alphaswarm.settings import AppSettings

    settings = AppSettings()
    driver = GraphDatabase.driver(
        settings.neo4j.uri, auth=(settings.neo4j.username, settings.neo4j.require_password())
    )

    def read(query: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        with driver.session(database=settings.neo4j.database) as session:
            rows: list[dict[str, Any]] = session.execute_read(
                lambda tx: tx.run(query, dict(params)).data()
            )
            return rows

    return read, driver.close


def _since() -> str:
    if not STARTED_AT.exists():
        STARTED_AT.parent.mkdir(parents=True, exist_ok=True)
        STARTED_AT.write_text(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")
    return STARTED_AT.read_text(encoding="utf-8").strip()


def _run_child(argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run(list(argv), env=dict(env), cwd=REPO_ROOT, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pilot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--events", default="")
    sub.add_parser("score")
    args = parser.parse_args(argv)
    events = read_jsonl(PATHS.events, EvalEvent)
    read, close = _open_reader()
    try:
        if args.command == "run":
            only = tuple(e for e in args.events.split(",") if e)
            return run_pilot(
                pilot_events(events, only),
                read=read,
                runner=_run_child,
                paths=PATHS,
                since=_since(),
                inherited=os.environ,
            )
        labels = {
            label.event_id: label for label in read_jsonl_if_exists(PATHS.labels, OutcomeLabel)
        }
        rows, matched = pilot_scores(read, events, _since())
        print(pilot_report(rows, labels, matched))
        return 0
    finally:
        close()


if __name__ == "__main__":
    raise SystemExit(main())
