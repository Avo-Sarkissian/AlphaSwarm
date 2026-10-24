"""Deterministic swarm evidence per holding (docs/DECISIONS.md#adr-grounded-advisory).

The advisory's per-holding signal comes from the final-round agents whose rationale
referenced the company, not from the orchestrator's reading of bracket counts. This
is the only place a swarm entity meets a held ticker: the swarm side resolves
tickers without portfolio data (docs/DECISIONS.md#adr-ticker-resolution), and the
advisory's portfolio-derived aliases are used here only for company entities the
swarm could not resolve.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from alphaswarm.advisory.sector_map import EMPTY_SECTOR_MAP, SectorMap
from alphaswarm.advisory.types import Signal
from alphaswarm.consensus import WEIGHTINGS, Vote, lean_from_score, net_score_votes
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.graph.rows import EvidenceEntityRow, FinalDecisionRow

MIN_SWARM_SUPPORT: Final = 3
_DECIDED: Final = frozenset({"buy", "sell", "hold"})
_TO_SIGNAL: Final[Mapping[str, Signal]] = {"buy": "BUY", "sell": "SELL", "hold": "HOLD"}


@dataclass(frozen=True)
class SwarmEvidence:
    """What the final round says about one held ticker."""

    ticker: str
    support: int  # decided final-round agents that referenced the company
    buy: int
    sell: int
    hold: int
    net_score: float  # headcount S = sum(s * c) / n over supporting agents
    signal: Signal | None  # lean of net_score when support >= MIN_SWARM_SUPPORT
    confidence: float | None  # agreeing agents' confidence / support; None without a signal
    sentiment: float | None  # mean decision sentiment of supporting agents
    agent_ids: tuple[str, ...]


def _vote(row: FinalDecisionRow) -> Vote:
    return Vote(
        agent_id=row["agent_id"],
        bracket=row["bracket"],
        signal=SignalType(row["signal"]),
        confidence=float(row["confidence"]),
        reach=float(row["reach"]),
    )


def _held_ticker(entity: EvidenceEntityRow, held: Collection[str], sector_map: SectorMap) -> str | None:
    ticker = entity["ticker"]
    if ticker is not None:
        return ticker.upper() if ticker.upper() in held else None
    if entity["type"] != "company":
        return None
    return sector_map.resolve_ticker(entity["name"], held)


def _evidence(ticker: str, rows: Sequence[FinalDecisionRow]) -> SwarmEvidence:
    votes = [_vote(row) for row in rows]
    support = len(votes)
    counts = Counter(v.signal for v in votes)
    net = net_score_votes(votes, weighting="headcount")
    signal: Signal | None = None
    confidence: float | None = None
    if support >= MIN_SWARM_SUPPORT:
        lean = lean_from_score(net)
        signal = _TO_SIGNAL[lean]
        agreeing = sum(v.confidence for v in votes if v.signal.value == lean)
        confidence = round(agreeing / support, 4)
    return SwarmEvidence(
        ticker=ticker,
        support=support,
        buy=counts[SignalType.BUY],
        sell=counts[SignalType.SELL],
        hold=counts[SignalType.HOLD],
        net_score=round(net, 6),
        signal=signal,
        confidence=confidence,
        sentiment=round(sum(float(r["sentiment"]) for r in rows) / support, 4),
        agent_ids=tuple(sorted(r["agent_id"] for r in rows)),
    )


def compute_swarm_evidence(
    rows: Sequence[FinalDecisionRow],
    held: Collection[str],
    *,
    sector_map: SectorMap = EMPTY_SECTOR_MAP,
) -> dict[str, SwarmEvidence]:
    """Held ticker (upper case) -> evidence, for tickers at least one agent referenced."""
    held_upper = frozenset(t.strip().upper() for t in held)
    supporters: dict[str, dict[str, FinalDecisionRow]] = {}
    for row in rows:
        if row["signal"] not in _DECIDED:
            continue
        for entity in row["entities"]:
            ticker = _held_ticker(entity, held_upper, sector_map)
            if ticker is not None:
                supporters.setdefault(ticker, {})[row["agent_id"]] = row
    return {ticker: _evidence(ticker, list(agents.values())) for ticker, agents in sorted(supporters.items())}


def swarm_consensus_summary(rows: Sequence[FinalDecisionRow]) -> str:
    """One line for the advisory prompt: the final round's net score under every weighting."""
    votes = [_vote(row) for row in rows if row["signal"] in _DECIDED]
    if not votes:
        return "no decided agents in the final round"
    scores = {w: net_score_votes(votes, weighting=w) for w in WEIGHTINGS}
    lean = _TO_SIGNAL[lean_from_score(scores["headcount"])]
    return (
        f"{lean} (net score {scores['headcount']:+.2f} headcount, "
        f"{scores['reach']:+.2f} reach-weighted, {scores['bracket_equal']:+.2f} bracket-equal; "
        f"{len(votes)} decided agents)"
    )
