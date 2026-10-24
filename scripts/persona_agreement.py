"""Round 1 agreement among prompt twins, per experiment tag (read-only).

Prompt twins are agents whose trait-less prompts are identical: same bracket and
round-robin modifier (docs/DECISIONS.md#adr-persona-traits). For every complete
cycle carrying one of the given experiment tags this reads the Round 1 decisions
and reports twin agreement, same-bracket cross-modifier agreement, within-bracket
entropy and between-bracket divergence, with a bootstrap interval over cycles and
the paired change between the first two tags (cycles pair on the seed rumor).

    uv run python scripts/persona_agreement.py --tag p76-baseline --tag p76-traits
"""

from __future__ import annotations

import argparse
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from neo4j import GraphDatabase

from alphaswarm.metrics import (
    bootstrap_mean_ci,
    bracket_divergence,
    cross_group_agreement,
    pairwise_agreement,
    within_bracket_entropy,
)
from alphaswarm.personas import generate_personas, load_bracket_configs, prompt_twin_groups
from alphaswarm.settings import AppSettings
from alphaswarm.types import AgentDecision, AgentPersona, SignalType

FIELDS = ("twin", "cross", "within_entropy", "bracket_tv")

Fetched = tuple[str, str, str, list[tuple[str, AgentDecision]]]


@dataclass(frozen=True)
class CycleStats:
    cycle_id: str
    tag: str
    seed_key: str  # the seed rumor: pairs cycles across tags
    twin: float | None
    cross: float | None
    within_entropy: float | None
    bracket_tv: float | None


def cycle_stats(
    cycle_id: str,
    tag: str,
    seed_key: str,
    decisions: Sequence[tuple[str, AgentDecision]],
    personas: Sequence[AgentPersona],
    groups: Sequence[Sequence[str]],
) -> CycleStats:
    return CycleStats(
        cycle_id=cycle_id,
        tag=tag,
        seed_key=seed_key,
        twin=pairwise_agreement(decisions, groups),
        cross=cross_group_agreement(decisions, groups, personas),
        within_entropy=within_bracket_entropy(decisions, personas),
        bracket_tv=bracket_divergence(decisions, personas),
    )


def _fmt(values: Sequence[float], rng: random.Random) -> str:
    if not values:
        return "-"
    ci = bootstrap_mean_ci(values, rng=rng)
    interval = f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci is not None else ""
    return f"{fmean(values):.3f}{interval}"


def summary_table(stats: Sequence[CycleStats], *, seed: int = 20) -> str:
    """Markdown table: per tag, the mean of each field with a bootstrap interval over cycles."""
    rng = random.Random(seed)
    lines = [
        "| tag | cycles | twin agreement | cross agreement | within-bracket entropy | bracket TV |",
        "|---|---|---|---|---|---|",
    ]
    for tag in dict.fromkeys(s.tag for s in stats):
        rows = [s for s in stats if s.tag == tag]
        cells = [_fmt([v for v in (getattr(r, field) for r in rows) if v is not None], rng) for field in FIELDS]
        lines.append(f"| {tag} | {len(rows)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def paired_drop(
    stats: Sequence[CycleStats], base_tag: str, test_tag: str, field: str = "twin"
) -> tuple[float, int, int] | None:
    """(mean of base - test over paired seeds, seeds where test < base, paired seeds)."""
    base = {s.seed_key: getattr(s, field) for s in stats if s.tag == base_tag}
    test = {s.seed_key: getattr(s, field) for s in stats if s.tag == test_tag}
    diffs = [base[k] - test[k] for k in base if k in test and base[k] is not None and test[k] is not None]
    if not diffs:
        return None
    return fmean(diffs), sum(1 for d in diffs if d > 0), len(diffs)


def decisions_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, AgentDecision]]:
    """Round 1 Decision rows -> (agent_id, decision); unknown signal values are skipped."""
    out: list[tuple[str, AgentDecision]] = []
    for row in rows:
        try:
            signal = SignalType(str(row["signal"]).lower())
        except ValueError:
            continue
        out.append((str(row["agent_id"]), AgentDecision(signal=signal, confidence=float(row["confidence"] or 0.0))))
    return out


def _fetch(tags: Sequence[str]) -> list[Fetched]:
    """Read the tagged complete cycles and their Round 1 decisions from the product Neo4j."""
    settings = AppSettings()
    driver = GraphDatabase.driver(settings.neo4j.uri, auth=(settings.neo4j.username, settings.neo4j.require_password()))
    out: list[Fetched] = []
    try:
        with driver.session(database=settings.neo4j.database) as session:
            cycles = session.run(
                "MATCH (c:Cycle) WHERE c.experiment_tag IN $tags AND c.status = 'complete' "
                "RETURN c.cycle_id AS id, c.experiment_tag AS tag, c.seed_rumor AS seed "
                "ORDER BY c.created_at",
                tags=list(tags),
            ).data()
            for cycle in cycles:
                rows = session.run(
                    "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $id, round: 1}) "
                    "RETURN a.id AS agent_id, d.signal AS signal, d.confidence AS confidence",
                    id=cycle["id"],
                ).data()
                out.append((cycle["id"], cycle["tag"], str(cycle["seed"]), decisions_from_rows(rows)))
    finally:
        driver.close()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", action="append", required=True, help="experiment_tag; repeat for each arm")
    args = parser.parse_args(argv)
    personas = generate_personas(load_bracket_configs())
    groups = prompt_twin_groups(personas)  # trait-less personas: the static-modifier twins
    stats = [cycle_stats(cid, tag, seed, decisions, personas, groups) for cid, tag, seed, decisions in _fetch(args.tag)]
    if not stats:
        print("No complete cycles carry these tags.")
        return 1
    print(summary_table(stats))
    if len(args.tag) >= 2:
        for field in FIELDS:
            drop = paired_drop(stats, args.tag[0], args.tag[1], field)
            if drop is not None:
                print(
                    f"{field}: mean({args.tag[0]} - {args.tag[1]}) = {drop[0]:+.3f}; "
                    f"lower in {args.tag[1]} for {drop[1]}/{drop[2]} seeds"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
