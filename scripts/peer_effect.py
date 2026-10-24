"""Peer-attributable flips, the shock arm, the noise floor and exposure checks.

Reads stored cycles read-only (Decision signal, d.control, d.shock_treated,
d.peer_ids, CITED edges; Cycle run_manifest_json and r1_retest_* metrics) and
prints tables for docs/experiments.md (docs/DECISIONS.md#adr-run-manifest):

  effect         per-bracket flip rate of treated readers minus control readers
  shock          pivot rate of the shock arm minus the rest (shock-split runs)
  noise          Round 1 retest flip rate: the noise floor
  influence      citation rate given exposure (Beta(1, 1) prior) for one round
  exposure-diff  do two cycles show the same readers the same peers?

A flip is a signal change between consecutive rounds; a PARSE_ERROR on either
side, or a missing previous decision, is not an observation. Each cycle gives
one paired difference per bracket (treated minus control, Rounds 2..N pooled);
"diff" is the mean over cycles and, with two or more cycles, the interval is a
percentile bootstrap over cycles, because agents in one cycle influence each
other. With one cycle the interval resamples agents and says "(agents)".
"treated_rate" and "control_rate" are pooled over all cycles. A cycle recorded
before the control holdout existed has no d.control, so all its readers count
as treated. Only complete cycles are read, by the app's own completeness rule.

Usage:
    uv run python scripts/peer_effect.py effect --tag p7-3-control --markdown
    uv run python scripts/peer_effect.py noise --tag p7-3-control
    uv run python scripts/peer_effect.py shock --tag p7-3-shock
    uv run python scripts/peer_effect.py influence --cycle CYCLE_ID --round 2 --top 10
    uv run python scripts/peer_effect.py exposure-diff CYCLE_A CYCLE_B
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase

from alphaswarm.graph.rows import _EFFECTIVE_STATUS
from alphaswarm.metrics import bootstrap_diff_ci, bootstrap_mean_ci, exposure_normalized_influence
from alphaswarm.settings import AppSettings
from alphaswarm.types import AgentDecision, SignalType

PARSE_ERROR = "parse_error"
IDENTITY_FIELDS = frozenset({"cycle_id", "created_at"})
EFFECT_HEADER = [
    "bracket",
    "cycles",
    "n_treated",
    "n_control",
    "treated_rate",
    "control_rate",
    "diff",
    "95% CI",
]
NOISE_HEADER = ["cycles", "pairs", "flips", "mean_flip_rate", "95% CI"]

CYCLES_QUERY = f"""
MATCH (c:Cycle)
WHERE {_EFFECTIVE_STATUS} = 'complete'
  AND ($tag IS NULL OR c.experiment_tag = $tag)
  AND ($cycle_ids IS NULL OR c.cycle_id IN $cycle_ids)
RETURN c
ORDER BY c.created_at
"""

DECISIONS_QUERY = """
MATCH (a:Agent)-[:MADE]->(d:Decision)
WHERE d.cycle_id IN $cycle_ids
OPTIONAL MATCH (d)-[:CITED]->(t:Agent)
RETURN d.cycle_id AS cycle_id, a.id AS agent_id, a.bracket AS bracket,
       d.round AS round_num, d.signal AS signal, d.control AS control,
       d.shock_treated AS shock_treated, d.peer_ids AS peer_ids,
       collect(t.id) AS cited
"""


@dataclass(frozen=True)
class DecisionRow:
    cycle_id: str
    agent_id: str
    bracket: str
    round_num: int
    signal: str  # lowercase SignalType value
    control: bool  # a missing d.control (older cycles) reads as treated
    shock_treated: bool | None  # None outside shock-split rounds
    peer_ids: tuple[str, ...] | None  # None when exposure was not recorded
    cited: tuple[str, ...] = ()


def to_row(record: Mapping[str, Any]) -> DecisionRow:
    """One query record as a DecisionRow."""
    peer_ids = record.get("peer_ids")
    return DecisionRow(
        cycle_id=str(record["cycle_id"]),
        agent_id=str(record["agent_id"]),
        bracket=str(record.get("bracket") or "unknown"),
        round_num=int(record["round_num"]),
        signal=str(record.get("signal") or PARSE_ERROR).lower(),
        control=bool(record.get("control")),
        shock_treated=record.get("shock_treated"),
        peer_ids=tuple(peer_ids) if peer_ids is not None else None,
        cited=tuple(record.get("cited") or ()),
    )


@dataclass(frozen=True)
class FlipObs:
    cycle_id: str
    bracket: str
    round_num: int  # the later round (>= 2)
    control: bool
    shock_treated: bool | None
    flipped: bool


def flip_observations(rows: Sequence[DecisionRow]) -> list[FlipObs]:
    """One observation per (cycle, agent, round >= 2) with valid decisions on both sides."""
    by_key = {(r.cycle_id, r.agent_id, r.round_num): r for r in rows}
    out: list[FlipObs] = []
    for row in sorted(rows, key=lambda r: (r.cycle_id, r.round_num, r.agent_id)):
        prev = by_key.get((row.cycle_id, row.agent_id, row.round_num - 1))
        if row.round_num < 2 or prev is None or PARSE_ERROR in (prev.signal, row.signal):
            continue
        out.append(
            FlipObs(
                cycle_id=row.cycle_id,
                bracket=row.bracket,
                round_num=row.round_num,
                control=row.control,
                shock_treated=row.shock_treated,
                flipped=prev.signal != row.signal,
            )
        )
    return out


@dataclass(frozen=True)
class Effect:
    label: str
    cycles: int  # cycles with both arms observed
    n_treated: int
    n_control: int
    treated_rate: float | None
    control_rate: float | None
    diff: float | None
    ci: tuple[float, float] | None
    ci_basis: str  # "cycles", "agents" or "n/a"


def _rate(obs: Sequence[FlipObs]) -> float | None:
    return sum(o.flipped for o in obs) / len(obs) if obs else None


def arm_effect(
    label: str,
    obs: Sequence[FlipObs],
    is_control: Callable[[FlipObs], bool],
    *,
    rng: random.Random,
    n_boot: int,
) -> Effect:
    """Treated minus control flip rate: the mean of per-cycle paired differences."""
    treated = [o for o in obs if not is_control(o)]
    control = [o for o in obs if is_control(o)]
    by_cycle: dict[str, list[FlipObs]] = {}
    for o in obs:
        by_cycle.setdefault(o.cycle_id, []).append(o)
    diffs: list[float] = []
    for cycle_id in sorted(by_cycle):
        items = by_cycle[cycle_id]
        t_rate = _rate([o for o in items if not is_control(o)])
        c_rate = _rate([o for o in items if is_control(o)])
        if t_rate is not None and c_rate is not None:
            diffs.append(t_rate - c_rate)
    ci: tuple[float, float] | None = None
    basis = "n/a"
    if len(diffs) >= 2:
        ci = bootstrap_mean_ci(diffs, rng=rng, n_boot=n_boot)
        basis = "cycles"
    elif len(diffs) == 1:
        ci = bootstrap_diff_ci(
            [float(o.flipped) for o in treated],
            [float(o.flipped) for o in control],
            rng=rng,
            n_boot=n_boot,
        )
        basis = "agents" if ci is not None else "n/a"
    return Effect(
        label=label,
        cycles=len(diffs),
        n_treated=len(treated),
        n_control=len(control),
        treated_rate=_rate(treated),
        control_rate=_rate(control),
        diff=statistics.fmean(diffs) if diffs else None,
        ci=ci,
        ci_basis=basis,
    )


def bracket_effects(obs: Sequence[FlipObs], *, rng: random.Random, n_boot: int) -> list[Effect]:
    """One Effect per bracket (sorted) plus "all", control = the seeded holdout."""
    effects = [
        arm_effect(b, [o for o in obs if o.bracket == b], lambda o: o.control, rng=rng, n_boot=n_boot)
        for b in sorted({o.bracket for o in obs})
    ]
    effects.append(arm_effect("all", obs, lambda o: o.control, rng=rng, n_boot=n_boot))
    return effects


def shock_effect(obs: Sequence[FlipObs], *, rng: random.Random, n_boot: int) -> Effect:
    """Pivot rate of agents who saw the shock minus those who did not (split rounds only)."""
    in_split = [o for o in obs if o.shock_treated is not None]
    return arm_effect("shock arm", in_split, lambda o: not o.shock_treated, rng=rng, n_boot=n_boot)


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def effect_row(effect: Effect) -> list[str]:
    """Table row; "no control agents" when the control arm is empty."""
    if effect.n_control == 0:
        diff, ci = "no control agents", "-"
    elif effect.diff is None:
        diff, ci = "-", "-"
    else:
        diff = f"{effect.diff:+.3f}"
        ci = "n/a" if effect.ci is None else f"[{effect.ci[0]:+.3f}, {effect.ci[1]:+.3f}] ({effect.ci_basis})"
    return [
        effect.label,
        str(effect.cycles),
        str(effect.n_treated),
        str(effect.n_control),
        _num(effect.treated_rate),
        _num(effect.control_rate),
        diff,
        ci,
    ]


@dataclass(frozen=True)
class NoiseFloor:
    cycles: int
    pairs: int
    flips: int
    mean_rate: float | None
    ci: tuple[float, float] | None


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def noise_floor(cycles: Sequence[Mapping[str, Any]], *, rng: random.Random, n_boot: int) -> NoiseFloor:
    """Mean Round 1 retest flip rate over the cycles that ran a retest."""
    tested = [c for c in cycles if _is_number(c.get("r1_retest_flip_rate"))]
    rates = [float(c["r1_retest_flip_rate"]) for c in tested]
    return NoiseFloor(
        cycles=len(rates),
        pairs=sum(int(c.get("r1_retest_pairs") or 0) for c in tested),
        flips=sum(int(c.get("r1_retest_flips") or 0) for c in tested),
        mean_rate=statistics.fmean(rates) if rates else None,
        ci=bootstrap_mean_ci(rates, rng=rng, n_boot=n_boot),
    )


def noise_row(floor: NoiseFloor) -> list[str]:
    ci = "n/a" if floor.ci is None else f"[{floor.ci[0]:.3f}, {floor.ci[1]:.3f}]"
    return [str(floor.cycles), str(floor.pairs), str(floor.flips), _num(floor.mean_rate), ci]


def influence_table(rows: Sequence[DecisionRow], round_num: int, *, top: int) -> list[tuple[str, str, float, int]]:
    """Agents ranked by citation rate given exposure in ``round_num``.

    Returns ``(agent_id, bracket, rate, times shown)``; ties sort by id.
    """
    in_round = [r for r in rows if r.round_num == round_num and r.peer_ids is not None]
    exposures = {r.agent_id: r.peer_ids or () for r in in_round}
    decisions = [
        (r.agent_id, AgentDecision(signal=SignalType(r.signal), confidence=0.0, cited_agents=list(r.cited)))
        for r in in_round
    ]
    rates = exposure_normalized_influence(exposures, decisions)
    shown = Counter(peer for r in in_round for peer in set(r.peer_ids or ()))
    bracket_of = {r.agent_id: r.bracket for r in rows}
    ranked = sorted(rates.items(), key=lambda item: (-item[1], item[0]))[:top]
    return [(agent, bracket_of.get(agent, "unknown"), rate, shown[agent]) for agent, rate in ranked]


@dataclass(frozen=True)
class ExposureMatch:
    round_num: int
    readers: int
    identical: int


def exposure_match(rows_a: Sequence[DecisionRow], rows_b: Sequence[DecisionRow]) -> list[ExposureMatch]:
    """Per round >= 2: readers with recorded exposure in both cycles, and how many match exactly."""
    a = {(r.agent_id, r.round_num): r.peer_ids for r in rows_a if r.round_num >= 2 and r.peer_ids is not None}
    b = {(r.agent_id, r.round_num): r.peer_ids for r in rows_b if r.round_num >= 2 and r.peer_ids is not None}
    out: list[ExposureMatch] = []
    for round_num in sorted({key[1] for key in a} & {key[1] for key in b}):
        keys = [key for key in a if key[1] == round_num and key in b]
        out.append(ExposureMatch(round_num, len(keys), sum(a[k] == b[k] for k in keys)))
    return out


def failed_round1(rows: Sequence[DecisionRow]) -> frozenset[str]:
    """Agents whose Round 1 decision was a PARSE_ERROR (Round 2 peers depend on this set)."""
    return frozenset(r.agent_id for r in rows if r.round_num == 1 and r.signal == PARSE_ERROR)


def manifest_diff(a: str | None, b: str | None) -> list[str]:
    """Manifest fields (and simulation knobs) whose values differ; identity fields excluded."""
    if a is None or b is None:
        return ["<manifest missing>"]
    left, right = json.loads(a), json.loads(b)
    diffs: list[str] = []
    for key in sorted(set(left) | set(right)):
        if key in IDENTITY_FIELDS:
            continue
        lv, rv = left.get(key), right.get(key)
        if key == "simulation" and isinstance(lv, dict) and isinstance(rv, dict):
            diffs.extend(f"simulation.{k}" for k in sorted(set(lv) | set(rv)) if lv.get(k) != rv.get(k))
        elif lv != rv:
            diffs.append(key)
    return diffs


def fetch_cycles(session: Any, *, tag: str | None, cycle_ids: Sequence[str] | None) -> list[dict[str, Any]]:
    """Complete cycles by tag or ids, oldest first, as property maps."""
    records = session.run(CYCLES_QUERY, tag=tag, cycle_ids=list(cycle_ids) if cycle_ids else None).data()
    return [dict(record["c"]) for record in records]


def fetch_decisions(session: Any, cycle_ids: Sequence[str]) -> list[DecisionRow]:
    """Every decision of the given cycles with its exposure, holdout flag and citations."""
    return [to_row(record) for record in session.run(DECISIONS_QUERY, cycle_ids=list(cycle_ids)).data()]


def render(rows: Sequence[Sequence[str]], *, markdown: bool) -> str:
    """Aligned plain text, or a markdown table for docs/experiments.md."""
    if markdown:
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join("---" for _ in rows[0]) + "|"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines)
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip() for row in rows
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("effect", "shock", "noise"):
        cmd = sub.add_parser(name, help=f"{name} table over a tag or explicit cycles")
        which = cmd.add_mutually_exclusive_group(required=True)
        which.add_argument("--tag", help="experiment_tag of the cycles to read")
        which.add_argument("--cycle", action="append", dest="cycles", help="cycle id (repeatable)")
        cmd.add_argument("--markdown", action="store_true")
        cmd.add_argument("--n-boot", type=int, default=2000)
        cmd.add_argument("--seed", type=int, default=7, help="bootstrap RNG seed")
    influence = sub.add_parser("influence", help="citation rate given exposure for one cycle")
    influence.add_argument("--cycle", required=True)
    influence.add_argument("--round", type=int, default=2, dest="round_num")
    influence.add_argument("--top", type=int, default=10)
    influence.add_argument("--markdown", action="store_true")
    diff = sub.add_parser("exposure-diff", help="compare the peers two cycles showed")
    diff.add_argument("cycle_a")
    diff.add_argument("cycle_b")
    return parser


def _missing(wanted: Sequence[str], cycles: Sequence[Mapping[str, Any]]) -> list[str]:
    found = {c.get("cycle_id") for c in cycles}
    return [cycle_id for cycle_id in wanted if cycle_id not in found]


def run_command(args: argparse.Namespace, session: Any) -> int:
    """Run one subcommand against an open session; 2 when a cycle is missing."""
    if args.command == "exposure-diff":
        wanted = [args.cycle_a, args.cycle_b]
        cycles = fetch_cycles(session, tag=None, cycle_ids=wanted)
        if missing := _missing(wanted, cycles):
            print(f"cycle not found or not complete: {', '.join(missing)}", file=sys.stderr)
            return 2
        by_id = {c["cycle_id"]: c for c in cycles}
        rows = fetch_decisions(session, wanted)
        rows_a = [r for r in rows if r.cycle_id == args.cycle_a]
        rows_b = [r for r in rows if r.cycle_id == args.cycle_b]
        for match in exposure_match(rows_a, rows_b):
            print(f"round {match.round_num}: {match.identical}/{match.readers} readers shown identical peers")
        same = failed_round1(rows_a) == failed_round1(rows_b)
        print(f"round 1 PARSE_ERROR sets identical: {'yes' if same else 'no'}")
        fields = manifest_diff(
            by_id[args.cycle_a].get("run_manifest_json"), by_id[args.cycle_b].get("run_manifest_json")
        )
        print("manifest fields that differ: " + (", ".join(fields) if fields else "none"))
        return 0
    if args.command == "influence":
        if _missing([args.cycle], fetch_cycles(session, tag=None, cycle_ids=[args.cycle])):
            print(f"cycle not found or not complete: {args.cycle}", file=sys.stderr)
            return 2
        table = influence_table(fetch_decisions(session, [args.cycle]), args.round_num, top=args.top)
        rows = [
            ["agent", "bracket", "cite_rate_given_exposure", "times_shown"],
            *([agent, bracket, f"{rate:.3f}", str(n)] for agent, bracket, rate, n in table),
        ]
        print(render(rows, markdown=args.markdown))
        return 0
    cycles = fetch_cycles(session, tag=args.tag, cycle_ids=args.cycles)
    if args.cycles and (missing := _missing(args.cycles, cycles)):
        print(f"cycle not found or not complete: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not cycles:
        print("no complete cycles match", file=sys.stderr)
        return 2
    rng = random.Random(args.seed)
    if args.command == "noise":
        floor = noise_floor(cycles, rng=rng, n_boot=args.n_boot)
        print(render([NOISE_HEADER, noise_row(floor)], markdown=args.markdown))
        return 0
    obs = flip_observations(fetch_decisions(session, [c["cycle_id"] for c in cycles]))
    effects = (
        bracket_effects(obs, rng=rng, n_boot=args.n_boot)
        if args.command == "effect"
        else [shock_effect(obs, rng=rng, n_boot=args.n_boot)]
    )
    print(render([EFFECT_HEADER, *(effect_row(e) for e in effects)], markdown=args.markdown))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = AppSettings()
    driver = GraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.username, settings.neo4j.require_password()),
    )
    try:
        with driver.session(database=settings.neo4j.database) as session:
            return run_command(args, session)
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
