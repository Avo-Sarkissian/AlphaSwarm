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
    uv run python eval/run_eval.py score [--no-parquet]
    uv run python eval/run_eval.py ablations
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from statistics import fmean
from typing import Any, Final, Literal

from alphaswarm.consensus import NET_SCORE_DEADBAND, net_score
from alphaswarm.evaluation import (
    ABLATION_SUBSET_SIZE,
    DEFAULT_SC_K,
    EVAL_NUM_ROUNDS,
    EVAL_SEEDS,
    MAX_EVENTS,
    MIN_EVENTS,
    MIN_POST_CUTOFF_SHARE,
    SEED_BASE,
    SINGLE_K,
    BaselineRecord,
    EvalEvent,
    EvalPaths,
    Horizon,
    Interval,
    OutcomeLabel,
    ProbeRecord,
    ReliabilityBin,
    Variant,
    ablation_subset,
    advise_g15,
    advise_g16,
    advise_g20,
    boot_rng,
    brier,
    brier_by_event,
    cluster_bootstrap,
    fmt,
    fmt_interval,
    fmt_rate,
    lean3,
    markdown_table,
    mean_bracket_temperature,
    mean_by_event,
    min_valid_baseline,
    normalize_rumor,
    p_up,
    paired_difference,
    read_jsonl,
    read_jsonl_if_exists,
    reliability_bins,
    score_forecaster,
    sim_seed_for,
    verdict,
)
from alphaswarm.ingestion.fixture import load_context_fixture
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas, load_bracket_configs
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentDecision, AgentPersona, BracketType, SignalType

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


# --- score -------------------------------------------------------------------------

CYCLES_QUERY: Final = """
MATCH (c:Cycle)
WHERE c.experiment_tag IN $tags
RETURN properties(c) AS props
ORDER BY c.created_at
"""

DECISIONS_QUERY: Final = """
MATCH (a:Agent)-[:MADE]->(d:Decision)
WHERE d.cycle_id = $cycle_id AND d.round IN $rounds
RETURN a.id AS agent_id, d.round AS round, d.signal AS signal, d.confidence AS confidence
"""

MIN_VALID_VOTES: Final = 50
MIN_NARRATOR_VOTES: Final = 4
METRIC_TOLERANCE: Final = 1e-6
SWARM_FORECASTERS: Final = (
    "swarm",
    "swarm_reach",
    "swarm_ex_narrators",
    "narrators_only",
    "r1_only",
    "orchestrator",
)
FORECASTERS: Final = (*SWARM_FORECASTERS, "single_k5", "self_consistency")
COMPARED: Final = (
    "orchestrator",
    "r1_only",
    "single_k5",
    "self_consistency",
    "swarm_reach",
    "swarm_ex_narrators",
    "narrators_only",
)
LEAKAGE_FORECASTERS: Final = ("swarm", "orchestrator", "r1_only", "single_k5")
RELIABILITY_FORECASTERS: Final = ("swarm", "r1_only", "orchestrator", "single_k5", "self_consistency")

Pairs = list[tuple[str, AgentDecision]]


@dataclass(frozen=True)
class CycleRun:
    arm: Arm
    event_id: str
    seed: int
    cycle_id: str
    props: Mapping[str, Any]
    manifest: Mapping[str, Any]


@dataclass
class MatchReport:
    matched: int = 0
    incomplete: int = 0
    orphans: int = 0
    duplicates: int = 0
    excluded: Counter[str] = field(default_factory=Counter)
    warnings: Counter[str] = field(default_factory=Counter)

    def lines(self) -> list[str]:
        out = [
            f"- cycles used: {self.matched}",
            f"- not complete: {self.incomplete}",
            f"- unmatched (rumor, variant or seed): {self.orphans}",
            f"- older duplicates replaced: {self.duplicates}",
        ]
        out += [f"- excluded ({reason}): {count}" for reason, count in sorted(self.excluded.items())]
        out += [f"- warning ({reason}): {count}" for reason, count in sorted(self.warnings.items())]
        return out


def expected_simulation(arm: Arm, seed: int, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The SimulationSettings an arm's cycle must have run with.

    *base* is the defaults frozen at registration (eval/registered_simulation.json); without
    it today's defaults stand in. The run-wide pins and the arm's knobs go on top, so a
    default changed after the runs (rounds, R3 boost) never turns stored cycles into drift.
    """
    expected = dict(base) if base is not None else frozen_simulation_defaults()
    knobs: dict[str, object] = {
        **RUN_PINS,
        **arm.overrides,
        "sim_seed": sim_seed_for(seed),
        "experiment_tag": arm.tag,
    }
    validated = SimulationSettings.model_validate(knobs)
    expected.update(validated.model_dump(mode="json", include=set(knobs)))
    return expected


def manifest_problem(
    props: Mapping[str, Any], arm: Arm, seed: int, *, base: Mapping[str, Any] | None = None
) -> tuple[str | None, dict[str, Any]]:
    """Why a cycle's run manifest disagrees with its planned arm, or None."""
    raw = props.get("run_manifest_json")
    if not isinstance(raw, str) or not raw:
        return "no manifest", {}
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return "unreadable manifest", {}
    if not isinstance(manifest, dict):
        return "unreadable manifest", {}
    if manifest.get("num_rounds") != arm.num_rounds:
        return "num_rounds drift", manifest
    if manifest.get("sim_seed") != sim_seed_for(seed) or manifest.get("experiment_tag") != arm.tag:
        return "seed or tag drift", manifest
    actual = manifest.get("simulation")
    if not isinstance(actual, dict):
        return "settings drift", manifest
    expected = expected_simulation(arm, seed, base)
    if any(key in actual and actual[key] != value for key, value in expected.items()):
        return "settings drift", manifest
    return None, manifest


def _text_index(events: Sequence[EvalEvent]) -> dict[str, tuple[str, Variant]]:
    index: dict[str, tuple[str, Variant]] = {}
    for event in events:
        for variant in VARIANTS:
            index[normalize_rumor(event.rumor_for(variant))] = (event.event_id, variant)
    return index


def _drop_context_drift(runs: dict[tuple[str, str, int], CycleRun], report: MatchReport) -> None:
    """Keep, per event and variant, only cycles whose market block is the majority block."""
    groups: dict[tuple[str, str], list[tuple[str, str, int]]] = defaultdict(list)
    for key, run in runs.items():
        groups[(run.event_id, run.arm.variant)].append(key)
    for keys in groups.values():
        blocks = Counter(str(runs[k].manifest.get("market_context")) for k in keys)
        majority = blocks.most_common(1)[0][0]
        for key in keys:
            if str(runs[key].manifest.get("market_context")) != majority:
                del runs[key]
                report.excluded["context drift"] += 1


def match_cycles(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[EvalEvent],
    arms: Mapping[str, Arm],
    *,
    base: Mapping[str, Any] | None = None,
) -> tuple[dict[tuple[str, str, int], CycleRun], MatchReport]:
    """Map stored cycles (oldest first) to (arm, event, seed); the newest valid one wins."""
    report = MatchReport()
    by_tag = {arm.tag: arm for arm in arms.values()}
    texts = _text_index(events)
    runs: dict[tuple[str, str, int], CycleRun] = {}
    for row in rows:
        props: Mapping[str, Any] = row.get("props") or {}
        arm = by_tag.get(str(props.get("experiment_tag")))
        if arm is None:
            continue
        if props.get("status") != "complete":
            report.incomplete += 1
            continue
        hit = texts.get(normalize_rumor(str(props.get("seed_rumor") or "")))
        seed = int(props.get("sim_seed") or 0) - SEED_BASE
        if hit is None or hit[1] != arm.variant or seed not in arm.seeds:
            report.orphans += 1
            continue
        problem, manifest = manifest_problem(props, arm, seed, base=base)
        if problem is not None:
            report.excluded[problem] += 1
            continue
        key = (arm.name, hit[0], seed)
        if key in runs:
            report.duplicates += 1
        runs[key] = CycleRun(arm, hit[0], seed, str(props.get("cycle_id")), props, manifest)
    _drop_context_drift(runs, report)
    report.matched = len(runs)
    return runs, report


def final_round(props: Mapping[str, Any]) -> int:
    return int(props.get("final_round") or props.get("num_rounds") or EVAL_NUM_ROUNDS)


def decisions_by_round(rows: Sequence[Mapping[str, Any]]) -> dict[int, Pairs]:
    grouped: dict[int, Pairs] = defaultdict(list)
    for row in rows:
        decision = AgentDecision(
            signal=SignalType(str(row["signal"]).lower()),
            confidence=float(row["confidence"] or 0.0),
        )
        grouped[int(row["round"])].append((str(row["agent_id"]), decision))
    return dict(grouped)


def valid_votes(pairs: Sequence[tuple[str, AgentDecision]]) -> int:
    return sum(1 for _, decision in pairs if decision.signal is not SignalType.PARSE_ERROR)


def cycle_forecasts(run: CycleRun, by_round: Mapping[int, Pairs], personas: Sequence[AgentPersona]) -> dict[str, float]:
    """The swarm-side forecasters of one cycle (docs/methodology.md §5)."""
    narrators = {p.id for p in personas if p.bracket is BracketType.NARRATORS}
    final = by_round.get(final_round(run.props), [])
    first = by_round.get(1, [])
    out: dict[str, float] = {}
    if valid_votes(final) >= MIN_VALID_VOTES:
        out["swarm"] = net_score(final, personas, weighting="headcount")
        out["swarm_reach"] = net_score(final, personas, weighting="reach")
        others = [pair for pair in final if pair[0] not in narrators]
        out["swarm_ex_narrators"] = net_score(others, personas, weighting="headcount")
        bracket = [pair for pair in final if pair[0] in narrators]
        if valid_votes(bracket) >= MIN_NARRATOR_VOTES:
            out["narrators_only"] = net_score(bracket, personas, weighting="headcount")
    if valid_votes(first) >= MIN_VALID_VOTES:
        out["r1_only"] = net_score(first, personas, weighting="headcount")
    sentiment = run.props.get("overall_sentiment")
    if isinstance(sentiment, int | float) and not isinstance(sentiment, bool):
        out["orchestrator"] = float(sentiment)
    return out


@dataclass(frozen=True)
class ForecastRow:
    event_id: str
    variant: Variant
    forecaster: str
    seed: int
    score: float


@dataclass(frozen=True)
class EvalInputs:
    events: Sequence[EvalEvent]
    labels: Mapping[str, OutcomeLabel]
    rows: Sequence[ForecastRow]
    probes: Sequence[ProbeRecord]
    report: MatchReport
    labels_sha256: str | None


def collect_eval_inputs(
    read: Read,
    events: Sequence[EvalEvent],
    labels: Mapping[str, OutcomeLabel],
    baselines: Sequence[BaselineRecord],
    probes: Sequence[ProbeRecord],
    personas: Sequence[AgentPersona],
    *,
    labels_sha256: str | None = None,
    base: Mapping[str, Any] | None = None,
) -> EvalInputs:
    eval_arms = {name: arm for name, arm in ARMS.items() if arm.study == "p77"}
    cycles = read(CYCLES_QUERY, {"tags": [arm.tag for arm in eval_arms.values()]})
    runs, report = match_cycles(cycles, events, eval_arms, base=base)
    rows: list[ForecastRow] = []
    for run in runs.values():
        final = final_round(run.props)
        decision_rows = read(DECISIONS_QUERY, {"cycle_id": run.cycle_id, "rounds": sorted({1, final})})
        forecasts = cycle_forecasts(run, decisions_by_round(decision_rows), personas)
        stored = run.props.get(f"r{final}_net_score_headcount")
        if isinstance(stored, float) and "swarm" in forecasts and abs(stored - forecasts["swarm"]) > METRIC_TOLERANCE:
            report.warnings["net score differs from the stored metric"] += 1
        if "swarm" not in forecasts:
            report.warnings["final round below 50 valid votes"] += 1
        rows.extend(
            ForecastRow(run.event_id, run.arm.variant, name, run.seed, value) for name, value in forecasts.items()
        )
    for record in baselines:
        if record.n_valid >= min_valid_baseline(record):
            rows.append(ForecastRow(record.event_id, record.variant, record.kind, record.seed, record.score))
        else:
            report.excluded[f"{record.kind}: too few valid samples"] += 1
    return EvalInputs(events, labels, rows, probes, report, labels_sha256)


def forecaster_scores(
    rows: Sequence[ForecastRow],
    forecaster: str,
    *,
    variant: Variant = "named",
    seed: int | None = None,
) -> dict[str, float]:
    """Per-event score of one forecaster: the mean over its seeds (or one seed)."""
    return mean_by_event(
        (r.event_id, r.score)
        for r in rows
        if r.forecaster == forecaster and r.variant == variant and (seed is None or r.seed == seed)
    )


def main_table(
    rows: Sequence[ForecastRow],
    labels: Mapping[str, OutcomeLabel],
    horizon: Horizon,
    *,
    deadband: float,
) -> str:
    body: list[list[str]] = []
    for name in FORECASTERS:
        result = score_forecaster(name, forecaster_scores(rows, name), labels, horizon, deadband=deadband)
        body.append(
            [
                name,
                str(result.n_events),
                str(result.n_directional),
                fmt_rate(result.hit_rate, result.hit_ci),
                fmt(result.brier),
                fmt(result.log_loss),
                fmt(result.spearman, "+.2f"),
                fmt(result.accuracy3, ".2f"),
            ]
        )
    header = [
        "forecaster",
        "events",
        "directional",
        "hit rate [95% CI]",
        "Brier",
        "log loss",
        "Spearman rho",
        "3-class acc.",
    ]
    return markdown_table(header, body)


def comparison_table(rows: Sequence[ForecastRow], labels: Mapping[str, OutcomeLabel], horizon: Horizon) -> str:
    swarm = brier_by_event(forecaster_scores(rows, "swarm"), labels, horizon)
    body: list[list[str]] = []
    for other in COMPARED:
        theirs = brier_by_event(forecaster_scores(rows, other), labels, horizon)
        interval = paired_difference(swarm, theirs, rng=boot_rng(f"compare:{horizon}:{other}"))
        body.append(
            [f"swarm - {other}", fmt_interval(interval), str(interval.n_clusters if interval else 0), verdict(interval)]
        )
    return markdown_table(["Brier difference", "mean [95% CI]", "events", "reading"], body)


def leakage_section(inputs: EvalInputs, *, deadband: float) -> str:
    """Post-cutoff split, named vs anonymized, memorization probe (docs/methodology.md §8)."""
    labels, rows = inputs.labels, inputs.rows
    post = {e.event_id for e in inputs.events if e.post_cutoff}
    everything = {e.event_id for e in inputs.events}
    splits = (("post-cutoff", post), ("pre-cutoff", everything - post))
    split_rows: list[list[str]] = []
    for name in LEAKAGE_FORECASTERS:
        scores = forecaster_scores(rows, name)
        for split, ids in splits:
            chosen = {e: s for e, s in scores.items() if e in ids}
            result = score_forecaster(name, chosen, labels, "1d", deadband=deadband)
            split_rows.append(
                [name, split, str(result.n_directional), fmt_rate(result.hit_rate, result.hit_ci), fmt(result.brier)]
            )
    named = forecaster_scores(rows, "swarm", seed=1)
    anon = forecaster_scores(rows, "swarm", variant="anon", seed=1)
    common = sorted(set(named) & set(anon))
    shift = cluster_bootstrap({e: [abs(named[e] - anon[e])] for e in common}, rng=boot_rng("anon:shift"))
    anon_brier = paired_difference(
        brier_by_event({e: anon[e] for e in common}, labels, "1d"),
        brier_by_event({e: named[e] for e in common}, labels, "1d"),
        rng=boot_rng("anon:brier"),
    )
    anon_rows = [
        ["mean |S named - S anonymized|", fmt_interval(shift, ".3f"), str(len(common))],
        ["Brier anonymized - named", fmt_interval(anon_brier), str(anon_brier.n_clusters if anon_brier else 0)],
    ]
    by_event = {p.event_id: p for p in inputs.probes}
    probe_rows: list[list[str]] = []
    for split, ids in splits:
        probed = [by_event[e] for e in sorted(ids) if e in by_event]
        recalled = [p for p in probed if p.recalled]
        correct = [p for p in recalled if p.event_id in labels and p.direction == labels[p.event_id].label_5d]
        probe_rows.append(
            [
                split,
                str(len(probed)),
                fmt(len(recalled) / len(probed) if probed else None, ".2f"),
                fmt(len(correct) / len(recalled) if recalled else None, ".2f"),
            ]
        )
    suspects = sorted(
        p.event_id
        for p in inputs.probes
        if p.recalled and p.event_id in labels and p.direction == labels[p.event_id].label_5d
    )
    clean_scores = {e: s for e, s in forecaster_scores(rows, "swarm").items() if e not in suspects}
    clean = score_forecaster("swarm", clean_scores, labels, "1d", deadband=deadband)
    return "\n".join(
        [
            "### Post-cutoff split (1-day)",
            "",
            markdown_table(["forecaster", "split", "directional", "hit rate [95% CI]", "Brier"], split_rows),
            "### Named vs anonymized (swarm, seed 1)",
            "",
            markdown_table(["comparison", "mean [95% CI]", "events"], anon_rows),
            "### Memorization probe",
            "",
            markdown_table(["split", "probed", "recall rate", "recall accuracy (5-day label)"], probe_rows),
            f"Suspect events (recalled with the correct direction): {', '.join(suspects) or 'none'}. "
            f"Swarm without them: hit rate {fmt_rate(clean.hit_rate, clean.hit_ci)}, "
            f"Brier {fmt(clean.brier)} ({clean.n_directional} directional events).",
            "",
        ]
    )


def build_eval_report(inputs: EvalInputs, *, deadband: float) -> str:
    missing = sorted(e.event_id for e in inputs.events if e.event_id not in inputs.labels)
    swarm_scores = forecaster_scores(inputs.rows, "swarm")
    swarm = score_forecaster("swarm", swarm_scores, inputs.labels, "1d", deadband=deadband)
    advice = advise_g20(swarm_scores, swarm.hit_rate, deadband=deadband)
    return "\n".join(
        [
            "## P7.7 evaluation",
            "",
            f"Labels sha256: {inputs.labels_sha256 or 'n/a'}. "
            f"Events without a label (excluded): {', '.join(missing) or 'none'}.",
            "",
            *inputs.report.lines(),
            "",
            "### 1-day horizon (primary)",
            "",
            main_table(inputs.rows, inputs.labels, "1d", deadband=deadband),
            "### 5-day horizon",
            "",
            main_table(inputs.rows, inputs.labels, "5d", deadband=deadband),
            "### Swarm vs each forecaster (1-day Brier, paired over events)",
            "",
            comparison_table(inputs.rows, inputs.labels, "1d"),
            "### Swarm vs each forecaster (5-day Brier, paired over events)",
            "",
            comparison_table(inputs.rows, inputs.labels, "5d"),
            leakage_section(inputs, deadband=deadband),
            f"G-20 advice: {advice.branch} ({advice.reason}).",
            "",
        ]
    )


def forecast_records(inputs: EvalInputs) -> list[dict[str, object]]:
    events = {e.event_id: e for e in inputs.events}
    records: list[dict[str, object]] = []
    for row in inputs.rows:
        label = inputs.labels.get(row.event_id)
        event = events.get(row.event_id)
        records.append(
            {
                "event_id": row.event_id,
                "variant": row.variant,
                "forecaster": row.forecaster,
                "seed": row.seed,
                "score": row.score,
                "p_up": p_up(row.score),
                "label_1d": label.label_1d if label else None,
                "label_5d": label.label_5d if label else None,
                "abn_ret_1d": label.abn_ret_1d if label else None,
                "abn_ret_5d": label.abn_ret_5d if label else None,
                "post_cutoff": event.post_cutoff if event else None,
            }
        )
    return records


def write_parquet(records: Sequence[Mapping[str, object]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist([dict(record) for record in records]), path)


def reliability_svg(title: str, bins: Sequence[ReliabilityBin]) -> str:
    """A small standalone reliability diagram: forecast P(up) against observed frequency."""
    size, pad = 260, 34
    span = size - 2 * pad

    def x(value: float) -> float:
        return pad + value * span

    def y(value: float) -> float:
        return size - pad - value * span

    points = [(b.mean_p, b.freq, b.n) for b in bins if b.mean_p is not None and b.freq is not None]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(p):.1f},{y(f):.1f}" for i, (p, f, _) in enumerate(points))
    dots = "".join(f'<circle cx="{x(p):.1f}" cy="{y(f):.1f}" r="{2 + n**0.5:.1f}"/>' for p, f, n in points)
    label = escape(title)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" font-family="sans-serif" font-size="10">'
        f"<title>{label}</title>"
        f'<rect width="{size}" height="{size}" fill="white"/>'
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" stroke="#999" '
        'stroke-dasharray="4 3"/>'
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(0)}" stroke="#333"/>'
        f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(0)}" y2="{y(1)}" stroke="#333"/>'
        f'<path d="{path}" fill="none" stroke="#1f6feb" stroke-width="1.5"/>'
        f'<g fill="#1f6feb">{dots}</g>'
        f'<text x="{pad}" y="18">{label}</text>'
        f'<text x="{size / 2}" y="{size - 8}" text-anchor="middle">forecast P(up)</text>'
        f'<text x="12" y="{size / 2}" transform="rotate(-90 12 {size / 2})" '
        'text-anchor="middle">observed frequency</text>'
        "</svg>\n"
    )


def write_outputs(report: str, inputs: EvalInputs, results: Path, *, parquet: bool) -> list[Path]:
    results.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    table = results / "eval_table.md"
    table.write_text(report, encoding="utf-8")
    written.append(table)
    records = forecast_records(inputs)
    jsonl = results / "forecasts.jsonl"
    jsonl.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    written.append(jsonl)
    if parquet:
        target = results / "forecasts.parquet"
        write_parquet(records, target)
        written.append(target)
    for name in RELIABILITY_FORECASTERS:
        scores = forecaster_scores(inputs.rows, name)
        pairs = [
            (p_up(s), inputs.labels[e].label_1d == "up")
            for e, s in scores.items()
            if e in inputs.labels and inputs.labels[e].label_1d != "flat"
        ]
        svg = results / f"reliability_1d_{name}.svg"
        title = f"{name}: 1-day reliability (n={len(pairs)})"
        svg.write_text(reliability_svg(title, reliability_bins(pairs)), encoding="utf-8")
        written.append(svg)
    return written


# --- ablations ------------------------------------------------------------------

ABLATION_METRICS: Final = (
    "net_score",
    "entropy",
    "flip_rate",
    "citation_gini",
    "distinct_peers",
    "brier_1d",
    "seconds",
)
ABLATION_HEADER: Final = [
    "arm",
    "vs",
    "pairs",
    "delta net score",
    "mean abs delta net",
    "lean agrees",
    "delta entropy",
    "delta flips/agent/round",
    "delta citation Gini",
    "delta distinct peers",
    "delta Brier 1d",
    "delta seconds",
]


def pair_metrics(run: CycleRun, score: float | None, labels: Mapping[str, OutcomeLabel]) -> dict[str, float]:
    """Per-cycle outcome metrics of docs/methodology.md §9; absent keys are skipped."""
    props = run.props
    final = final_round(props)
    out: dict[str, float] = {}
    if score is not None:
        out["net_score"] = score
        label = labels.get(run.event_id)
        if label is not None and label.label_1d != "flat":
            out["brier_1d"] = brier(p_up(score), label.label_1d == "up")
    for name, key in (
        ("entropy", f"r{final}_entropy"),
        ("citation_gini", f"r{final}_citation_gini"),
        ("distinct_peers", f"r{final}_distinct_peers_shown"),
        ("seconds", "total_seconds"),
    ):
        value = props.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            out[name] = float(value)
    flips = [props.get(f"r{n}_flips") for n in range(2, final + 1)]
    counts = [float(f) for f in flips if isinstance(f, int | float) and not isinstance(f, bool)]
    agents = props.get("agent_count")
    if final >= 2 and len(counts) == len(flips) and isinstance(agents, int | float) and agents > 0:
        out["flip_rate"] = sum(counts) / float(agents) / (final - 1)
    return out


@dataclass(frozen=True)
class ArmComparison:
    arm: str
    reference: str
    pairs: int
    deltas: Mapping[str, Interval | None]
    abs_shift: Interval | None
    lean_agreement: float | None


def compare_arm(
    arm_metrics: Mapping[tuple[str, int], Mapping[str, float]],
    ref_metrics: Mapping[tuple[str, int], Mapping[str, float]],
    *,
    arm: str,
    reference: str,
    deadband: float,
) -> ArmComparison:
    """Paired (event, seed) differences arm - reference, bootstrapped over events."""
    common = sorted(set(arm_metrics) & set(ref_metrics))
    deltas: dict[str, Interval | None] = {}
    for metric in ABLATION_METRICS:
        clusters: dict[str, list[float]] = defaultdict(list)
        for key in common:
            a, r = arm_metrics[key].get(metric), ref_metrics[key].get(metric)
            if a is not None and r is not None:
                clusters[key[0]].append(a - r)
        deltas[metric] = cluster_bootstrap(clusters, rng=boot_rng(f"ablation:{arm}:{metric}"))
    shifts: dict[str, list[float]] = defaultdict(list)
    agreement: list[bool] = []
    for key in common:
        a, r = arm_metrics[key].get("net_score"), ref_metrics[key].get("net_score")
        if a is None or r is None:
            continue
        shifts[key[0]].append(abs(a - r))
        agreement.append(lean3(a, deadband) == lean3(r, deadband))
    return ArmComparison(
        arm,
        reference,
        len(common),
        deltas,
        cluster_bootstrap(shifts, rng=boot_rng(f"ablation:{arm}:shift")),
        sum(agreement) / len(agreement) if agreement else None,
    )


def within_round3(
    scores: Mapping[tuple[str, int], tuple[float, float]],
    labels: Mapping[str, OutcomeLabel],
    *,
    deadband: float,
) -> ArmComparison:
    """Round 3 against Round 2 inside the same rounds3 cycles (the default-rounds evidence)."""
    second: dict[tuple[str, int], dict[str, float]] = {}
    third: dict[tuple[str, int], dict[str, float]] = {}
    for key, (s2, s3) in scores.items():
        second[key] = {"net_score": s2}
        third[key] = {"net_score": s3}
        label = labels.get(key[0])
        if label is not None and label.label_1d != "flat":
            up = label.label_1d == "up"
            second[key]["brier_1d"] = brier(p_up(s2), up)
            third[key]["brier_1d"] = brier(p_up(s3), up)
    return compare_arm(
        third, second, arm="R3 vs R2 (rounds3 cycles)", reference="same cycle, Round 2", deadband=deadband
    )


def _ablation_row(c: ArmComparison) -> list[str]:
    d = c.deltas
    return [
        c.arm,
        c.reference,
        str(c.pairs),
        fmt_interval(d.get("net_score")),
        fmt_interval(c.abs_shift, ".3f"),
        fmt(c.lean_agreement, ".0%"),
        fmt_interval(d.get("entropy")),
        fmt_interval(d.get("flip_rate")),
        fmt_interval(d.get("citation_gini")),
        fmt_interval(d.get("distinct_peers"), "+.1f"),
        fmt_interval(d.get("brier_1d")),
        fmt_interval(d.get("seconds"), "+.0f"),
    ]


def build_ablation_report(
    comparisons: Sequence[ArmComparison],
    within: ArmComparison | None,
    *,
    missing: Sequence[str],
    report: MatchReport,
) -> str:
    rows = [_ablation_row(c) for c in comparisons]
    if within is not None:
        rows.append(_ablation_row(within))
    g16 = advise_g16(
        within.abs_shift if within else None,
        within.lean_agreement if within else None,
        within.deltas.get("brier_1d") if within else None,
    )
    by_arm = {c.arm: c for c in comparisons}
    candidates: dict[float, tuple[Interval | None, Interval | None]] = {}
    for name, value in (("boost_0", 0.0), ("boost_005", 0.05)):
        comparison = by_arm.get(name)
        if comparison is not None:
            candidates[value] = (comparison.deltas.get("distinct_peers"), comparison.deltas.get("brier_1d"))
    g15 = advise_g15(candidates)
    lines = ["## P7.8 ablations", "", *report.lines(), "", markdown_table(ABLATION_HEADER, rows)]
    if missing:
        lines.append(f"Arms without runs: {', '.join(missing)}.")
    lines += [f"G-16 advice: {g16.branch} ({g16.reason}).", f"G-15 advice: {g15.branch} ({g15.reason}).", ""]
    return "\n".join(lines)


def collect_ablations(
    read: Read,
    events: Sequence[EvalEvent],
    labels: Mapping[str, OutcomeLabel],
    personas: Sequence[AgentPersona],
    *,
    deadband: float,
    base: Mapping[str, Any] | None = None,
) -> str:
    subset = set(ablation_subset([e.event_id for e in events]))
    arms = {name: arm for name, arm in ARMS.items() if arm.study == "p78" or name == "swarm"}
    cycles = read(CYCLES_QUERY, {"tags": [arm.tag for arm in arms.values()]})
    runs, report = match_cycles(cycles, events, arms, base=base)
    metrics: dict[str, dict[tuple[str, int], dict[str, float]]] = defaultdict(dict)
    within: dict[tuple[str, int], tuple[float, float]] = {}
    for (arm_name, event_id, seed), run in sorted(runs.items()):
        if event_id not in subset:
            continue
        final = final_round(run.props)
        rounds = sorted({final, 2} if arm_name == "rounds3" else {final})
        by_round = decisions_by_round(read(DECISIONS_QUERY, {"cycle_id": run.cycle_id, "rounds": rounds}))
        final_pairs = by_round.get(final, [])
        score = (
            net_score(final_pairs, personas, weighting="headcount")
            if valid_votes(final_pairs) >= MIN_VALID_VOTES
            else None
        )
        metrics[arm_name][(event_id, seed)] = pair_metrics(run, score, labels)
        second = by_round.get(2, [])
        if arm_name == "rounds3" and score is not None and valid_votes(second) >= MIN_VALID_VOTES:
            within[(event_id, seed)] = (net_score(second, personas, weighting="headcount"), score)
    comparisons: list[ArmComparison] = []
    for name, arm in arms.items():
        if arm.reference is None or not metrics.get(name):
            continue
        comparisons.append(
            compare_arm(
                metrics[name], metrics.get(arm.reference, {}), arm=name, reference=arm.reference, deadband=deadband
            )
        )
    missing = [
        name
        for name, arm in arms.items()
        if arm.study == "p78"
        and not metrics.get(name)
        and (name != "private_headlines" or private_headlines_available())
    ]
    within_comparison = within_round3(within, labels, deadband=deadband) if within else None
    return build_ablation_report(comparisons, within_comparison, missing=missing, report=report)


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


def _cmd_score(args: argparse.Namespace) -> int:
    if args.parquet and importlib.util.find_spec("pyarrow") is None:
        print("pyarrow is missing: run `uv sync --group eval` (or pass --no-parquet).", file=sys.stderr)
        return 2
    events = read_jsonl(PATHS.events, EvalEvent)
    labels = {label.event_id: label for label in read_jsonl_if_exists(PATHS.labels, OutcomeLabel)}
    labels_sha = _sha256(PATHS.labels.read_bytes()) if PATHS.labels.exists() else None
    baselines = read_jsonl_if_exists(PATHS.baselines, BaselineRecord)
    probes = read_jsonl_if_exists(PATHS.probes, ProbeRecord)
    personas = generate_personas(load_bracket_configs())
    read, close = open_reader()
    try:
        inputs = collect_eval_inputs(
            read,
            events,
            labels,
            baselines,
            probes,
            personas,
            labels_sha256=labels_sha,
            base=registered_simulation(PATHS),
        )
    finally:
        close()
    report = build_eval_report(inputs, deadband=NET_SCORE_DEADBAND)
    written = write_outputs(report, inputs, PATHS.results, parquet=args.parquet)
    print(report)
    for path in written:
        print(f"wrote {path}")
    return 0


def _cmd_ablations(args: argparse.Namespace) -> int:
    events = read_jsonl(PATHS.events, EvalEvent)
    labels = {label.event_id: label for label in read_jsonl_if_exists(PATHS.labels, OutcomeLabel)}
    personas = generate_personas(load_bracket_configs())
    read, close = open_reader()
    try:
        text = collect_ablations(
            read,
            events,
            labels,
            personas,
            deadband=NET_SCORE_DEADBAND,
            base=registered_simulation(PATHS),
        )
    finally:
        close()
    PATHS.results.mkdir(parents=True, exist_ok=True)
    target = PATHS.results / "ablation_table.md"
    target.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote {target}")
    return 0


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
    score = sub.add_parser("score", help="the accuracy table from stored cycles, labels and baselines")
    score.add_argument("--no-parquet", dest="parquet", action="store_false", help="skip eval/results/forecasts.parquet")
    score.set_defaults(func=_cmd_score)
    ablations = sub.add_parser("ablations", help="the ablation table from stored cycles")
    ablations.set_defaults(func=_cmd_ablations)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.func
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
