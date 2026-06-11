"""Compare per-cycle metrics across simulation runs (A/B analysis).

Reads the flat metrics stamped onto Cycle nodes by run_simulation
(write_cycle_metrics) and prints a side-by-side table — the measurement
half of every experiment in the improvement plan (num_rounds, peer
diversity, composition, NUM_PARALLEL, worker model).

Usage:
    uv run python scripts/compare_cycles.py            # all metric-stamped cycles
    uv run python scripts/compare_cycles.py --limit 5  # most recent 5
"""

from __future__ import annotations

import argparse

from neo4j import GraphDatabase

from alphaswarm.config import AppSettings

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Max cycles to show")
    args = parser.parse_args()

    settings = AppSettings()
    driver = GraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.username, settings.neo4j.password),
    )
    with driver.session(database=settings.neo4j.database) as session:
        rows = session.run(
            """
            MATCH (c:Cycle)
            WHERE c.metrics_recorded_at IS NOT NULL
            RETURN c
            ORDER BY c.created_at DESC
            LIMIT $limit
            """,
            limit=args.limit,
        ).data()
    driver.close()

    if not rows:
        print("No metric-stamped cycles found. Run a simulation first — metrics")
        print("are written at cycle completion (feat(metrics) commit onward).")
        return

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

    widths = [max(len(r[i]) for r in [header, *table]) for i in range(len(header))]
    for r in [header, *table]:
        print("  ".join(cell.ljust(w) for cell, w in zip(r, widths)))

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


if __name__ == "__main__":
    main()
