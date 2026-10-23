"""Pure influence and shock-impact maths: no I/O, no graph imports.

The graph modules call these functions; the row types defined here are
re-exported by alphaswarm.graph.rows (docs/DECISIONS.md#adr-neo4j-schema).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Final, TypedDict

from alphaswarm.personas import BRACKET_DISPLAY_NAMES, bracket_sort_key

_TIE_ORDER: Final = ("BUY", "SELL", "HOLD")


class ShockComparisonRow(TypedDict):
    """One agent valid on both sides of the shock; signals upper-case."""

    agent_id: str
    bracket: str
    pre_signal: str
    post_signal: str
    shock_round: int
    shock_text: str


class PivotAgentRow(TypedDict):
    agent_id: str
    pre_signal: str
    post_signal: str


class BracketPivotRow(TypedDict):
    bracket: str
    display_name: str
    comparable: int
    pivots: int
    pre_dominant: str | None
    post_dominant: str | None
    pre_buy_pct: float
    post_buy_pct: float
    delta_buy_pct: float
    dominant_arrow: str
    agents: list[PivotAgentRow]


class ShockImpactRow(TypedDict):
    """How the swarm moved across the (earliest) shock."""

    shock_text: str
    injected_before_round: int
    pre_dominant: str | None
    post_dominant: str | None
    pivot_count: int
    pivot_rate: float
    bracket_pivots: list[BracketPivotRow]


def citation_weights(target_ids: Iterable[str], total_agents: int) -> dict[str, float]:
    """INFLUENCED_BY weight per cited agent (docs/DECISIONS.md#p8-d-01).

    *target_ids* holds the cited agent of every distinct (citing, cited) pair;
    the weight is the number of distinct citers divided by the active agents.
    Callers skip rounds with no active agents before calling.
    """
    if total_agents <= 0:
        raise ValueError(f"total_agents must be positive, got {total_agents}")
    counts: Counter[str] = Counter(target_ids)
    return {agent_id: count / total_agents for agent_id, count in counts.items()}


def majority(signals: Sequence[str]) -> str | None:
    """Most common of BUY/SELL/HOLD; ties BUY > SELL > HOLD; None when empty."""
    counts = dict.fromkeys(_TIE_ORDER, 0)
    for signal in signals:
        if signal in counts:
            counts[signal] += 1
    if not any(counts.values()):
        return None
    best = max(counts.values())
    return next(sig for sig in _TIE_ORDER if counts[sig] == best)


def aggregate_shock_impact(rows: Sequence[ShockComparisonRow]) -> ShockImpactRow:
    """Aggregate per-agent (pre, post) rows into a ShockImpactRow; zero-filled when empty."""
    if not rows:
        return ShockImpactRow(
            shock_text="",
            injected_before_round=0,
            pre_dominant=None,
            post_dominant=None,
            pivot_count=0,
            pivot_rate=0.0,
            bracket_pivots=[],
        )
    by_bracket: dict[str, list[ShockComparisonRow]] = {}
    for row in rows:
        by_bracket.setdefault(row["bracket"], []).append(row)
    bracket_pivots: list[BracketPivotRow] = []
    for bracket in sorted(by_bracket, key=bracket_sort_key):
        members = by_bracket[bracket]
        pre = [r["pre_signal"] for r in members]
        post = [r["post_signal"] for r in members]
        pivoted = [r for r in members if r["pre_signal"] != r["post_signal"]]
        pre_buy_pct = pre.count("BUY") / len(members) * 100
        post_buy_pct = post.count("BUY") / len(members) * 100
        delta = post_buy_pct - pre_buy_pct
        bracket_pivots.append(
            BracketPivotRow(
                bracket=bracket,
                display_name=BRACKET_DISPLAY_NAMES.get(bracket, bracket),
                comparable=len(members),
                pivots=len(pivoted),
                pre_dominant=majority(pre),
                post_dominant=majority(post),
                pre_buy_pct=pre_buy_pct,
                post_buy_pct=post_buy_pct,
                delta_buy_pct=delta,
                # The arrow glyph stays in the row until the templates own presentation.
                dominant_arrow="▲" if delta > 0 else "▼" if delta < 0 else "·",
                agents=[
                    PivotAgentRow(
                        agent_id=r["agent_id"],
                        pre_signal=r["pre_signal"],
                        post_signal=r["post_signal"],
                    )
                    for r in pivoted
                ],
            )
        )
    pivot_count = sum(1 for r in rows if r["pre_signal"] != r["post_signal"])
    return ShockImpactRow(
        shock_text=rows[0]["shock_text"],
        injected_before_round=rows[0]["shock_round"],
        pre_dominant=majority([r["pre_signal"] for r in rows]),
        post_dominant=majority([r["post_signal"] for r in rows]),
        pivot_count=pivot_count,
        pivot_rate=pivot_count / len(rows),
        bracket_pivots=bracket_pivots,
    )
