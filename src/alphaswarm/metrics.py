"""Pure measurement functions for cycles and experiments (docs/DECISIONS.md#adr-run-manifest).

Citation validity, exposure-normalised influence, control and treated flips,
the Round 1 retest noise floor, the per-round experiment metric keys and
percentile bootstrap intervals. No I/O: the round runner and the operator
scripts share these functions.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Collection, Mapping, Sequence

from alphaswarm.types import AgentDecision, AgentPersona, SignalType

Pairs = Sequence[tuple[str, AgentDecision]]


def _norm(agent_id: str) -> str:
    return agent_id.strip().lower()


def filter_citations(cited: Sequence[str], shown: Collection[str], self_id: str) -> tuple[list[str], int]:
    """Keep citations of peers the reader was shown, in first-mention order.

    Matching ignores case and surrounding whitespace and returns the shown id.
    Self-citations, duplicates and ids the reader was not shown are invalid;
    the second value counts them.
    """
    canonical = {_norm(peer): peer for peer in shown}
    me = _norm(self_id)
    kept: list[str] = []
    seen: set[str] = set()
    for raw in cited:
        key = _norm(raw)
        if key == me or key in seen or key not in canonical:
            continue
        seen.add(key)
        kept.append(canonical[key])
    return kept, len(cited) - len(kept)


def filter_round_citations(
    decisions: Pairs, exposures: Mapping[str, Sequence[str]]
) -> tuple[tuple[tuple[str, AgentDecision], ...], dict[str, int]]:
    """Apply ``filter_citations`` to a round: decisions with valid citations only,
    plus the invalid count per agent (0 included). Other fields are untouched."""
    filtered: list[tuple[str, AgentDecision]] = []
    invalid: dict[str, int] = {}
    for agent_id, decision in decisions:
        kept, dropped = filter_citations(decision.cited_agents, exposures.get(agent_id, ()), agent_id)
        invalid[agent_id] = dropped
        if kept != list(decision.cited_agents):
            decision = decision.model_copy(update={"cited_agents": kept})
        filtered.append((agent_id, decision))
    return tuple(filtered), invalid


def citation_validity_rate(valid: int, invalid: int) -> float | None:
    """Share of citations that named a shown peer; None when there were none."""
    total = valid + invalid
    return valid / total if total else None


def _check_priors(prior_a: float, prior_b: float) -> None:
    if prior_a <= 0 or prior_b <= 0:
        raise ValueError(f"Beta prior parameters must be positive, got {prior_a}, {prior_b}")


def _exposure_counts(exposures: Mapping[str, Sequence[str]], decisions: Pairs) -> tuple[dict[str, int], dict[str, int]]:
    cited_by_reader = {agent_id: set(d.cited_agents) for agent_id, d in decisions}
    shown: dict[str, int] = {}
    cited: dict[str, int] = {}
    for reader, peers in exposures.items():
        reader_cites = cited_by_reader.get(reader, set())
        for peer in set(peers):
            shown[peer] = shown.get(peer, 0) + 1
            if peer in reader_cites:
                cited[peer] = cited.get(peer, 0) + 1
    return shown, cited


def exposure_normalized_influence(
    exposures: Mapping[str, Sequence[str]],
    decisions: Pairs,
    *,
    prior_a: float = 1.0,
    prior_b: float = 1.0,
) -> dict[str, float]:
    """Citation rate given exposure, per shown agent: ``(cited + a) / (shown + a + b)``.

    ``shown`` counts readers whose exposure contained the agent and ``cited``
    those readers whose (already filtered) citations name it. Agents nobody saw
    are left out: the prior alone would rank them above real evidence.
    """
    _check_priors(prior_a, prior_b)
    shown, cited = _exposure_counts(exposures, decisions)
    return {peer: (cited.get(peer, 0) + prior_a) / (n + prior_a + prior_b) for peer, n in sorted(shown.items())}


def bracket_citation_rates(
    exposures: Mapping[str, Sequence[str]],
    decisions: Pairs,
    personas: Sequence[AgentPersona],
    *,
    prior_a: float = 1.0,
    prior_b: float = 1.0,
) -> dict[str, float]:
    """``exposure_normalized_influence`` pooled per bracket (keyed by bracket value)."""
    _check_priors(prior_a, prior_b)
    bracket_of = {p.id: p.bracket.value for p in personas}
    shown, cited = _exposure_counts(exposures, decisions)
    shown_by: dict[str, int] = {}
    cited_by: dict[str, int] = {}
    for peer, n in shown.items():
        bracket = bracket_of.get(peer, "unknown")
        shown_by[bracket] = shown_by.get(bracket, 0) + n
        cited_by[bracket] = cited_by.get(bracket, 0) + cited.get(peer, 0)
    return {bracket: (cited_by[bracket] + prior_a) / (n + prior_a + prior_b) for bracket, n in sorted(shown_by.items())}


def _valid(signal: SignalType | None) -> bool:
    return signal is not None and signal != SignalType.PARSE_ERROR


def split_flips(prev: Pairs, curr: Pairs, group: Collection[str]) -> tuple[int, int]:
    """Signal changes between two rounds as ``(inside group, outside group)``.

    A PARSE_ERROR on either side, or no previous decision, is not a flip.
    """
    before = {agent_id: d.signal for agent_id, d in prev}
    inside = outside = 0
    for agent_id, decision in curr:
        old = before.get(agent_id)
        if not _valid(old) or not _valid(decision.signal) or old == decision.signal:
            continue
        if agent_id in group:
            inside += 1
        else:
            outside += 1
    return inside, outside


def retest_metrics(first: Pairs, second: Pairs) -> dict[str, float | int]:
    """Noise floor between two draws of Round 1: valid pairs, flips and their rate."""
    before = {agent_id: d.signal for agent_id, d in first}
    pairs = flips = 0
    for agent_id, decision in second:
        old = before.get(agent_id)
        if not _valid(old) or not _valid(decision.signal):
            continue
        pairs += 1
        flips += int(old != decision.signal)
    out: dict[str, float | int] = {"r1_retest_pairs": pairs, "r1_retest_flips": flips}
    if pairs:
        out["r1_retest_flip_rate"] = round(flips / pairs, 6)
    return out


def round_experiment_metrics(
    round_num: int,
    *,
    decisions: Pairs,
    prev_decisions: Pairs | None,
    exposures: Mapping[str, Sequence[str]],
    control_ids: Collection[str],
    citations_invalid: Mapping[str, int],
    personas: Sequence[AgentPersona],
    shock_treated_ids: Collection[str] | None = None,
    prior_a: float = 1.0,
    prior_b: float = 1.0,
) -> dict[str, float | int]:
    """The experiment ``r{n}_*`` cycle-metric keys for one round (docs/DECISIONS.md#adr-run-manifest)."""
    n = round_num
    valid = sum(len(d.cited_agents) for _, d in decisions)
    invalid = sum(citations_invalid.values())
    out: dict[str, float | int] = {
        f"r{n}_citations_invalid": invalid,
        f"r{n}_control_agents": len(control_ids),
    }
    rate = citation_validity_rate(valid, invalid)
    if rate is not None:
        out[f"r{n}_citation_validity_rate"] = round(rate, 6)
    if prev_decisions is None or n < 2:
        return out
    control_flips, treated_flips = split_flips(prev_decisions, decisions, control_ids)
    out[f"r{n}_flips_control"] = control_flips
    out[f"r{n}_flips_treated"] = treated_flips
    rates = bracket_citation_rates(exposures, decisions, personas, prior_a=prior_a, prior_b=prior_b)
    for bracket, value in rates.items():
        out[f"r{n}_cite_rate_{bracket}"] = round(value, 6)
    if shock_treated_ids is not None:
        pivots_in, pivots_out = split_flips(prev_decisions, decisions, shock_treated_ids)
        out[f"r{n}_shock_treated_agents"] = len(shock_treated_ids)
        out[f"r{n}_pivots_shock_treated"] = pivots_in
        out[f"r{n}_pivots_shock_untreated"] = pivots_out
    return out


def _check_bootstrap(n_boot: int, alpha: float) -> None:
    if n_boot < 1:
        raise ValueError(f"n_boot must be >= 1, got {n_boot}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")


def _percentile_interval(samples: list[float], alpha: float) -> tuple[float, float]:
    samples.sort()
    last = len(samples) - 1
    return samples[round(alpha / 2 * last)], samples[round((1 - alpha / 2) * last)]


def bootstrap_mean_ci(
    values: Sequence[float], *, rng: random.Random, n_boot: int = 2000, alpha: float = 0.05
) -> tuple[float, float] | None:
    """Percentile bootstrap interval of the mean; None with fewer than two values."""
    _check_bootstrap(n_boot, alpha)
    if len(values) < 2:
        return None
    k = len(values)
    means = [statistics.fmean(rng.choices(values, k=k)) for _ in range(n_boot)]
    return _percentile_interval(means, alpha)


def bootstrap_diff_ci(
    treated: Sequence[float],
    control: Sequence[float],
    *,
    rng: random.Random,
    n_boot: int = 2000,
    alpha: float = 0.05,
) -> tuple[float, float] | None:
    """Percentile interval of ``mean(treated) - mean(control)``, resampling each
    group independently; None when either group has fewer than two values."""
    _check_bootstrap(n_boot, alpha)
    if len(treated) < 2 or len(control) < 2:
        return None
    diffs = [
        statistics.fmean(rng.choices(treated, k=len(treated))) - statistics.fmean(rng.choices(control, k=len(control)))
        for _ in range(n_boot)
    ]
    return _percentile_interval(diffs, alpha)
