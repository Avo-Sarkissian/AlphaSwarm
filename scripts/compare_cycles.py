"""Compare per-cycle metrics across simulation runs (A/B analysis).

Reads the flat metrics and the experiment tag stamped onto Cycle nodes
(write_cycle_metrics, write_run_manifest) and prints a side-by-side table or,
with --group-by, one row per group: the mean of each metric over the group's
cycles and a percentile bootstrap 95% interval (docs/DECISIONS.md#adr-run-manifest).
Only complete cycles are read, by the app's own completeness rule. A missing
metric is skipped, never read as 0; a group with one value shows "[n/a]".

Usage:
    uv run python scripts/compare_cycles.py                         # newest 20 complete cycles
    uv run python scripts/compare_cycles.py --limit 5 --tag p7-3-control
    uv run python scripts/compare_cycles.py --group-by experiment_tag,worker_model
    uv run python scripts/compare_cycles.py --group-by experiment_tag --tag p7-3-control \\
        --metrics r2_flips,r3_flips,r2_citation_validity_rate --markdown
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase

from alphaswarm.graph.rows import _EFFECTIVE_STATUS
from alphaswarm.metrics import bootstrap_mean_ci
from alphaswarm.settings import AppSettings

METRIC_COLS = [
    ("num_rounds", "rounds"),
    ("total_seconds", "total_s"),
    ("r1_seconds", "r1_s"),
    ("r2_seconds", "r2_s"),
    ("r3_seconds", "r3_s"),
    ("narratives_seconds", "narr_s"),
    ("r2_flips", "flips_r2"),
    ("r3_flips", "flips_r3"),
    ("r1_parse_errors", "perr_r1"),
    ("r2_parse_errors", "perr_r2"),
    ("r3_parse_errors", "perr_r3"),
    ("final_buy", "buy"),
    ("final_sell", "sell"),
    ("final_hold", "hold"),
]

DEFAULT_GROUP_METRICS: tuple[str, ...] = (
    "total_seconds",
    "r2_flips",
    "r3_flips",
    "final_buy",
    "final_sell",
    "final_hold",
    "r2_citation_validity_rate",
    "r3_citation_validity_rate",
)
MISSING = "-"

# The cycles the app lists: the same completeness rule as the replay picker and the
# report default, so a failed or cancelled cycle that carries metrics stays out
# (docs/DECISIONS.md#adr-cycle-metrics).
CYCLES_QUERY = f"""
MATCH (c:Cycle)
WHERE {_EFFECTIVE_STATUS} = 'complete'
  AND ($tag IS NULL OR c.experiment_tag = $tag)
RETURN c
ORDER BY c.created_at DESC
LIMIT $limit
"""


@dataclass(frozen=True)
class MetricStat:
    """Mean and bootstrap interval of one metric over one group's cycles."""

    n: int
    mean: float | None
    ci: tuple[float, float] | None


@dataclass(frozen=True)
class GroupSummary:
    """One --group-by row: the group key, its cycle count and per-metric stats."""

    key: tuple[str, ...]
    cycles: int
    stats: dict[str, MetricStat]


def parse_fields(text: str) -> list[str]:
    """Comma-separated names; whitespace and empty entries are dropped."""
    return [part.strip() for part in text.split(",") if part.strip()]


def group_key(cycle: Mapping[str, Any], fields: Sequence[str]) -> tuple[str, ...]:
    """The cycle's value of each field; missing, null or empty reads as "-"."""
    key: list[str] = []
    for field in fields:
        value = cycle.get(field)
        key.append(MISSING if value is None or value == "" else str(value))
    return tuple(key)


def metric_values(cycles: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    """Numeric values of ``key``; missing, null, text and booleans are skipped, never 0."""
    values: list[float] = []
    for cycle in cycles:
        value = cycle.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(float(value))
    return values


def summarize_groups(
    cycles: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    metrics: Sequence[str],
    *,
    rng: random.Random,
    n_boot: int = 2000,
) -> list[GroupSummary]:
    """Group cycles by ``fields`` (rows sorted by key) and summarise each metric."""
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for cycle in cycles:
        groups.setdefault(group_key(cycle, fields), []).append(cycle)
    summaries: list[GroupSummary] = []
    for key in sorted(groups):
        members = groups[key]
        stats: dict[str, MetricStat] = {}
        for metric in metrics:
            values = metric_values(members, metric)
            stats[metric] = MetricStat(
                n=len(values),
                mean=sum(values) / len(values) if values else None,
                ci=bootstrap_mean_ci(values, rng=rng, n_boot=n_boot),
            )
        summaries.append(GroupSummary(key=key, cycles=len(members), stats=stats))
    return summaries


def format_stat(stat: MetricStat) -> str:
    """'mean [low, high]', 'mean [n/a]' for a single value, '-' for none."""
    if stat.mean is None:
        return MISSING
    if stat.ci is None:
        return f"{stat.mean:.3f} [n/a]"
    return f"{stat.mean:.3f} [{stat.ci[0]:.3f}, {stat.ci[1]:.3f}]"


def group_table(summaries: Sequence[GroupSummary], fields: Sequence[str], metrics: Sequence[str]) -> list[list[str]]:
    """Header plus one row per group."""
    rows = [[*fields, "n", *metrics]]
    for summary in summaries:
        rows.append([*summary.key, str(summary.cycles), *(format_stat(summary.stats[m]) for m in metrics)])
    return rows


def render(rows: Sequence[Sequence[str]], *, markdown: bool) -> str:
    """Aligned plain text, or a markdown table for docs/experiments.md."""
    if markdown:
        lines = [
            "| " + " | ".join(rows[0]) + " |",
            "|" + "|".join("---" for _ in rows[0]) + "|",
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines)
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip() for row in rows
    )


def fetch_cycles(session: Any, *, limit: int, tag: str | None) -> list[dict[str, Any]]:
    """Newest complete cycles as records ``{"c": <Cycle properties>}``."""
    return list(session.run(CYCLES_QUERY, limit=limit, tag=tag).data())


def _print_cycle_table(rows: Sequence[Mapping[str, Any]]) -> None:
    """One line per cycle with the METRIC_COLS, then the HOLD share per cycle."""
    header = ["cycle", "seed", *(label for _, label in METRIC_COLS)]
    table: list[list[str]] = []
    for row in rows:
        c = row["c"]
        seed = (c.get("seed_rumor") or "")[:28]
        line = [c.get("cycle_id", "")[:8], seed]
        for key, _label in METRIC_COLS:
            v = c.get(key)
            line.append("-" if v is None else (f"{v:.0f}" if isinstance(v, float) else str(v)))
        table.append(line)
    print(render([header, *table], markdown=False))

    # Convergence read: HOLD share of the final distribution per cycle.
    print()
    for row in rows:
        c = row["c"]
        buy, sell, hold = (c.get("final_buy", 0), c.get("final_sell", 0), c.get("final_hold", 0))
        total = buy + sell + hold
        if total:
            print(
                f"{c.get('cycle_id', '')[:8]}: HOLD share {hold / total:.0%}"
                f"  (>70% across diverse seeds suggests prompt action-bias, not consensus)"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=20, help="Max cycles to read")
    parser.add_argument("--tag", default=None, help="Only cycles with this experiment_tag")
    parser.add_argument(
        "--group-by",
        default=None,
        help="Comma-separated Cycle properties, e.g. experiment_tag,worker_model",
    )
    parser.add_argument(
        "--metrics",
        default=",".join(DEFAULT_GROUP_METRICS),
        help="Comma-separated metric keys summarised by --group-by",
    )
    parser.add_argument("--markdown", action="store_true", help="Print --group-by as markdown")
    parser.add_argument("--n-boot", type=int, default=2000, help="Bootstrap resamples per interval")
    parser.add_argument("--seed", type=int, default=7, help="Bootstrap RNG seed (reproducible intervals)")
    args = parser.parse_args(argv)

    settings = AppSettings()
    driver = GraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.username, settings.neo4j.require_password()),
    )
    try:
        with driver.session(database=settings.neo4j.database) as session:
            rows = fetch_cycles(session, limit=args.limit, tag=args.tag)
    finally:
        driver.close()

    if not rows:
        suffix = f" with tag {args.tag!r}" if args.tag else ""
        print(f"No complete cycles found{suffix}. Run a simulation first.")
        return 0

    if args.group_by:
        fields = parse_fields(args.group_by)
        metrics = parse_fields(args.metrics)
        summaries = summarize_groups(
            [row["c"] for row in rows],
            fields,
            metrics,
            rng=random.Random(args.seed),
            n_boot=args.n_boot,
        )
        print(render(group_table(summaries, fields, metrics), markdown=args.markdown))
        return 0

    _print_cycle_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
