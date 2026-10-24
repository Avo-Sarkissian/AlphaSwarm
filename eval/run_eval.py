#!/usr/bin/env python3
"""Point-in-time accuracy evaluation and seeded ablations.

Every rule is pre-registered in docs/methodology.md (docs/DECISIONS.md#adr-eval-harness).
Neo4j is only read (MATCH ... RETURN in read transactions); cycles are written by
`alphaswarm run`, which `run` launches once per missing cycle with the arm's seed,
tag and knobs. Run from the repo root in the owner's shell with the web server stopped.

    uv run python eval/run_eval.py check --worker-release 2026-04-01 --require-fixtures
    uv run python eval/run_eval.py budget [--n-events 18]
    uv run python eval/run_eval.py registration --worker-release 2026-04-01 --backend "A: local"
    uv run python eval/run_eval.py run --arm swarm [--events evt-001,evt-002] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any, Final, Literal

from alphaswarm.evaluation import (
    ABLATION_SUBSET_SIZE,
    DEFAULT_SC_K,
    EVAL_NUM_ROUNDS,
    EVAL_SEEDS,
    MAX_EVENTS,
    MIN_EVENTS,
    MIN_POST_CUTOFF_SHARE,
    SINGLE_K,
    EvalEvent,
    EvalPaths,
    OutcomeLabel,
    Variant,
    ablation_subset,
    markdown_table,
    mean_bracket_temperature,
    normalize_rumor,
    read_jsonl,
    read_jsonl_if_exists,
    sim_seed_for,
)
from alphaswarm.ingestion.fixture import load_context_fixture
from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.settings import AppSettings, SimulationSettings

EVAL_DIR: Final = Path(__file__).resolve().parent
REPO_ROOT: Final = EVAL_DIR.parent
PATHS: Final = EvalPaths(EVAL_DIR)
VARIANTS: Final[tuple[Variant, ...]] = ("named", "anon")
UNIFORM_TEMPERATURE: Final = mean_bracket_temperature(DEFAULT_BRACKETS)
MIN_EVENT_AGE: Final = timedelta(days=10)
MAX_PER_CATEGORY: Final = 5
SIM_ENV_PREFIX: Final = "ALPHASWARM_SIMULATION__"
ROUNDS_ENV: Final = "ALPHASWARM_NUM_ROUNDS"
STOP_CODES: Final[dict[int, str]] = {
    2: "configuration or usage error (see the message above)",
    75: "another AlphaSwarm instance holds the lock; stop the web server first",
    130: "interrupted",
}
# Every eval arm runs without the control holdout, whatever its default is: the swarm
# under test is fully peer-exposed and peer_none is the peer-free contrast (methodology §6).
RUN_PINS: Final[Mapping[str, object]] = {"control_fraction": 0.0}

Read = Callable[[str, Mapping[str, Any]], list[dict[str, Any]]]
Runner = Callable[[Sequence[str], Mapping[str, str]], int]
Out = Callable[[str], object]


@dataclass(frozen=True)
class Arm:
    """One pre-registered run configuration (docs/methodology.md §6, §9)."""

    name: str
    tag: str
    num_rounds: int
    overrides: Mapping[str, object] = field(default_factory=dict)
    reference: str | None = None
    variant: Variant = "named"
    seeds: tuple[int, ...] = EVAL_SEEDS
    study: Literal["p77", "p78"] = "p78"


ARMS: Final[dict[str, Arm]] = {
    "swarm": Arm("swarm", "p77.swarm", EVAL_NUM_ROUNDS, study="p77"),
    "anon": Arm("anon", "p77.anon", EVAL_NUM_ROUNDS, variant="anon", seeds=(1,), study="p77"),
    "rounds3": Arm("rounds3", "p78.rounds3", 3, reference="swarm"),
    "peer_random": Arm("peer_random", "p78.peer_random", EVAL_NUM_ROUNDS, {"peer_strategy": "random"}, "swarm"),
    "peer_none": Arm("peer_none", "p78.peer_none", EVAL_NUM_ROUNDS, {"peer_strategy": "none"}, "swarm"),
    "boost_0": Arm("boost_0", "p78.boost_0", 3, {"personal_boost": 0.0}, "rounds3"),
    "boost_005": Arm("boost_005", "p78.boost_005", 3, {"personal_boost": 0.05}, "rounds3"),
    "own_prior_off": Arm("own_prior_off", "p78.own_prior_off", EVAL_NUM_ROUNDS, {"own_prior_memory": False}, "swarm"),
    "uniform_temp": Arm(
        "uniform_temp",
        "p78.uniform_temp",
        EVAL_NUM_ROUNDS,
        {"uniform_temperature": UNIFORM_TEMPERATURE},
        "swarm",
    ),
    "private_headlines": Arm(
        "private_headlines",
        "p78.private_headlines",
        EVAL_NUM_ROUNDS,
        {"private_headlines": True},
        "swarm",
    ),
}

COMPLETED_QUERY: Final = """
MATCH (c:Cycle)
WHERE c.experiment_tag IN $tags AND c.status = 'complete'
RETURN c.experiment_tag AS tag, c.sim_seed AS sim_seed, c.seed_rumor AS seed_rumor
"""

BUDGET_QUERY: Final = """
MATCH (c:Cycle)
WHERE c.status = 'complete' AND c.total_seconds IS NOT NULL
RETURN c.num_rounds AS num_rounds, c.total_seconds AS total_seconds,
       c.seed_seconds AS seed_seconds, c.agent_count AS agent_count
ORDER BY c.created_at DESC
LIMIT $limit
"""


# --- check -------------------------------------------------------------------------


def ticker_mentioned(ticker: str, text: str) -> bool:
    """Case-sensitive whole-word match (an optional $ prefix); 1-letter tickers are not checked."""
    if len(ticker) < 2:
        return False
    return re.search(rf"(?<![A-Za-z0-9])\$?{re.escape(ticker)}(?![A-Za-z0-9])", text) is not None


def check_events(events: Sequence[EvalEvent], *, worker_release: date, today: date) -> list[str]:
    """Every docs/methodology.md §2 rule that the event file itself can violate."""
    problems: list[str] = []
    if not MIN_EVENTS <= len(events) <= MAX_EVENTS:
        problems.append(f"need {MIN_EVENTS}-{MAX_EVENTS} events, found {len(events)}")
    seen_ids: set[str] = set()
    seen_texts: dict[str, str] = {}
    categories: dict[str, int] = {}
    for event in events:
        if event.event_id in seen_ids:
            problems.append(f"{event.event_id}: duplicate event_id")
        seen_ids.add(event.event_id)
        texts = {variant: normalize_rumor(event.rumor_for(variant)) for variant in VARIANTS}
        if texts["named"] == texts["anon"]:
            problems.append(f"{event.event_id}: anonymized_rumor equals rumor")
        for variant, text in texts.items():
            other = seen_texts.setdefault(text, event.event_id)
            if other != event.event_id:
                problems.append(f"{event.event_id}: {variant} rumor duplicates {other}")
        if ticker_mentioned(event.primary_ticker, event.anonymized_rumor):
            problems.append(f"{event.event_id}: anonymized_rumor names {event.primary_ticker}")
        expected_post = event.timestamp.date() > worker_release
        if event.post_cutoff != expected_post:
            problems.append(
                f"{event.event_id}: post_cutoff should be {expected_post} for a worker "
                f"released {worker_release.isoformat()}"
            )
        if event.timestamp.date() > today - MIN_EVENT_AGE:
            problems.append(f"{event.event_id}: too recent; labels need {MIN_EVENT_AGE.days} days")
        categories[event.category] = categories.get(event.category, 0) + 1
    for category, count in sorted(categories.items()):
        if count > MAX_PER_CATEGORY:
            problems.append(f"category {category}: {count} events (max {MAX_PER_CATEGORY})")
    if events:
        share = sum(1 for e in events if e.post_cutoff) / len(events)
        if share < MIN_POST_CUTOFF_SHARE:
            problems.append(f"post-cutoff share {share:.0%} is below {MIN_POST_CUTOFF_SHARE:.0%}")
    return problems


def check_fixtures(events: Sequence[EvalEvent], paths: EvalPaths) -> list[str]:
    problems: list[str] = []
    for event in events:
        for variant in VARIANTS:
            path = paths.fixture(event.event_id, variant)
            try:
                load_context_fixture(path, not_after=event.timestamp)
            except ValueError as exc:
                problems.append(f"{event.event_id} ({variant}): {exc}")
                continue
            if variant == "anon" and ticker_mentioned(event.primary_ticker, path.read_text(encoding="utf-8")):
                problems.append(f"{event.event_id} (anon): fixture names {event.primary_ticker}")
    return problems


def check_labels(events: Sequence[EvalEvent], labels: Sequence[OutcomeLabel]) -> list[str]:
    have = {label.event_id for label in labels}
    return [f"{e.event_id}: no outcome label" for e in events if e.event_id not in have]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen_simulation_defaults() -> dict[str, Any]:
    """Today's SimulationSettings defaults (sim_seed and experiment_tag unset)."""
    return SimulationSettings().model_dump(mode="json")


def write_registered_simulation(paths: EvalPaths) -> Path:
    """Freeze the defaults scoring compares manifests against (docs/methodology.md §11)."""
    path = paths.registered_simulation
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(frozen_simulation_defaults(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def registered_simulation(paths: EvalPaths) -> dict[str, Any] | None:
    """The registered defaults, or None before registration (live defaults stand in)."""
    path = paths.registered_simulation
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def registration_record(
    events: Sequence[EvalEvent],
    paths: EvalPaths,
    *,
    worker_release: date,
    backend: str,
    today: date,
) -> str:
    """docs/methodology.md §11: hashes that commit to events, fixtures and labels before runs."""
    fixtures = sorted(paths.fixtures.glob("evt-*.json"))
    post = sum(1 for e in events if e.post_cutoff)
    fixture_digest = _sha256(b"".join(p.read_bytes() for p in fixtures))
    frozen = paths.registered_simulation
    frozen_row = (
        f"eval/registered_simulation.json sha256 {_sha256(frozen.read_bytes())}" if frozen.exists() else "not written"
    )
    rows = [
        ["Registered on", today.isoformat()],
        ["Worker release date (post-cutoff boundary)", worker_release.isoformat()],
        ["Backend", backend],
        ["Events", f"{len(events)} ({post} post-cutoff); sha256 {_sha256(paths.events.read_bytes())}"],
        ["Fixtures", f"{len(fixtures)} files; sha256 of their concatenation in name order {fixture_digest}"],
        ["Labels", f"sha256 {_sha256(paths.labels.read_bytes())}"],
        ["Ablation subset", ", ".join(ablation_subset([e.event_id for e in events]))],
        ["Seeds", ", ".join(f"{s} -> sim_seed {sim_seed_for(s)}" for s in EVAL_SEEDS)],
        ["Swarm rounds", f"{EVAL_NUM_ROUNDS} (3 for rounds3, boost_0, boost_005)"],
        ["Uniform-arm and baseline temperature", f"{UNIFORM_TEMPERATURE}"],
        ["Run-wide pins", ", ".join(f"{k} = {v}" for k, v in RUN_PINS.items())],
        ["Simulation defaults", frozen_row],
    ]
    return "## 11. Registration record\n\n" + markdown_table(["Item", "Value"], rows)


# --- runs --------------------------------------------------------------------------


def arm_events(arm: Arm, events: Sequence[EvalEvent]) -> list[EvalEvent]:
    """Accuracy arms (p77) cover every event; ablation arms (p78) the pre-registered subset."""
    if arm.study == "p77":
        return list(events)
    subset = set(ablation_subset([e.event_id for e in events]))
    return [e for e in events if e.event_id in subset]


@dataclass(frozen=True)
class RunSpec:
    arm: Arm
    event: EvalEvent
    seed: int

    @property
    def key(self) -> tuple[str, int, str]:
        """(tag, sim_seed, normalized rumor): what identifies a finished cycle in Neo4j."""
        rumor = normalize_rumor(self.event.rumor_for(self.arm.variant))
        return (self.arm.tag, sim_seed_for(self.seed), rumor)

    @property
    def label(self) -> str:
        return f"{self.arm.name} {self.event.event_id} seed {self.seed}"


def planned_runs(arm: Arm, events: Sequence[EvalEvent], *, only: Sequence[str] = ()) -> list[RunSpec]:
    chosen = [e for e in arm_events(arm, events) if not only or e.event_id in only]
    return [RunSpec(arm, event, seed) for event in chosen for seed in arm.seeds]


def env_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def is_arm_variable(name: str) -> bool:
    return name.startswith(SIM_ENV_PREFIX) or name == ROUNDS_ENV


def arm_env(arm: Arm, seed: int, inherited: Mapping[str, str]) -> dict[str, str]:
    """The child environment: inherited minus every arm variable, plus this arm's values."""
    env = {k: v for k, v in inherited.items() if not is_arm_variable(k)}
    env[ROUNDS_ENV] = str(arm.num_rounds)
    env[f"{SIM_ENV_PREFIX}SIM_SEED"] = str(sim_seed_for(seed))
    env[f"{SIM_ENV_PREFIX}EXPERIMENT_TAG"] = arm.tag
    for name, value in {**RUN_PINS, **arm.overrides}.items():
        env[f"{SIM_ENV_PREFIX}{name.upper()}"] = env_value(value)
    return env


def dotenv_arm_keys(path: Path) -> list[str]:
    """Names (never values) of arm variables set in a dotenv file."""
    if not path.exists():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if is_arm_variable(key):
            keys.append(key)
    return keys


def private_headlines_available() -> bool:
    """True when SimulationSettings has the private-headlines experiment flag."""
    return "private_headlines" in SimulationSettings.model_fields


def command_for(spec: RunSpec, paths: EvalPaths) -> list[str]:
    fixture = paths.fixture(spec.event.event_id, spec.arm.variant)
    return [
        sys.executable,
        "-m",
        "alphaswarm",
        "run",
        spec.event.rumor_for(spec.arm.variant),
        "--context-fixture",
        str(fixture),
    ]


def completed_keys(read: Read, tags: Sequence[str]) -> set[tuple[str, int, str]]:
    rows = read(COMPLETED_QUERY, {"tags": list(tags)})
    return {
        (str(row["tag"]), int(row["sim_seed"]), normalize_rumor(str(row["seed_rumor"])))
        for row in rows
        if row.get("sim_seed") is not None and row.get("seed_rumor")
    }


@dataclass
class RunSummary:
    ran: int = 0
    skipped: int = 0
    failed: int = 0
    stopped: int | None = None


def run_batch(
    specs: Sequence[RunSpec],
    *,
    read: Read,
    runner: Runner,
    paths: EvalPaths,
    inherited: Mapping[str, str],
    dry_run: bool = False,
    rerun: bool = False,
    out: Out = print,
) -> RunSummary:
    """Run every spec without a complete cycle (all specs with *rerun*); stop on 2, 75, 130."""
    summary = RunSummary()
    if not specs:
        return summary
    done: set[tuple[str, int, str]] = set() if rerun else completed_keys(read, sorted({s.arm.tag for s in specs}))
    for spec in specs:
        if spec.key in done:
            summary.skipped += 1
            continue
        if dry_run:
            out(f"[dry-run] {spec.label}")
            continue
        out(f"[run] {spec.label}")
        code = runner(command_for(spec, paths), arm_env(spec.arm, spec.seed, inherited))
        if code in STOP_CODES:
            out(f"[stop] {spec.label}: exit {code}: {STOP_CODES[code]}")
            summary.stopped = code
            break
        if code != 0:
            out(f"[fail] {spec.label}: exit {code}; rerun `run` to retry")
            summary.failed += 1
            continue
        if spec.key not in completed_keys(read, [spec.arm.tag]):
            out(f"[fail] {spec.label}: exit 0 but no complete cycle was found")
            summary.failed += 1
            continue
        summary.ran += 1
    return summary


def subprocess_runner(argv: Sequence[str], env: Mapping[str, str]) -> int:
    """One `alphaswarm run` in its own process (fresh memory, own instance lock)."""
    return subprocess.run(list(argv), env=dict(env), cwd=REPO_ROOT, check=False).returncode


def open_reader() -> tuple[Read, Callable[[], None]]:
    """Read-only Cypher against the configured Neo4j (credentials come from AppSettings)."""
    from neo4j import GraphDatabase

    settings = AppSettings()
    driver = GraphDatabase.driver(settings.neo4j.uri, auth=(settings.neo4j.username, settings.neo4j.require_password()))

    def read(query: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        with driver.session(database=settings.neo4j.database) as session:
            rows: list[dict[str, Any]] = session.execute_read(lambda tx: tx.run(query, dict(params)).data())
            return rows

    return read, driver.close


# --- budget ------------------------------------------------------------------------


@dataclass(frozen=True)
class Budget:
    seconds_2r: float
    seconds_3r: float
    seconds_per_call: float


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def estimate_budget(
    rows: Sequence[Mapping[str, Any]],
    *,
    seconds_2r: float | None = None,
    seconds_3r: float | None = None,
    seconds_per_call: float | None = None,
) -> Budget | None:
    """Seconds per 2-/3-round cycle and per worker call from recent cycles (or overrides)."""
    two: list[float] = []
    three: list[float] = []
    per_call: list[float] = []
    for row in rows:
        total = _number(row.get("total_seconds"))
        rounds = row.get("num_rounds")
        if total is None or rounds not in (2, 3):
            continue
        (two if rounds == 2 else three).append(total)
        agents = _number(row.get("agent_count"))
        if agents:
            seed = _number(row.get("seed_seconds")) or 0.0
            per_call.append((total - seed) / (agents * int(rounds)))
    s2 = seconds_2r
    if s2 is None:
        s2 = fmean(two) if two else (fmean(three) * 2 / 3 if three else None)
    s3 = seconds_3r
    if s3 is None:
        s3 = fmean(three) if three else (s2 * 1.5 if s2 is not None else None)
    spc = seconds_per_call if seconds_per_call is not None else (fmean(per_call) if per_call else None)
    if s2 is None or s3 is None or spc is None:
        return None
    return Budget(s2, s3, spc)


def budget_rows(n_events: int, budget: Budget, *, sc_k: int) -> list[list[str]]:
    """Hours per planned phase, in cost order, and the total."""
    rows: list[list[str]] = []
    total = 0.0

    def add(phase: str, units: int, unit: str, seconds: float) -> None:
        nonlocal total
        total += seconds
        rows.append([phase, str(units), unit, f"{seconds / 3600:.1f}"])

    seeds = len(EVAL_SEEDS)
    add("P7.7 swarm (named, 3 seeds)", n_events * seeds, "cycles", n_events * seeds * budget.seconds_2r)
    add("P7.7 anon (seed 1)", n_events, "cycles", n_events * budget.seconds_2r)
    single = n_events * (seeds + 1) * SINGLE_K
    add("single_k5 (named seeds 1-3, anon seed 1)", single, "worker calls", single * budget.seconds_per_call)
    add("probe", n_events, "worker calls", n_events * budget.seconds_per_call)
    sc_calls = n_events * seeds * sc_k
    add(f"self_consistency (k={sc_k})", sc_calls, "worker calls", sc_calls * budget.seconds_per_call)
    subset = min(ABLATION_SUBSET_SIZE, n_events)
    for arm in ARMS.values():
        if arm.study != "p78":
            continue
        if arm.name == "private_headlines" and not private_headlines_available():
            continue
        cycles = subset * len(arm.seeds)
        per_cycle = budget.seconds_3r if arm.num_rounds == 3 else budget.seconds_2r
        add(f"P7.8 {arm.name}", cycles, "cycles", cycles * per_cycle)
    rows.append(["total", "", "", f"{total / 3600:.1f}"])
    return rows


# --- command line ------------------------------------------------------------------


def _today() -> date:
    return datetime.now(UTC).date()


def _event_filter(value: str) -> tuple[str, ...]:
    return tuple(e for e in value.split(",") if e)


def _cmd_check(args: argparse.Namespace) -> int:
    events: list[EvalEvent] = []
    try:
        events = read_jsonl(PATHS.events, EvalEvent)
        problems = check_events(events, worker_release=args.worker_release, today=args.today)
        if args.require_fixtures:
            problems += check_fixtures(events, PATHS)
        if args.require_labels:
            problems += check_labels(events, read_jsonl_if_exists(PATHS.labels, OutcomeLabel))
    except (OSError, ValueError) as exc:
        problems = [str(exc)]
    for problem in problems:
        print(f"problem: {problem}")
    if problems:
        return 1
    post = sum(1 for e in events if e.post_cutoff)
    print(f"OK: {len(events)} events, {post} post-cutoff ({post / len(events):.0%})")
    return 0


def _cmd_budget(args: argparse.Namespace) -> int:
    n_events = args.n_events
    if n_events is None:
        if not PATHS.events.exists():
            print("No eval/events.jsonl yet: pass --n-events.", file=sys.stderr)
            return 2
        n_events = len(read_jsonl(PATHS.events, EvalEvent))
    rows: list[dict[str, Any]] = []
    if None in (args.seconds_2r, args.seconds_3r, args.seconds_per_call):
        read, close = open_reader()
        try:
            rows = read(BUDGET_QUERY, {"limit": args.limit})
        finally:
            close()
    budget = estimate_budget(
        rows,
        seconds_2r=args.seconds_2r,
        seconds_3r=args.seconds_3r,
        seconds_per_call=args.seconds_per_call,
    )
    if budget is None:
        print(
            "No complete cycles with total_seconds: pass --seconds-2r, --seconds-3r and --seconds-per-call.",
            file=sys.stderr,
        )
        return 2
    print(
        f"per 2-round cycle {budget.seconds_2r:.0f} s, per 3-round cycle {budget.seconds_3r:.0f} s, "
        f"per worker call {budget.seconds_per_call:.2f} s ({len(rows)} cycles read)"
    )
    print(markdown_table(["phase", "units", "unit", "hours"], budget_rows(n_events, budget, sc_k=args.sc_k)))
    return 0


def _cmd_registration(args: argparse.Namespace) -> int:
    events = read_jsonl(PATHS.events, EvalEvent)
    labels = read_jsonl_if_exists(PATHS.labels, OutcomeLabel)
    problems = (
        check_events(events, worker_release=args.worker_release, today=args.today)
        + check_fixtures(events, PATHS)
        + check_labels(events, labels)
    )
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        return 1
    if PATHS.registered_simulation.exists():
        print(f"keeping the existing {PATHS.registered_simulation.name}", file=sys.stderr)
    else:
        write_registered_simulation(PATHS)
    print(
        registration_record(
            events,
            PATHS,
            worker_release=args.worker_release,
            backend=args.backend,
            today=args.today,
        )
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    arm = ARMS[args.arm]
    if args.rerun and not args.events:
        print("--rerun needs --events: rerun only the cycles you name.", file=sys.stderr)
        return 2
    if arm.name == "private_headlines" and not private_headlines_available():
        print("The private_headlines arm needs SimulationSettings.private_headlines.", file=sys.stderr)
        return 2
    stray = dotenv_arm_keys(REPO_ROOT / ".env")
    if stray:
        print(
            "Remove these keys from .env before eval runs (they would override the arm): " + ", ".join(stray),
            file=sys.stderr,
        )
        return 2
    ignored = sorted(k for k in os.environ if is_arm_variable(k))
    if ignored:
        print("Ignoring shell overrides for eval runs: " + ", ".join(ignored))
    events = read_jsonl(PATHS.events, EvalEvent)
    specs = planned_runs(arm, events, only=args.events)
    missing = sorted({s.event.event_id for s in specs if not PATHS.fixture(s.event.event_id, arm.variant).exists()})
    if missing:
        print(f"Missing fixtures for {', '.join(missing)}: run eval/build_fixtures.py first.", file=sys.stderr)
        return 2
    read, close = open_reader()
    try:
        summary = run_batch(
            specs,
            read=read,
            runner=subprocess_runner,
            paths=PATHS,
            inherited=os.environ,
            dry_run=args.dry_run,
            rerun=args.rerun,
        )
    finally:
        close()
    print(f"ran {summary.ran}, skipped {summary.skipped} (already complete), failed {summary.failed}")
    if summary.stopped is not None:
        return summary.stopped
    return 1 if summary.failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate events, fixtures and labels")
    check.add_argument(
        "--worker-release",
        type=date.fromisoformat,
        required=True,
        help="worker model release date, YYYY-MM-DD (post-cutoff boundary)",
    )
    check.add_argument("--today", type=date.fromisoformat, default=_today())
    check.add_argument("--require-fixtures", action="store_true")
    check.add_argument("--require-labels", action="store_true")
    check.set_defaults(func=_cmd_check)

    budget = sub.add_parser("budget", help="estimate machine time for every planned phase")
    budget.add_argument("--n-events", type=int, default=None)
    budget.add_argument("--sc-k", type=int, default=DEFAULT_SC_K)
    budget.add_argument("--limit", type=int, default=20, help="recent complete cycles to average")
    budget.add_argument("--seconds-2r", type=float, default=None)
    budget.add_argument("--seconds-3r", type=float, default=None)
    budget.add_argument("--seconds-per-call", type=float, default=None)
    budget.set_defaults(func=_cmd_budget)

    registration = sub.add_parser("registration", help="print the methodology registration record")
    registration.add_argument("--worker-release", type=date.fromisoformat, required=True)
    registration.add_argument("--backend", required=True, help='e.g. "A: local Ollama/MLX"')
    registration.add_argument("--today", type=date.fromisoformat, default=_today())
    registration.set_defaults(func=_cmd_registration)

    run = sub.add_parser("run", help="run the missing cycles of one arm through `alphaswarm run`")
    run.add_argument("--arm", choices=sorted(ARMS), required=True)
    run.add_argument("--events", type=_event_filter, default=(), help="comma-separated event ids")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--rerun",
        action="store_true",
        help="run the named events again even if a complete cycle exists (needs --events)",
    )
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.func
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
