"""Per-round peer exposure report for one or more cycles (peer-selection before/after).

Reads the r{n}_exposure_* / r{n}_readers_seeing_* / r{n}_distinct_peers_shown
metric keys that run_simulation stamps on the Cycle node, adds CITED counts
per bracket, prints the cycle's effective peer knobs (so a before/after pair
shows it shared one configuration), and checks the exposure invariant from
docs/DECISIONS.md#adr-diverse-peer-context: no bracket above 35% of a round's
peer slots, and every bracket seen by at least 15% of readers.

Usage:
    uv run python scripts/peer_exposure.py --cycle <cycle_id> [--cycle <cycle_id> ...]
    uv run python scripts/peer_exposure.py --cycle <cycle_id> --markdown   # paste-ready tables
    uv run python scripts/peer_exposure.py --cycle <cycle_id> --check      # exit 1 on violation

Exit codes: 0 report printed (and every round passed when --check is given);
1 --check found a violation; 2 a cycle is missing or carries no exposure keys.
Read-only: the script never writes to Neo4j.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from alphaswarm.config import DEFAULT_BRACKETS, AppSettings

MAX_SLOT_SHARE = 0.35
MIN_READER_SHARE = 0.15
BRACKETS: tuple[str, ...] = tuple(b.bracket_type.value for b in DEFAULT_BRACKETS)


@dataclass(frozen=True)
class BracketExposure:
    bracket: str
    slots: int
    readers: int
    citations: int


@dataclass(frozen=True)
class RoundExposure:
    round_num: int
    agent_count: int
    distinct_peers: int
    rows: tuple[BracketExposure, ...]

    @property
    def total_slots(self) -> int:
        return sum(r.slots for r in self.rows)

    @property
    def total_citations(self) -> int:
        return sum(r.citations for r in self.rows)

    def slot_share(self, row: BracketExposure) -> float:
        return row.slots / self.total_slots if self.total_slots else 0.0

    def reader_share(self, row: BracketExposure) -> float:
        return row.readers / self.agent_count if self.agent_count else 0.0

    def citation_share(self, row: BracketExposure) -> float:
        return row.citations / self.total_citations if self.total_citations else 0.0

    def passes(self) -> bool:
        return all(
            self.slot_share(r) <= MAX_SLOT_SHARE and self.reader_share(r) >= MIN_READER_SHARE
            for r in self.rows
        )


def exposure_rounds(
    props: Mapping[str, Any], citations: Mapping[int, Mapping[str, int]]
) -> list[RoundExposure]:
    """Build one RoundExposure per peer round present in the cycle's metric keys."""
    agent_count = int(props.get("agent_count") or 100)
    rounds: list[RoundExposure] = []
    for n in (2, 3):
        if f"r{n}_distinct_peers_shown" not in props:
            continue
        cited = citations.get(n, {})
        rows = tuple(
            BracketExposure(
                bracket=b,
                slots=int(props.get(f"r{n}_exposure_{b}", 0)),
                readers=int(props.get(f"r{n}_readers_seeing_{b}", 0)),
                citations=int(cited.get(b, 0)),
            )
            for b in BRACKETS
        )
        rounds.append(
            RoundExposure(
                round_num=n,
                agent_count=agent_count,
                distinct_peers=int(props[f"r{n}_distinct_peers_shown"]),
                rows=rows,
            )
        )
    return rounds


def format_round(rnd: RoundExposure, *, markdown: bool) -> str:
    """Render one round as a plain or markdown table plus a verdict line."""
    header = ["bracket", "slots", "slot %", "readers %", "citations %"]
    body = [
        [
            r.bracket,
            str(r.slots),
            f"{rnd.slot_share(r):.1%}",
            f"{rnd.reader_share(r):.0%}",
            f"{rnd.citation_share(r):.1%}",
        ]
        for r in rnd.rows
    ]
    max_slots = max(rnd.slot_share(r) for r in rnd.rows)
    min_readers = min(rnd.reader_share(r) for r in rnd.rows)
    verdict = (
        f"R{rnd.round_num}: distinct peers shown {rnd.distinct_peers}/{rnd.agent_count}; "
        f"max slot share {max_slots:.1%} (limit {MAX_SLOT_SHARE:.0%}); "
        f"min readers {min_readers:.0%} (limit {MIN_READER_SHARE:.0%}) -> "
        f"{'PASS' if rnd.passes() else 'FAIL'}"
    )
    if markdown:
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        # GFM folds a line that directly follows a table into the table, so the
        # verdict and the next block each start after a blank line.
        return "\n".join([*lines, "", verdict, ""])
    widths = [max(len(x) for x in col) for col in zip(header, *body, strict=True)]
    lines = [
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in [header, *body]
    ]
    return "\n".join([*lines, verdict])


def _read_cycle(
    session: Any, cycle_id: str
) -> tuple[dict[str, Any] | None, dict[int, dict[str, int]]]:
    record = session.run(
        "MATCH (c:Cycle {cycle_id: $cycle_id}) RETURN properties(c) AS props", cycle_id=cycle_id
    ).single()
    if record is None:
        return None, {}
    rows = session.run(
        """
        MATCH (d:Decision {cycle_id: $cycle_id})-[:CITED]->(a:Agent)
        WHERE d.round >= 2
        RETURN d.round AS round_num, a.bracket AS bracket, count(*) AS n
        """,
        cycle_id=cycle_id,
    ).data()
    citations: dict[int, dict[str, int]] = {}
    for row in rows:
        citations.setdefault(int(row["round_num"]), {})[str(row["bracket"])] = int(row["n"])
    return dict(record["props"]), citations


# (label, cycle metric key) for the effective peer knobs printed under each header.
PEER_KNOBS: tuple[tuple[str, str], ...] = (
    ("limit", "peer_limit"),
    ("min_brackets", "peer_min_brackets"),
    ("bracket_cap", "peer_bracket_cap"),
    ("personal_boost", "peer_personal_boost"),
    ("budget_chars", "peer_budget_chars"),
    ("seed_source", "peer_seed_source"),
)


def _cycle_header(cycle_id: str, props: Mapping[str, Any]) -> str:
    """Heading line plus the effective peer knobs ("-" when the cycle lacks a key)."""
    git_sha = str(props.get("git_sha") or "")[:8] or "-"
    knobs = " ".join(f"{label}={props.get(key, '-')}" for label, key in PEER_KNOBS)
    return (
        f"\n## {cycle_id}: peer_selection_version={props.get('peer_selection_version', '-')}"
        f" mode={props.get('inference_mode', '-')}"
        f" worker={props.get('worker_model', '-')} git={git_sha}"
        f" parse_errors r2={props.get('r2_parse_errors', '-')}"
        f" r3={props.get('r3_parse_errors', '-')}"
        f"\npeers: {knobs}\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cycle", action="append", required=True, help="cycle id (repeatable)")
    parser.add_argument("--markdown", action="store_true", help="print markdown tables")
    parser.add_argument("--check", action="store_true", help="exit 1 if any round fails")
    args = parser.parse_args(argv)

    from neo4j import GraphDatabase

    settings = AppSettings()
    driver = GraphDatabase.driver(
        settings.neo4j.uri, auth=(settings.neo4j.username, settings.neo4j.require_password())
    )
    failed = False
    try:
        with driver.session(database=settings.neo4j.database) as session:
            for cycle_id in args.cycle:
                props, citations = _read_cycle(session, cycle_id)
                rounds = exposure_rounds(props, citations) if props is not None else []
                if props is None or not rounds:
                    print(f"{cycle_id}: missing, or no exposure metric keys", file=sys.stderr)
                    return 2
                print(_cycle_header(cycle_id, props))
                for rnd in rounds:
                    print(format_round(rnd, markdown=args.markdown))
                    failed = failed or not rnd.passes()
    finally:
        driver.close()
    return 1 if (args.check and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
