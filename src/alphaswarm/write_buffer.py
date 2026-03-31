"""Write-behind buffer for RationaleEpisode graph writes (D-01, D-02).

Agents push EpisodeRecords into an asyncio.Queue as they complete inference.
A single flush() call drains the queue and delegates batch writes to
GraphStateManager. TUI sees per-agent updates immediately via StateStore;
Neo4j receives efficient batch writes at round boundaries.

ORDERING CONSTRAINT: flush() MUST be called AFTER write_decisions() completes.
The MATCH on Decision {decision_id} in the episode write requires the Decision
node to already exist in Neo4j.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from alphaswarm.types import FlipType, SignalType

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager

log = structlog.get_logger(component="write_buffer")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeRecord:
    """Immutable record capturing a single agent inference episode.

    Passed to WriteBuffer.push() immediately after each agent decision.
    Consumed in batches by WriteBuffer.flush() at round boundaries.
    """

    decision_id: str          # links to parent Decision node via HAS_EPISODE edge
    agent_id: str
    rationale: str
    peer_context_received: str  # full formatted context string; "" for Round 1 (Pitfall 3)
    flip_type: str              # FlipType.value string (stored as string for Neo4j compat)
    round_num: int
    cycle_id: str


# ---------------------------------------------------------------------------
# Pure function
# ---------------------------------------------------------------------------


def compute_flip_type(
    prev_signal: SignalType | None,
    curr_signal: SignalType,
) -> FlipType:
    """Compute the FlipType describing the transition from prev to curr signal.

    Returns FlipType.NONE when:
    - prev_signal is None (Round 1, no previous signal exists)
    - prev_signal is PARSE_ERROR (previous round failed to parse)
    - curr_signal is PARSE_ERROR (current round failed to parse)
    - prev_signal == curr_signal (no change, not a flip)

    Otherwise returns the matching FlipType enum value via key construction.
    """
    if prev_signal is None:
        return FlipType.NONE
    if prev_signal == SignalType.PARSE_ERROR:
        return FlipType.NONE
    if curr_signal == SignalType.PARSE_ERROR:
        return FlipType.NONE
    if prev_signal == curr_signal:
        return FlipType.NONE
    key = f"{prev_signal.value}_to_{curr_signal.value}"
    return FlipType(key)


# ---------------------------------------------------------------------------
# WriteBuffer
# ---------------------------------------------------------------------------


class WriteBuffer:
    """Async write-behind buffer for EpisodeRecord graph writes.

    Agents call push() immediately after inference (non-blocking, fire-and-forget).
    The simulation runner calls flush() once per round boundary after write_decisions()
    completes, ensuring Decision nodes exist in Neo4j before episode writes reference them.

    Drop-oldest policy: when the queue is full, the oldest record is discarded and
    the new record is enqueued. Mirrors the pattern used in StateStore for rationale
    buffering.
    """

    def __init__(self, maxsize: int = 200) -> None:
        self._queue: asyncio.Queue[EpisodeRecord] = asyncio.Queue(maxsize=maxsize)
        self._log = structlog.get_logger(component="write_buffer")

    async def push(self, record: EpisodeRecord) -> None:
        """Add a record to the internal queue.

        If the queue is full, the oldest record is dropped and the new record
        is enqueued (drop-oldest policy, same as StateStore._rationale_queue).
        """
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(record)
            self._log.warning(
                "write_buffer.drop_oldest",
                agent_id=record.agent_id,
                cycle_id=record.cycle_id,
            )

    def drain(self) -> list[EpisodeRecord]:
        """Remove and return all queued records in FIFO order.

        Returns an empty list if the queue is empty.
        Non-blocking: uses get_nowait() in a loop.
        """
        records: list[EpisodeRecord] = []
        while True:
            try:
                records.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return records

    async def flush(
        self,
        graph_manager: GraphStateManager,
        entity_names: list[str],
    ) -> int:
        """Drain the queue and delegate batch writes to GraphStateManager.

        Calls write_rationale_episodes() then write_narrative_edges().
        Returns the number of records flushed.
        Returns 0 without calling graph_manager if the queue is empty.

        ORDERING CONSTRAINT: caller must ensure write_decisions() completed
        before calling flush() so Decision nodes exist in Neo4j.
        """
        records = self.drain()
        if not records:
            self._log.debug("write_buffer.flush.empty")
            return 0

        await graph_manager.write_rationale_episodes(records)
        await graph_manager.write_narrative_edges(records, entity_names)

        self._log.info("write_buffer.flushed", count=len(records))
        return len(records)
