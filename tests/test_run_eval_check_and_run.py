"""run_eval.py check, budget, registration and run (docs/methodology.md §2, §6, §9)."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from alphaswarm.evaluation import (
    EvalEvent,
    EvalPaths,
    OutcomeLabel,
    ablation_subset,
    normalize_rumor,
    sim_seed_for,
    write_jsonl,
)
from alphaswarm.ingestion.fixture import anonymize_packet, build_fixture_packet
from tests.support.eval_data import TODAY, WORKER_RELEASE, make_event, make_events, write_events
from tests.support.eval_scripts import load_eval_script

run_eval = load_eval_script("run_eval")


def _write_fixtures(paths: EvalPaths, event: EvalEvent, *, leak_anon: bool = False) -> None:
    packet = build_fixture_packet(
        event_id=event.event_id,
        as_of=event.timestamp,
        ticker=event.primary_ticker,
        close=Decimal("50.00"),
        volume=1000,
    )
    paths.fixtures.mkdir(parents=True, exist_ok=True)
    paths.fixture(event.event_id, "named").write_text(packet.model_dump_json(), encoding="utf-8")
    anon = packet if leak_anon else anonymize_packet(packet)
    paths.fixture(event.event_id, "anon").write_text(anon.model_dump_json(), encoding="utf-8")


def _label(event_id: str) -> OutcomeLabel:
    return OutcomeLabel(
        event_id=event_id, abn_ret_1d=0.01, abn_ret_5d=0.02, vol_scale=0.01, label_1d="up", label_5d="up"
    )


def test_sixteen_fictional_events_pass_the_check() -> None:
    assert run_eval.check_events(make_events(16), worker_release=WORKER_RELEASE, today=TODAY) == []


def test_check_reports_every_event_problem() -> None:
    events = make_events(14)
    assert run_eval.check_events(events, worker_release=WORKER_RELEASE, today=TODAY) == ["need 15-20 events, found 14"]
    duplicate = make_event(15, rumor=events[0].rumor)
    leak = make_event(16, anonymized_rumor="A company (ticker ZZZT) is said to explore a sale (fictional).")
    wrong_post = make_event(17, post_cutoff=False)
    recent = make_event(18, when=datetime(2026, 10, 1, 14, 30, tzinfo=UTC))
    problems = "\n".join(
        run_eval.check_events(
            [*events, duplicate, leak, wrong_post, recent],
            worker_release=WORKER_RELEASE,
            today=TODAY,
        )
    )
    assert "evt-015: named rumor duplicates evt-001" in problems
    assert "evt-016: anonymized_rumor names ZZZT" in problems
    assert "evt-017: post_cutoff should be True" in problems
    assert "evt-018: too recent" in problems


def test_check_enforces_post_cutoff_share_and_category_mix() -> None:
    pre_only = [make_event(i, post_cutoff=False) for i in range(1, 17)]
    assert run_eval.check_events(pre_only, worker_release=date(2026, 12, 1), today=TODAY) == [
        "post-cutoff share 0% is below 40%"
    ]
    one_category = [make_event(i, category="m_and_a") for i in range(1, 17)]
    assert run_eval.check_events(one_category, worker_release=WORKER_RELEASE, today=TODAY) == [
        "category m_and_a: 16 events (max 5)"
    ]


def test_check_reports_an_anonymized_fixture_naming_the_ticker(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    first, second, third = make_events(3)
    _write_fixtures(paths, first)
    _write_fixtures(paths, second, leak_anon=True)
    problems = run_eval.check_fixtures([first, second, third], paths)
    assert problems[0] == "evt-002 (anon): fixture names QQQX"
    assert problems[1].startswith("evt-003 (named): cannot read context fixture")
    assert run_eval.check_labels([first, second], [_label("evt-001")]) == ["evt-002: no outcome label"]


def test_arms_follow_the_registered_design() -> None:
    arms = run_eval.ARMS
    assert all(arm.tag == f"{arm.study}.{arm.name}" for arm in arms.values())
    assert [n for n, a in arms.items() if a.num_rounds == 3] == ["rounds3", "boost_0", "boost_005"]
    assert arms["anon"].seeds == (1,) and arms["anon"].variant == "anon"
    assert arms["uniform_temp"].overrides == {"uniform_temperature": 0.57}
    assert all(arm.reference in arms for arm in arms.values() if arm.reference is not None)
    events = make_events(16)
    assert len(run_eval.planned_runs(arms["swarm"], events)) == 48
    assert len(run_eval.planned_runs(arms["anon"], events)) == 16
    subset_runs = run_eval.planned_runs(arms["peer_none"], events)
    assert {s.event.event_id for s in subset_runs} == set(ablation_subset([e.event_id for e in events]))
    assert len(subset_runs) == 15
    only = run_eval.planned_runs(arms["swarm"], events, only=("evt-002",))
    assert [(s.event.event_id, s.seed) for s in only] == [("evt-002", 1), ("evt-002", 2), ("evt-002", 3)]


def test_arm_env_strips_stray_overrides_and_sets_the_arm() -> None:
    inherited = {
        "PATH": "/usr/bin",
        "ALPHASWARM_SIMULATION__CONTROL_FRACTION": "0.2",
        "ALPHASWARM_NUM_ROUNDS": "3",
        "ALPHASWARM_NEO4J__URI": "bolt://127.0.0.1:7687",
    }
    env = run_eval.arm_env(run_eval.ARMS["own_prior_off"], 2, inherited)
    assert env["PATH"] == "/usr/bin" and env["ALPHASWARM_NEO4J__URI"] == "bolt://127.0.0.1:7687"
    assert env["ALPHASWARM_SIMULATION__CONTROL_FRACTION"] == "0.0"  # run-wide pin, not the stray 0.2
    assert env["ALPHASWARM_NUM_ROUNDS"] == "2"
    assert env["ALPHASWARM_SIMULATION__SIM_SEED"] == str(sim_seed_for(2))
    assert env["ALPHASWARM_SIMULATION__EXPERIMENT_TAG"] == "p78.own_prior_off"
    assert env["ALPHASWARM_SIMULATION__OWN_PRIOR_MEMORY"] == "false"


def test_command_uses_the_variant_rumor_and_fixture(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    event = make_event(3)
    spec = run_eval.RunSpec(run_eval.ARMS["anon"], event, 1)
    argv = run_eval.command_for(spec, paths)
    assert argv[:4] == [sys.executable, "-m", "alphaswarm", "run"]
    assert argv[4] == event.anonymized_rumor
    assert argv[5:] == ["--context-fixture", str(paths.fixture("evt-003", "anon"))]
    assert spec.key == ("p77.anon", sim_seed_for(1), normalize_rumor(event.anonymized_rumor))


def test_run_refuses_simulation_keys_in_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ALPHASWARM_LOG_LEVEL=INFO\n"
        "# ALPHASWARM_SIMULATION__SIM_SEED=1\n"
        "export ALPHASWARM_SIMULATION__PERSONAL_BOOST=0.05\n"
        "ALPHASWARM_NUM_ROUNDS = 2\n",
        encoding="utf-8",
    )
    assert run_eval.dotenv_arm_keys(dotenv) == [
        "ALPHASWARM_SIMULATION__PERSONAL_BOOST",
        "ALPHASWARM_NUM_ROUNDS",
    ]
    assert run_eval.dotenv_arm_keys(tmp_path / "missing.env") == []
    monkeypatch.setattr(run_eval, "REPO_ROOT", tmp_path)
    assert run_eval.main(["run", "--arm", "swarm"]) == 2
    err = capsys.readouterr().err
    assert "ALPHASWARM_SIMULATION__PERSONAL_BOOST" in err and "0.05" not in err


class FakeNeo4j:
    """Read-only stand-in: answers COMPLETED_QUERY from a mutable set of keys."""

    def __init__(self, completed: set[tuple[str, int, str]]) -> None:
        self.completed = completed

    def read(self, query: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        assert query == run_eval.COMPLETED_QUERY
        return [
            {"tag": tag, "sim_seed": seed, "seed_rumor": rumor}
            for tag, seed, rumor in self.completed
            if tag in params["tags"]
        ]


def test_run_batch_resumes_and_stops_on_the_lock(tmp_path: Path) -> None:
    specs = run_eval.planned_runs(run_eval.ARMS["swarm"], make_events(2))
    neo4j = FakeNeo4j({specs[0].key})
    codes = iter([0, 1, 75])
    calls: list[tuple[Sequence[str], Mapping[str, str]]] = []

    def runner(argv: Sequence[str], env: Mapping[str, str]) -> int:
        calls.append((argv, env))
        code = next(codes)
        if code == 0:
            neo4j.completed.add(specs[len(calls)].key)
        return code

    lines: list[str] = []
    summary = run_eval.run_batch(
        specs,
        read=neo4j.read,
        runner=runner,
        paths=EvalPaths(tmp_path),
        inherited={"PATH": "/usr/bin"},
        out=lines.append,
    )
    assert (summary.ran, summary.skipped, summary.failed, summary.stopped) == (1, 1, 1, 75)
    assert len(calls) == 3
    assert calls[0][1]["ALPHASWARM_SIMULATION__SIM_SEED"] == str(sim_seed_for(2))
    assert any(line.startswith("[stop]") and "lock" in line for line in lines)


def test_exit_zero_without_a_complete_cycle_is_a_failure(tmp_path: Path) -> None:
    specs = run_eval.planned_runs(run_eval.ARMS["anon"], make_events(1))
    summary = run_eval.run_batch(
        specs,
        read=FakeNeo4j(set()).read,
        runner=lambda argv, env: 0,
        paths=EvalPaths(tmp_path),
        inherited={},
        out=lambda line: None,
    )
    assert (summary.ran, summary.failed, summary.stopped) == (0, 1, None)


def test_rerun_ignores_completed_keys_and_needs_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = run_eval.planned_runs(run_eval.ARMS["anon"], make_events(1))
    neo4j = FakeNeo4j({specs[0].key})
    calls: list[Sequence[str]] = []

    def runner(argv: Sequence[str], env: Mapping[str, str]) -> int:
        calls.append(argv)
        return 0

    summary = run_eval.run_batch(
        specs,
        read=neo4j.read,
        runner=runner,
        paths=EvalPaths(tmp_path),
        inherited={},
        rerun=True,
        out=lambda line: None,
    )
    assert (summary.ran, summary.skipped, len(calls)) == (1, 0, 1)
    monkeypatch.setattr(run_eval, "REPO_ROOT", tmp_path)
    assert run_eval.main(["run", "--arm", "anon", "--rerun"]) == 2


def test_dry_run_starts_nothing(tmp_path: Path) -> None:
    def runner(argv: Sequence[str], env: Mapping[str, str]) -> int:
        raise AssertionError("dry run must not start a cycle")

    lines: list[str] = []
    specs = run_eval.planned_runs(run_eval.ARMS["anon"], make_events(2))
    summary = run_eval.run_batch(
        specs,
        read=FakeNeo4j(set()).read,
        runner=runner,
        paths=EvalPaths(tmp_path),
        inherited={},
        dry_run=True,
        out=lines.append,
    )
    assert summary.ran == 0 and sum(line.startswith("[dry-run]") for line in lines) == 2


def test_budget_estimates_from_recent_cycles() -> None:
    rows = [
        {"num_rounds": 2, "total_seconds": 600.0, "seed_seconds": 40.0, "agent_count": 100},
        {"num_rounds": 3, "total_seconds": 900.0, "seed_seconds": 60.0, "agent_count": 100},
        {"num_rounds": 3, "total_seconds": None, "seed_seconds": None, "agent_count": 100},
    ]
    budget = run_eval.estimate_budget(rows)
    assert budget == run_eval.Budget(600.0, 900.0, pytest.approx(2.8))
    assert run_eval.estimate_budget([]) is None
    assert run_eval.estimate_budget([], seconds_2r=10.0, seconds_3r=15.0, seconds_per_call=0.1) == run_eval.Budget(
        10.0, 15.0, 0.1
    )
    only_three = run_eval.estimate_budget(rows[1:2])
    assert only_three is not None and only_three.seconds_2r == pytest.approx(600.0)


def test_budget_rows_cover_every_phase() -> None:
    rows = run_eval.budget_rows(16, run_eval.Budget(600.0, 900.0, 2.0), sc_k=200)
    phases = [row[0] for row in rows]
    assert phases[0] == "P7.7 swarm (named, 3 seeds)" and phases[-1] == "total"
    assert rows[0][1] == "48" and rows[0][3] == f"{48 * 600 / 3600:.1f}"
    assert "self_consistency (k=200)" in phases
    assert ("P7.8 private_headlines" in phases) == run_eval.private_headlines_available()
    assert "P7.8 boost_0" in phases and "P7.8 rounds3" in phases


def test_registration_record_hashes_the_registered_files(tmp_path: Path) -> None:
    paths = EvalPaths(tmp_path)
    events = make_events(16)
    write_events(paths.events, events)
    for event in events:
        _write_fixtures(paths, event)
    write_jsonl(paths.labels, [_label(e.event_id) for e in events])
    frozen = run_eval.write_registered_simulation(paths)
    assert run_eval.registered_simulation(paths) == run_eval.frozen_simulation_defaults()
    assert run_eval.registered_simulation(EvalPaths(tmp_path / "none")) is None
    record = run_eval.registration_record(
        events,
        paths,
        worker_release=WORKER_RELEASE,
        backend="A: local Ollama/MLX",
        today=TODAY,
    )
    assert record.startswith("## 11. Registration record")
    assert hashlib.sha256(paths.events.read_bytes()).hexdigest() in record
    assert hashlib.sha256(paths.labels.read_bytes()).hexdigest() in record
    assert "32 files" in record and "A: local Ollama/MLX" in record
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() in record
    assert ", ".join(ablation_subset([e.event_id for e in events])) in record
