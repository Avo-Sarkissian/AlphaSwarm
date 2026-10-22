"""Pure measurement functions for cycles and experiments.

Fast-track subset: the control/treated flip split. No I/O
(docs/DECISIONS.md#adr-diverse-peer-context).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from alphaswarm.types import AgentDecision, SignalType

Pairs = Sequence[tuple[str, AgentDecision]]


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
