"""Consensus estimators over one round of decisions (docs/DECISIONS.md#adr-consensus-estimators).

Pure functions. Signals map to s = +1 (buy), 0 (hold), -1 (sell) and PARSE_ERROR
is excluded everywhere. The net score is S = sum(w * s * c) / sum(w) under three
weightings:

- headcount: w = 1 for every decided agent;
- reach: w = influence_weight_base, the agent's narrative reach, not capital
  (docs/DECISIONS.md#adr-influence-weight-reach);
- bracket_equal: w = 1 / (decided agents in the agent's bracket), so every bracket
  that decided anything carries the same total weight.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import blake2b
from typing import Final, Literal

from alphaswarm.types import AgentDecision, AgentPersona, SignalType

Weighting = Literal["headcount", "reach", "bracket_equal"]
WEIGHTINGS: Final[tuple[Weighting, ...]] = ("headcount", "reach", "bracket_equal")
NET_SCORE_DEADBAND: Final = 0.15
_DEFAULT_CI_WEIGHTINGS: Final[tuple[Weighting, ...]] = ("headcount",)

_DIRECTION: Final[Mapping[SignalType, int]] = {
    SignalType.BUY: 1,
    SignalType.HOLD: 0,
    SignalType.SELL: -1,
}


@dataclass(frozen=True)
class Vote:
    """One decided agent's input to the estimators (never PARSE_ERROR)."""

    agent_id: str
    bracket: str
    signal: SignalType
    confidence: float
    reach: float


@dataclass(frozen=True)
class Dispersion:
    entropy: float  # Shannon entropy of the buy/sell/hold shares, normalized by ln 3, in [0, 1]
    stdev: float  # population standard deviation of s * c over decided agents


@dataclass(frozen=True)
class ConsensusEstimate:
    weighting: Weighting
    score: float
    ci_low: float | None
    ci_high: float | None
    n: int


def votes_from_decisions(
    decisions: Sequence[tuple[str, AgentDecision]],
    personas: Sequence[AgentPersona],
) -> list[Vote]:
    """Decided agents with a known persona, in input order."""
    by_id = {p.id: p for p in personas}
    votes: list[Vote] = []
    for agent_id, decision in decisions:
        persona = by_id.get(agent_id)
        if persona is None or decision.signal is SignalType.PARSE_ERROR:
            continue
        votes.append(
            Vote(
                agent_id=agent_id,
                bracket=persona.bracket.value,
                signal=decision.signal,
                confidence=float(decision.confidence),
                reach=float(persona.influence_weight_base),
            )
        )
    return votes


def _weights(votes: Sequence[Vote], weighting: Weighting) -> list[float]:
    if weighting == "headcount":
        return [1.0] * len(votes)
    if weighting == "reach":
        return [v.reach for v in votes]
    per_bracket = Counter(v.bracket for v in votes)
    return [1.0 / per_bracket[v.bracket] for v in votes]


def net_score_votes(votes: Sequence[Vote], *, weighting: Weighting) -> float:
    """S = sum(w * s * c) / sum(w); 0.0 when nobody decided."""
    if not votes:
        return 0.0
    weights = _weights(votes, weighting)
    total = sum(weights)
    if total <= 0.0:
        return 0.0
    signed = sum(w * _DIRECTION[v.signal] * v.confidence for w, v in zip(weights, votes, strict=True))
    return signed / total


def net_score(
    decisions: Sequence[tuple[str, AgentDecision]],
    personas: Sequence[AgentPersona],
    *,
    weighting: Weighting,
) -> float:
    return net_score_votes(votes_from_decisions(decisions, personas), weighting=weighting)


def normalized_entropy(counts: Iterable[int]) -> float:
    """Shannon entropy of a buy/sell/hold count vector, divided by ln 3."""
    values = [c for c in counts if c > 0]
    total = sum(values)
    if total == 0:
        return 0.0
    entropy = -sum((c / total) * math.log(c / total) for c in values)
    return entropy / math.log(3)


def _dispersion_of(signals: Sequence[SignalType], confidences: Sequence[float]) -> Dispersion:
    if not signals:
        return Dispersion(entropy=0.0, stdev=0.0)
    counts = Counter(signals)
    values = [_DIRECTION[s] * c for s, c in zip(signals, confidences, strict=True)]
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return Dispersion(entropy=normalized_entropy(counts.values()), stdev=math.sqrt(variance))


def dispersion_votes(votes: Sequence[Vote]) -> Dispersion:
    return _dispersion_of([v.signal for v in votes], [v.confidence for v in votes])


def dispersion(decisions: Sequence[tuple[str, AgentDecision]]) -> Dispersion:
    decided = [d for _, d in decisions if d.signal is not SignalType.PARSE_ERROR]
    return _dispersion_of([d.signal for d in decided], [float(d.confidence) for d in decided])


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def bootstrap_ci_votes(
    votes: Sequence[Vote],
    *,
    weighting: Weighting,
    n_boot: int = 1000,
    alpha: float = 0.05,
    rng: random.Random,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the net score, resampling agents with replacement."""
    if n_boot < 1:
        raise ValueError("n_boot must be at least 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if not votes:
        return (0.0, 0.0)
    n = len(votes)
    stats = sorted(net_score_votes(rng.choices(votes, k=n), weighting=weighting) for _ in range(n_boot))
    return (_quantile(stats, alpha / 2), _quantile(stats, 1 - alpha / 2))


def bootstrap_ci(
    decisions: Sequence[tuple[str, AgentDecision]],
    personas: Sequence[AgentPersona],
    *,
    weighting: Weighting,
    n_boot: int = 1000,
    alpha: float = 0.05,
    rng: random.Random,
) -> tuple[float, float]:
    return bootstrap_ci_votes(
        votes_from_decisions(decisions, personas),
        weighting=weighting,
        n_boot=n_boot,
        alpha=alpha,
        rng=rng,
    )


def estimate_consensus(
    votes: Sequence[Vote],
    *,
    rng: random.Random,
    n_boot: int = 1000,
    alpha: float = 0.05,
    ci_weightings: Collection[Weighting] = _DEFAULT_CI_WEIGHTINGS,
) -> dict[Weighting, ConsensusEstimate]:
    """Net score under every weighting; CI only for ``ci_weightings`` and only with votes."""
    estimates: dict[Weighting, ConsensusEstimate] = {}
    for weighting in WEIGHTINGS:
        ci: tuple[float, float] | None = None
        if votes and weighting in ci_weightings:
            ci = bootstrap_ci_votes(votes, weighting=weighting, n_boot=n_boot, alpha=alpha, rng=rng)
        estimates[weighting] = ConsensusEstimate(
            weighting=weighting,
            score=net_score_votes(votes, weighting=weighting),
            ci_low=ci[0] if ci is not None else None,
            ci_high=ci[1] if ci is not None else None,
            n=len(votes),
        )
    return estimates


def lean_from_score(
    score: float,
    deadband: float = NET_SCORE_DEADBAND,
) -> Literal["buy", "sell", "hold"]:
    """BUY above +deadband, SELL below -deadband, HOLD in between (inclusive)."""
    if score > deadband:
        return "buy"
    if score < -deadband:
        return "sell"
    return "hold"


def consensus_rng(seed: str, round_num: int) -> random.Random:
    """Deterministic bootstrap RNG per (seed, round), same scheme as peers.peer_rng."""
    digest = blake2b(f"{seed}:consensus:{round_num}".encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))
