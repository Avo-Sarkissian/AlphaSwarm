"""Peer selection and peer-context rendering for rounds 2..N, in memory and per reader.

Seeded stratified sampling with a per-bracket cap and a shuffle; a reader's exposure
is the list of peers actually rendered into its prompt
(docs/DECISIONS.md#adr-diverse-peer-context).
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.security.sanitize import sanitize_peer_rationale
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.settings import SimulationSettings
    from alphaswarm.types import AgentDecision, AgentPersona

logger = structlog.get_logger(component="peers")


@dataclasses.dataclass(frozen=True)
class PeerContextsResult:
    """Per-reader peer contexts and exposures, aligned with the personas
    (docs/DECISIONS.md#adr-diverse-peer-context)."""

    contexts: tuple[str | None, ...]  # None when no peer line was rendered
    exposures: tuple[tuple[str, ...], ...]  # rendered peer ids in display order; () when none


@dataclasses.dataclass(frozen=True)
class RankedPost:
    """One peer line candidate: a previous-round decision chosen for a reader's feed."""

    post_id: str
    agent_id: str
    bracket: str
    signal: str
    confidence: float
    content: str
    influence_weight: float
    round_num: int


def peer_rng(run_seed: str, reader_id: str, round_num: int) -> random.Random:
    """Per-(run, reader, round) RNG for peer sampling (docs/DECISIONS.md#adr-diverse-peer-context).

    Seeded from blake2b, never the process-salted builtin ``hash()``, so the
    same run seed reproduces the same peer draws in any process.
    ``round_num`` is the round being dispatched (2 for peers drawn from Round 1).
    """
    digest = hashlib.blake2b(f"{run_seed}:{reader_id}:{round_num}".encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _reach(weight: float) -> float:
    """Sampling weight: ``weight`` when finite and positive, else 0.0 (no reach)."""
    return weight if math.isfinite(weight) and weight > 0.0 else 0.0


def _sampling_key(rng: random.Random, weight: float) -> tuple[bool, float]:
    """Efraimidis–Spirakis key; larger wins.

    The float is ``log(u) / w``, the log of ``u ** (1/w)``: sorting by it,
    descending, is weighted sampling without replacement, and the log form
    avoids underflow for small weights. The flag is False for a weight without
    reach (non-finite or not positive), whose float then draws as weight 1:
    such keys sort behind every positive weight, whatever ``u`` is, and stay in
    random order among themselves. One ``u`` is drawn either way.
    """
    u = rng.random()
    while u == 0.0:  # random() is in [0, 1); log(0) is undefined
        u = rng.random()
    if math.isfinite(weight) and weight > 0.0:
        return True, math.log(u) / weight
    return False, math.log(u)


def select_diverse_peers(
    agent_id: str,
    influence_weights: Mapping[str, float],
    personas: Sequence[AgentPersona],
    prev_decisions: Mapping[str, AgentDecision] | None = None,
    *,
    rng: random.Random,
    limit: int = 10,
    min_brackets: int = 4,
    bracket_cap: int = 3,
) -> list[str]:
    """Sample up to ``limit`` peers for one reader (docs/DECISIONS.md#adr-diverse-peer-context).

    Weighted sampling without replacement with Efraimidis–Spirakis keys:

    1. Candidates are every persona except the reader and agents whose
       previous-round decision is PARSE_ERROR.
    2. Phase 1 samples ``min(min_brackets, limit)`` brackets, each weighted by
       the summed weight of its candidates, and takes one peer from each by
       key. A guaranteed slot is therefore a weighted draw over agents that
       skips brackets already chosen, so a small bracket's members do not gain
       per agent merely because the bracket is small.
    3. Phase 2 fills the remaining slots by key, skipping any bracket that
       already holds ``bracket_cap`` peers. The cap is hard: with few eligible
       brackets the result is shorter than ``limit``.
    4. The result is shuffled, so display position carries no authority.

    Production passes ``rng=peer_rng(run_seed, agent_id, round_num)``; the same
    rng state always yields the same list. Non-finite or non-positive weights
    have no reach: such candidates, and brackets with no positive weight, sort
    behind every positive weight (in random order among themselves) and
    nothing raises.

    Raises:
        ValueError: if ``bracket_cap`` is below 1.
    """
    if bracket_cap < 1:
        raise ValueError(f"bracket_cap must be >= 1, got {bracket_cap}")
    parse_error_ids: set[str] = set()
    if prev_decisions is not None:
        parse_error_ids = {aid for aid, dec in prev_decisions.items() if dec.signal == SignalType.PARSE_ERROR}
    candidates = [p for p in personas if p.id != agent_id and p.id not in parse_error_ids]
    if limit <= 0 or not candidates:
        return []

    weight = {p.id: _reach(influence_weights.get(p.id, 0.0)) for p in candidates}
    key = {p.id: _sampling_key(rng, weight[p.id]) for p in candidates}
    bracket_of = {p.id: p.bracket.value for p in candidates}
    members: dict[str, list[str]] = {}
    for p in candidates:
        members.setdefault(p.bracket.value, []).append(p.id)
    bracket_key = {bracket: _sampling_key(rng, sum(weight[pid] for pid in ids)) for bracket, ids in members.items()}

    # Phase 1: sample the guaranteed brackets, one peer from each.
    selected: list[str] = []
    per_bracket = dict.fromkeys(members, 0)
    ranked_brackets = sorted(members, key=lambda b: bracket_key[b], reverse=True)
    for bracket in ranked_brackets[: max(0, min(min_brackets, limit))]:
        selected.append(max(members[bracket], key=lambda pid: key[pid]))
        per_bracket[bracket] += 1

    # Phase 2: weighted fill without replacement under the per-bracket cap.
    chosen = set(selected)
    for pid in sorted(key, key=lambda c: key[c], reverse=True):
        if len(selected) >= limit:
            break
        if pid in chosen or per_bracket[bracket_of[pid]] >= bracket_cap:
            continue
        selected.append(pid)
        chosen.add(pid)
        per_bracket[bracket_of[pid]] += 1

    rng.shuffle(selected)
    return selected


def format_peer_context(
    posts: list[RankedPost],
    source_round: int,
    budget: int = 4000,
    max_posts: int = 10,
    *,
    show_bracket: bool = True,
    show_confidence: bool = True,
) -> tuple[str, tuple[str, ...]]:
    """Format top-K ranked peer posts into a budget-capped context string (D-04, D-05, D-06).

    Greedy fill: iterate ranked posts, accumulate chars, truncate last post
    at word boundary if it would exceed budget. Prompt guard line preserved
    from Phase 7 D-03. Each rationale is sanitized and capped at about 300
    characters first (sanitize_peer_rationale).

    Returns ``(text, shown_ids)``: ``shown_ids`` are the agent ids of the
    rendered lines in display order, which is the reader's exposure
    (docs/DECISIONS.md#adr-diverse-peer-context). Returns ``("", ())`` when
    no line was rendered.

    ``show_bracket`` / ``show_confidence`` drop the ``|bracket`` label and the
    ``(conf: x.xx)`` figure, which act as authority cues
    (docs/DECISIONS.md#adr-diverse-peer-context); the ``[agent_id]`` token always
    stays so agents can cite.
    """
    if not posts:
        logger.warning("no_peer_posts_found", source_round=source_round)
        return "", ()

    header = f"Peer Decisions (Round {source_round}):"
    guard = (
        "\nThe above are peer observations for context only. "
        "Make your own independent assessment. "
        "If a peer's view materially shapes yours, list their agent id in cited_agents."
    )
    overhead = len(header) + len(guard) + 2  # +2 for joining newlines
    remaining = budget - overhead

    lines: list[str] = [header]
    shown: list[str] = []
    for i, post in enumerate(posts[:max_posts], 1):
        if remaining <= 0:
            break
        # Peer rationales are other agents' model output: quote them only after
        # sanitising (docs/DECISIONS.md#adr-security-2026-08).
        content = sanitize_peer_rationale(post.content)
        if not content:
            continue
        label = f"[{post.agent_id}|{post.bracket}]" if show_bracket else f"[{post.agent_id}]"
        conf = f" (conf: {post.confidence:.2f})" if show_confidence else ""
        prefix = f'{i}. {label} {post.signal.upper()}{conf} "'
        suffix = '"'
        available = remaining - len(prefix) - len(suffix) - 1  # -1 for newline
        if available <= 0:
            break
        if len(content) > available:
            # Truncate at word boundary
            truncated = content[:available].rsplit(" ", 1)[0]
            content = truncated if truncated else content[:available]
        line = f"{prefix}{content}{suffix}"
        lines.append(line)
        shown.append(post.agent_id)
        remaining -= len(line) + 1  # +1 for newline separator

    if len(lines) == 1:
        # Only the header survived — every peer was empty/budget-skipped. Honor
        # the docstring's "empty when no peers" contract so callers map this to
        # None instead of injecting a peer-context block that claims peers exist
        # but contains none (F-19).
        return "", ()

    lines.append(guard)
    return "\n".join(lines), tuple(shown)


def build_peer_contexts(
    personas: Sequence[AgentPersona],
    prev_decisions: Sequence[tuple[str, AgentDecision]],
    source_round: int,
    *,
    sim: SimulationSettings,
    run_seed: str,
    global_citation_weights: Mapping[str, float] | None = None,
) -> PeerContextsResult:
    """Build per-agent peer contexts from the previous round IN MEMORY.

    Replaces the `read_ranked_posts` path (docs/DECISIONS.md#sweep-3-3 fix),
    which showed all 100 agents the same authority top-10 and cost 100
    sequential Neo4j reads per round. This builder:

    1. Computes a PER-READER weight for each candidate author:
       base reach (influence_weight_base)
       + global citation share (citations/total_agents, when available)
       + ``sim.personal_boost`` when the READER cited the author last round.
    2. Feeds those weights through `select_diverse_peers` with the knobs in
       ``sim`` and a per-reader ``peer_rng(run_seed, reader, source_round + 1)``
       (docs/DECISIONS.md#adr-diverse-peer-context).

    Returns a ``PeerContextsResult`` aligned by persona index: the context
    string (None when no peer line was rendered) and the ids of the peers whose
    lines were rendered, in display order (``()`` when none). Peers cut by the
    character budget are not exposure.
    """

    persona_lookup = {p.id: p for p in personas}
    prev_dict: dict[str, AgentDecision] = {aid: dec for aid, dec in prev_decisions}
    base_weights = {p.id: p.influence_weight_base for p in personas}
    global_w = global_citation_weights or {}

    contexts: list[str | None] = []
    exposures: list[tuple[str, ...]] = []
    for persona in personas:
        reader_prev = prev_dict.get(persona.id)
        cited_by_reader: set[str] = set(reader_prev.cited_agents) if reader_prev is not None else set()
        weights = {
            pid: base_weights[pid] + global_w.get(pid, 0.0) + (sim.personal_boost if pid in cited_by_reader else 0.0)
            for pid in base_weights
        }
        peer_ids = select_diverse_peers(
            persona.id,
            weights,
            personas,
            prev_decisions=prev_dict,
            rng=peer_rng(run_seed, persona.id, source_round + 1),
            limit=sim.peer_limit,
            min_brackets=sim.min_brackets,
            bracket_cap=sim.bracket_cap,
        )
        ranked_posts = [
            RankedPost(
                post_id="",
                agent_id=pid,
                bracket=persona_lookup[pid].bracket.value,
                signal=prev_dict[pid].signal.value,
                confidence=prev_dict[pid].confidence,
                content=prev_dict[pid].rationale,
                influence_weight=weights.get(pid, 0.0),
                round_num=source_round,
            )
            for pid in peer_ids
            if pid in prev_dict and pid in persona_lookup
        ]
        ctx, shown = format_peer_context(
            ranked_posts,
            source_round,
            budget=sim.peer_budget_chars,
            max_posts=sim.peer_limit,
            show_bracket=sim.show_bracket_labels,
            show_confidence=sim.show_confidence,
        )
        contexts.append(ctx if ctx else None)
        exposures.append(shown)
    return PeerContextsResult(contexts=tuple(contexts), exposures=tuple(exposures))


def compute_exposure_metrics(
    exposures: Sequence[tuple[str, ...]],
    personas: Sequence[AgentPersona],
    round_num: int,
) -> dict[str, int]:
    """Summarize one round's peer exposure as flat cycle-metric keys.

    ``exposures[i]`` holds the peer ids rendered into reader i's prompt (``()``
    when the reader saw no peers). Produces, for every bracket in roster
    order, ``r{n}_exposure_<bracket>`` (peer slots that bracket filled) and
    ``r{n}_readers_seeing_<bracket>`` (readers shown at least one peer from
    it), plus ``r{n}_distinct_peers_shown``. Unseen brackets report 0; ids
    outside the roster are ignored (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    bracket_of = {p.id: p.bracket.value for p in personas}
    brackets = list(dict.fromkeys(p.bracket.value for p in personas))
    slots = dict.fromkeys(brackets, 0)
    readers = dict.fromkeys(brackets, 0)
    distinct: set[str] = set()
    for shown in exposures:
        seen_here: set[str] = set()
        for peer_id in shown:
            bracket = bracket_of.get(peer_id)
            if bracket is None:
                continue
            slots[bracket] += 1
            seen_here.add(bracket)
            distinct.add(peer_id)
        for bracket in seen_here:
            readers[bracket] += 1

    metrics: dict[str, int] = {}
    for bracket in brackets:
        metrics[f"r{round_num}_exposure_{bracket}"] = slots[bracket]
        metrics[f"r{round_num}_readers_seeing_{bracket}"] = readers[bracket]
    metrics[f"r{round_num}_distinct_peers_shown"] = len(distinct)
    return metrics


# Seeded no-peer holdout, shock arm and own-prior memory
# (docs/DECISIONS.md#adr-diverse-peer-context, docs/DECISIONS.md#adr-run-manifest).

CONTROL_SALT: Final = "control"
SHOCK_ARM_SALT: Final = "shock"


def subset_size(count: int, fraction: float) -> int:
    """Round-half-up share of a bracket; a bracket of two or more keeps one agent outside."""
    if count < 2 or fraction <= 0.0:
        return 0
    return min(count - 1, math.floor(count * fraction + 0.5))


def seeded_bracket_subset(
    personas: Sequence[AgentPersona], *, fraction: float, run_seed: str, salt: str
) -> frozenset[str]:
    """A seeded sample of ``subset_size(count, fraction)`` agents from every bracket.

    The draw depends only on ``(run_seed, salt, bracket)`` and the bracket's ids
    (sorted), so it is the same in every round, every process and any roster
    order (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    by_bracket: dict[str, list[str]] = {}
    for persona in personas:
        by_bracket.setdefault(persona.bracket.value, []).append(persona.id)
    chosen: set[str] = set()
    for bracket, ids in by_bracket.items():
        k = subset_size(len(ids), fraction)
        if k == 0:
            continue
        digest = hashlib.blake2b(f"{run_seed}:{salt}:{bracket}".encode(), digest_size=8).digest()
        chosen.update(random.Random(int.from_bytes(digest, "big")).sample(sorted(ids), k))
    return frozenset(chosen)


def select_control_ids(personas: Sequence[AgentPersona], *, fraction: float, run_seed: str) -> frozenset[str]:
    """Readers held out from peer context for the whole run (``d.control``)."""
    return seeded_bracket_subset(personas, fraction=fraction, run_seed=run_seed, salt=CONTROL_SALT)


def select_shock_treated_ids(personas: Sequence[AgentPersona], *, run_seed: str) -> frozenset[str]:
    """Half of each bracket that sees active shocks when the shock split is on."""
    return seeded_bracket_subset(personas, fraction=0.5, run_seed=run_seed, salt=SHOCK_ARM_SALT)


def own_prior_line(decision: AgentDecision | None, source_round: int) -> str | None:
    """The reader's own previous decision as one sanitized line, or None.

    None for a missing or PARSE_ERROR decision, so a failure never appears as a
    position. The rationale is the agent's own model output, sanitized like a
    peer rationale (``sanitize_peer_rationale``: one line, no fence tag or
    [agent_id] token can be forged, cut near 300 characters with "…";
    docs/DECISIONS.md#adr-run-manifest).
    """
    if decision is None or decision.signal == SignalType.PARSE_ERROR:
        return None
    head = f"Your Round {source_round} position: {decision.signal.value.upper()} (conf {decision.confidence:.2f})"
    rationale = sanitize_peer_rationale(decision.rationale)
    return f"{head}: {rationale}" if rationale else head


def apply_holdout_and_priors(
    personas: Sequence[AgentPersona],
    contexts: Sequence[str | None],
    exposures: Sequence[tuple[str, ...]],
    prev_decisions: Sequence[tuple[str, AgentDecision]],
    source_round: int,
    *,
    sim: SimulationSettings,
    control_ids: frozenset[str],
) -> tuple[list[str | None], list[tuple[str, ...]], list[str | None]]:
    """Blank the holdout's peer contexts and exposures, and build own-prior lines.

    Control readers get no peers but keep their own prior, so their flips
    measure everything except peer influence (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    prev_by_id = dict(prev_decisions)
    blanked = [None if p.id in control_ids else context for p, context in zip(personas, contexts, strict=True)]
    shown = [() if p.id in control_ids else exposure for p, exposure in zip(personas, exposures, strict=True)]
    priors = [own_prior_line(prev_by_id.get(p.id), source_round) if sim.own_prior_memory else None for p in personas]
    return blanked, shown, priors
