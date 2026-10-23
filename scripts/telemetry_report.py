"""Read-only telemetry report over cycle metrics (performance experiments).

Usage:
    uv run python scripts/telemetry_report.py rows --cycle ID [--cycle ID ...] [--label A0] [--markdown]
    uv run python scripts/telemetry_report.py ab --pair SEED:BEFORE_ID:AFTER_ID [--pair ...] [--markdown]
    uv run python scripts/telemetry_report.py rationales --cycle ID [--round N] [--sample 10] [--rng-seed 7]

Reads Cycle and Decision nodes from the configured Neo4j and never writes.
The tables go into docs/experiments.md; the decision rules are documented there.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

TV_MEAN_MAX: Final = 0.15
TV_SEED_MAX: Final = 0.25
PREFILL_DROP_MIN_PCT: Final = 10.0
RATIONALE_CHAR_CAP: Final = 280
SIGNALS: Final = ("buy", "sell", "hold")
_TERMINAL: Final = (".", "!", "?", '"', "'", ")")

CYCLE_QUERY: Final = "MATCH (c:Cycle {cycle_id: $cycle_id}) RETURN properties(c) AS props"
RATIONALE_QUERY: Final = (
    "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: $round_num}) "
    "WHERE d.signal <> 'parse_error' "
    "RETURN a.id AS agent_id, d.signal AS signal, d.rationale AS rationale ORDER BY a.id"
)

ROW_HEADER: Final = (
    "arm",
    "cycle",
    "round",
    "seconds",
    "p50 ms",
    "p95 ms",
    "prompt tok",
    "completion tok",
    "prefill ms",
    "decode ms",
    "load ms",
    "cold",
    "trunc",
    "ctx",
    "perr",
)


@dataclass(frozen=True)
class RoundRow:
    label: str
    cycle: str
    round_num: int
    seconds: float | None
    p50_ms: float | None
    p95_ms: float | None
    prompt_tokens: float | None
    completion_tokens: float | None
    prefill_ms: float | None
    decode_ms: float | None
    load_ms: float | None
    cold_loads: int | None
    truncations: int | None
    ctx_warnings: int | None
    parse_errors: int | None


def _num_rounds(props: Mapping[str, Any]) -> int:
    value = props.get("num_rounds", 3)
    return int(value) if isinstance(value, (int, float)) else 3


def round_rows(label: str, cycle_id: str, props: Mapping[str, Any]) -> list[RoundRow]:
    """One row per round actually run (num_rounds), from the r{n}_* metric keys."""
    rows: list[RoundRow] = []
    for n in range(1, _num_rounds(props) + 1):
        p = f"r{n}_"
        rows.append(
            RoundRow(
                label=label,
                cycle=cycle_id[:8],
                round_num=n,
                seconds=props.get(f"{p}seconds"),
                p50_ms=props.get(f"{p}latency_p50_ms"),
                p95_ms=props.get(f"{p}latency_p95_ms"),
                prompt_tokens=props.get(f"{p}mean_prompt_tokens"),
                completion_tokens=props.get(f"{p}mean_completion_tokens"),
                prefill_ms=props.get(f"{p}mean_prefill_ms"),
                decode_ms=props.get(f"{p}mean_decode_ms"),
                load_ms=props.get(f"{p}total_load_ms"),
                cold_loads=props.get(f"{p}cold_loads"),
                truncations=props.get(f"{p}truncations"),
                ctx_warnings=props.get(f"{p}ctx_warnings"),
                parse_errors=props.get(f"{p}parse_errors"),
            )
        )
    return rows


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def format_rows(rows: Sequence[RoundRow], *, markdown: bool) -> str:
    """The rows as a markdown table or aligned plain text."""
    table = [list(ROW_HEADER)] + [
        [
            r.label,
            r.cycle,
            str(r.round_num),
            _fmt(r.seconds),
            _fmt(r.p50_ms),
            _fmt(r.p95_ms),
            _fmt(r.prompt_tokens),
            _fmt(r.completion_tokens),
            _fmt(r.prefill_ms),
            _fmt(r.decode_ms),
            _fmt(r.load_ms),
            _fmt(r.cold_loads),
            _fmt(r.truncations),
            _fmt(r.ctx_warnings),
            _fmt(r.parse_errors),
        ]
        for r in rows
    ]
    if markdown:
        lines = ["| " + " | ".join(table[0]) + " |", "|" + "---|" * len(ROW_HEADER)]
        lines += ["| " + " | ".join(cells) + " |" for cells in table[1:]]
        return "\n".join(lines)
    widths = [max(len(row[i]) for row in table) for i in range(len(ROW_HEADER))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in table)


def mean_over_rounds(props: Mapping[str, Any], key: str, rounds: Sequence[int]) -> float | None:
    """Mean of r{n}_{key} over the given rounds that have the key."""
    raw = [props.get(f"r{n}_{key}") for n in rounds]
    values = [float(v) for v in raw if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else None


def cycle_summary(label: str, cycle_id: str, props: Mapping[str, Any]) -> str:
    """One line per cycle: seeding, total, decode share, governor, final distribution, provenance."""
    rounds = list(range(1, _num_rounds(props) + 1))
    prefill = mean_over_rounds(props, "mean_prefill_ms", rounds)
    decode = mean_over_rounds(props, "mean_decode_ms", rounds)
    share = "-"
    if prefill is not None and decode is not None and prefill + decode > 0:
        share = f"{decode / (prefill + decode):.2f}"
    final = "/".join(_fmt(props.get(f"final_{s}")) for s in SIGNALS)
    return (
        f"{label} {cycle_id[:8]}: seed_s={_fmt(props.get('seed_seconds'))} "
        f"total_s={_fmt(props.get('total_seconds'))} decode_share={share} "
        f"throttled_s={_fmt(props.get('governor_throttled_seconds'))} "
        f"paused_s={_fmt(props.get('governor_paused_seconds'))} "
        f"peak_mem={_fmt(props.get('governor_peak_memory_percent'))} final={final} "
        f"worker={props.get('worker_model', '-')} git={props.get('git_sha') or '-'}"
    )


def final_counts(props: Mapping[str, Any]) -> dict[str, int] | None:
    """Final buy/sell/hold counts, or None when any is missing."""
    values = {s: props.get(f"final_{s}") for s in SIGNALS}
    if not all(isinstance(v, int) for v in values.values()):
        return None
    return {s: int(v) for s, v in values.items() if isinstance(v, int)}


def tv_distance(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    """Total-variation distance between two buy/sell/hold distributions."""
    total_a = sum(a.get(s, 0) for s in SIGNALS) or 1
    total_b = sum(b.get(s, 0) for s in SIGNALS) or 1
    return 0.5 * sum(abs(a.get(s, 0) / total_a - b.get(s, 0) / total_b) for s in SIGNALS)


def change_pct(before: float | None, after: float | None) -> float | None:
    """Relative change in percent, or None when it cannot be computed."""
    if before is None or after is None or before == 0:
        return None
    return (after - before) / before * 100


@dataclass(frozen=True)
class AbRow:
    seed: str
    before: str
    after: str
    completion_change_pct: float | None
    prefill_change_pct: float | None
    seconds_change_pct: float | None
    tv: float | None


def ab_row(seed: str, before_id: str, before: Mapping[str, Any], after_id: str, after: Mapping[str, Any]) -> AbRow:
    """Compare one seed's run in two arms. Prefill uses rounds 2+ (round 1 carries live market text)."""
    rounds = list(range(1, min(_num_rounds(before), _num_rounds(after)) + 1))
    later = [n for n in rounds if n >= 2]

    def total_seconds(props: Mapping[str, Any]) -> float | None:
        values = [props.get(f"r{n}_seconds") for n in rounds]
        return float(sum(v for v in values if isinstance(v, (int, float)))) if values else None

    fb, fa = final_counts(before), final_counts(after)
    return AbRow(
        seed=seed,
        before=before_id[:8],
        after=after_id[:8],
        completion_change_pct=change_pct(
            mean_over_rounds(before, "mean_completion_tokens", rounds),
            mean_over_rounds(after, "mean_completion_tokens", rounds),
        ),
        prefill_change_pct=change_pct(
            mean_over_rounds(before, "mean_prefill_ms", later),
            mean_over_rounds(after, "mean_prefill_ms", later),
        ),
        seconds_change_pct=change_pct(total_seconds(before), total_seconds(after)),
        tv=None if fb is None or fa is None else round(tv_distance(fb, fa), 3),
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def ab_verdict(rows: Sequence[AbRow]) -> list[str]:
    """Summary lines with the decision rules of docs/experiments.md."""
    tvs = [r.tv for r in rows if r.tv is not None]
    if tvs:
        mean_tv, max_tv = sum(tvs) / len(tvs), max(tvs)
        state = "UNCHANGED" if mean_tv <= TV_MEAN_MAX and max_tv <= TV_SEED_MAX else "SHIFTED"
        lines = [f"distribution: mean TV {mean_tv:.3f}, max TV {max_tv:.3f} -> {state}"]
    else:
        lines = ["distribution: final counts missing -> UNKNOWN"]
    prefill = _mean([r.prefill_change_pct for r in rows if r.prefill_change_pct is not None])
    if prefill is None:
        lines.append("prefill (R2-R3): no data -> NOT DROPPED")
    else:
        dropped = "DROPPED" if prefill <= -PREFILL_DROP_MIN_PCT else "NOT DROPPED"
        lines.append(f"prefill (R2-R3): mean change {prefill:.1f}% -> {dropped}")
    for name, values in (
        ("completion tokens", [r.completion_change_pct for r in rows if r.completion_change_pct is not None]),
        ("round seconds", [r.seconds_change_pct for r in rows if r.seconds_change_pct is not None]),
    ):
        mean = _mean(values)
        lines.append(f"{name}: mean change {'-' if mean is None else f'{mean:.1f}%'}")
    return lines


def format_ab(rows: Sequence[AbRow], *, markdown: bool) -> str:
    header = ["seed", "before", "after", "completion Δ%", "prefill R2-R3 Δ%", "seconds Δ%", "TV"]
    body = [
        [
            r.seed,
            r.before,
            r.after,
            _fmt(r.completion_change_pct),
            _fmt(r.prefill_change_pct),
            _fmt(r.seconds_change_pct),
            "-" if r.tv is None else f"{r.tv:.3f}",
        ]
        for r in rows
    ]
    if markdown:
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in body])
    return "\n".join("  ".join(row) for row in [header, *body])


@dataclass(frozen=True)
class RationaleStats:
    count: int
    max_chars: int
    over_cap: int
    mean_words: float
    unterminated: int


def rationale_stats(texts: Sequence[str]) -> RationaleStats:
    """Length and cut-off statistics for a set of rationales."""
    stripped = [t.strip() for t in texts]
    return RationaleStats(
        count=len(stripped),
        max_chars=max((len(t) for t in stripped), default=0),
        over_cap=sum(1 for t in stripped if len(t) > RATIONALE_CHAR_CAP),
        mean_words=round(sum(len(t.split()) for t in stripped) / len(stripped), 1) if stripped else 0.0,
        unterminated=sum(1 for t in stripped if t and not t.endswith(_TERMINAL)),
    )


def sample_rows(rows: Sequence[tuple[str, str, str]], k: int, seed: int) -> list[tuple[str, str, str]]:
    """A deterministic sample of k rows (all rows when there are fewer)."""
    return random.Random(seed).sample(list(rows), min(k, len(rows)))


def read_props(session: Any, cycle_id: str) -> dict[str, Any] | None:
    record = session.run(CYCLE_QUERY, cycle_id=cycle_id).single()
    return None if record is None else dict(record["props"])


def read_rationales(session: Any, cycle_id: str, round_num: int) -> list[tuple[str, str, str]]:
    rows = session.run(RATIONALE_QUERY, cycle_id=cycle_id, round_num=round_num).data()
    return [(r["agent_id"], r["signal"], r["rationale"] or "") for r in rows]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rows = sub.add_parser("rows", help="per-round telemetry rows")
    rows.add_argument("--cycle", action="append", required=True)
    rows.add_argument("--label", default="-")
    rows.add_argument("--markdown", action="store_true")
    ab = sub.add_parser("ab", help="compare two arms seed by seed")
    ab.add_argument("--pair", action="append", required=True, help="SEED:BEFORE_ID:AFTER_ID")
    ab.add_argument("--markdown", action="store_true")
    rat = sub.add_parser("rationales", help="sample final-round rationales")
    rat.add_argument("--cycle", required=True)
    rat.add_argument("--round", type=int, default=None)
    rat.add_argument("--sample", type=int, default=10)
    rat.add_argument("--rng-seed", type=int, default=7)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    from neo4j import GraphDatabase

    from alphaswarm.settings import AppSettings

    settings = AppSettings()
    driver = GraphDatabase.driver(settings.neo4j.uri, auth=(settings.neo4j.username, settings.neo4j.require_password()))
    try:
        with driver.session(database=settings.neo4j.database) as session:
            if args.command == "rows":
                all_rows: list[RoundRow] = []
                summaries: list[str] = []
                for cycle_id in args.cycle:
                    props = read_props(session, cycle_id)
                    if props is None:
                        print(f"cycle {cycle_id} not found", file=sys.stderr)
                        return 2
                    all_rows += round_rows(args.label, cycle_id, props)
                    summaries.append(cycle_summary(args.label, cycle_id, props))
                print(format_rows(all_rows, markdown=args.markdown))
                print()
                print("\n".join(summaries))
            elif args.command == "ab":
                ab_rows: list[AbRow] = []
                for pair in args.pair:
                    seed, before_id, after_id = pair.split(":")
                    before, after = read_props(session, before_id), read_props(session, after_id)
                    if before is None or after is None:
                        print(f"pair {pair}: cycle not found", file=sys.stderr)
                        return 2
                    ab_rows.append(ab_row(seed, before_id, before, after_id, after))
                print(format_ab(ab_rows, markdown=args.markdown))
                print()
                print("\n".join(ab_verdict(ab_rows)))
            else:
                props = read_props(session, args.cycle)
                if props is None:
                    print(f"cycle {args.cycle} not found", file=sys.stderr)
                    return 2
                round_num = args.round or _num_rounds(props)
                rows_r = read_rationales(session, args.cycle, round_num)
                stats = rationale_stats([text for _, _, text in rows_r])
                print(
                    f"round {round_num}: n={stats.count} max_chars={stats.max_chars} "
                    f"over_{RATIONALE_CHAR_CAP}={stats.over_cap} mean_words={stats.mean_words} "
                    f"unterminated={stats.unterminated}"
                )
                for agent_id, signal, text in sample_rows(rows_r, args.sample, args.rng_seed):
                    print(f"- {agent_id} {signal.upper()} ({len(text)} chars, {len(text.split())} words): {text}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
