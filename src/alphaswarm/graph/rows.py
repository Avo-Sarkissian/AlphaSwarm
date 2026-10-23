"""Typed shapes returned by and passed between the graph modules.

Read methods return these TypedDicts; templates, services and the web layer read
only these keys (docs/DECISIONS.md#adr-neo4j-schema). TxRunner is how the
operation modules receive the facade's `_read` / `_write` helpers
(docs/DECISIONS.md#p4-d-07). Cypher fragments shared by more than one graph
module also live here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict, TypeVar

from alphaswarm.influence import BracketPivotRow, PivotAgentRow, ShockImpactRow

__all__ = [
    "AgentDecisionRow",
    "BracketNarrativeRow",
    "BracketPivotRow",
    "BracketRoundRow",
    "CompletedCycleRow",
    "ConsensusSummaryRow",
    "CycleStatus",
    "EntityImpactRow",
    "InfluenceEdgeRow",
    "InfluenceLeaderRow",
    "KeyDissenterRow",
    "PersistRoundResult",
    "PivotAgentRow",
    "RationaleRoundRow",
    "RoundTimelineRow",
    "ShockImpactRow",
    "SignalFlipRow",
    "TxRunner",
]

T = TypeVar("T")

CycleStatus = Literal["running", "complete", "failed", "cancelled"]


class TxRunner(Protocol):
    """GraphStateManager._read or ._write: run *fn* in a managed transaction.

    The runner opens the session, applies the query timeout and maps driver
    errors to the GraphError family; *op* names the operation in errors and logs.
    """

    def __call__(self, fn: Callable[..., Awaitable[T]], /, *args: Any, op: str) -> Awaitable[T]: ...


@dataclass(frozen=True)
class PersistRoundResult:
    """What one persist_round transaction wrote (docs/DECISIONS.md#p4-d-08)."""

    decision_ids: tuple[str, ...]
    decisions_written: int
    episodes_written: int
    citations_written: int
    citations_dropped: int  # CITED targets that matched no Agent -> r{n}_citations_dropped
    references_written: int


class ConsensusSummaryRow(TypedDict):
    """Final-round counts; total = buy + sell + hold + parse_error."""

    buy_count: int
    sell_count: int
    hold_count: int
    parse_error_count: int
    total: int


class RoundTimelineRow(TypedDict):
    round_num: int
    buy_count: int
    sell_count: int
    hold_count: int
    parse_error_count: int
    total: int


class BracketNarrativeRow(TypedDict):
    """Final-round stance per bracket; totals and averages exclude parse errors."""

    bracket: str
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float
    majority: str | None


class KeyDissenterRow(TypedDict):
    agent_id: str
    name: str
    bracket: str
    signal: str
    bracket_majority: str


class InfluenceLeaderRow(TypedDict):
    agent_id: str
    name: str
    bracket: str
    citation_count: int
    influence_share: float


class SignalFlipRow(TypedDict):
    agent_id: str
    name: str
    bracket: str
    round_num: int
    flip_type: str
    final_signal: str


class EntityImpactRow(TypedDict):
    entity_name: str
    entity_type: str
    avg_sentiment: float
    mention_count: int
    buy_mentions: int
    sell_mentions: int
    hold_mentions: int


class InfluenceEdgeRow(TypedDict):
    source_id: str  # citing agent
    target_id: str  # cited agent
    weight: float


class CompletedCycleRow(TypedDict):
    """One complete cycle with the run metrics stamped on its Cycle node.

    Metric columns are None for cycles recorded before metrics existed
    (docs/DECISIONS.md#adr-cycle-metrics).
    """

    cycle_id: str
    created_at: str
    seed_rumor: str
    round_count: int
    status: str
    final_buy: int | None
    final_sell: int | None
    final_hold: int | None
    total_flips: int | None
    total_seconds: float | None
    agent_count: int | None


class AgentDecisionRow(TypedDict):
    """One stored decision of one agent; signal is lowercase."""

    round_num: int
    signal: str
    confidence: float
    sentiment: float
    rationale: str
    cited_agents: list[str]


class BracketRoundRow(TypedDict):
    """Replay per-round bracket row; totals and averages exclude parse errors."""

    bracket: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float


class RationaleRoundRow(TypedDict):
    agent_id: str
    signal: str
    rationale: str
    round_num: int
