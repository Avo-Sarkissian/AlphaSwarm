"""Fictional report read rows (GraphStateManager report-read shapes) and a fake graph."""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Final

REPORT_CYCLE: Final = "00000000-0000-4000-8000-0000000000a1"
REPORT_RUMOR: Final = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."

CONSENSUS: Final[dict[str, Any]] = {
    "buy_count": 52,
    "sell_count": 21,
    "hold_count": 24,
    "parse_error_count": 3,
    "total": 100,
}
TIMELINE: Final[list[dict[str, Any]]] = [
    {"round_num": 1, "buy_count": 40, "sell_count": 30, "hold_count": 28, "parse_error_count": 2, "total": 100},
    {"round_num": 2, "buy_count": 48, "sell_count": 24, "hold_count": 26, "parse_error_count": 2, "total": 100},
    {"round_num": 3, "buy_count": 52, "sell_count": 21, "hold_count": 24, "parse_error_count": 3, "total": 100},
]
BRACKETS: Final[list[dict[str, Any]]] = [
    {
        "bracket": "sell_side",
        "display_name": "Sell-Side",
        "buy_count": 7,
        "sell_count": 1,
        "hold_count": 2,
        "total": 10,
        "avg_confidence": 0.71,
        "avg_sentiment": 0.42,
        "majority": "buy",
    },
    {
        "bracket": "shorts",
        "display_name": "Shorts",
        "buy_count": 1,
        "sell_count": 5,
        "hold_count": 1,
        "total": 7,
        "avg_confidence": 0.66,
        "avg_sentiment": -0.31,
        "majority": "sell",
    },
]
DISSENTERS: Final[list[dict[str, Any]]] = [
    {"agent_id": "shorts_02", "name": "Shorts 2", "bracket": "shorts", "signal": "buy", "bracket_majority": "sell"},
]
INFLUENCE: Final[list[dict[str, Any]]] = [
    {
        "agent_id": "sell_side_03",
        "name": "Sell-Side 3",
        "bracket": "sell_side",
        "citation_count": 9,
        "influence_share": 0.09,
    },
    {
        "agent_id": "narrators_01",
        "name": "Narrators 1",
        "bracket": "narrators",
        "citation_count": 6,
        "influence_share": 0.06,
    },
]
FLIPS: Final[list[dict[str, Any]]] = [
    {
        "agent_id": "degens_04",
        "name": "Degens 4",
        "bracket": "degens",
        "round_num": 2,
        "flip_type": "hold_to_buy",
        "final_signal": "buy",
    },
]
ENTITIES: Final[list[dict[str, Any]]] = [
    {
        "entity_name": "ZZZT Holdings",
        "entity_type": "company",
        "avg_sentiment": 0.44,
        "mention_count": 31,
        "buy_mentions": 20,
        "sell_mentions": 5,
        "hold_mentions": 6,
    },
]
SHOCK: Final[dict[str, Any]] = {
    "shock_text": "QQQX Robotics guides revenue 12% lower",
    "injected_before_round": 2,
    "pre_dominant": "buy",
    "post_dominant": "hold",
    "pivot_count": 14,
    "pivot_rate": 0.14,
    "bracket_pivots": [],
}


class FakeReportGraph:
    """GraphStateManager stand-in for the report reads; records (read, cycle_id)."""

    def __init__(
        self,
        *,
        timeline: list[dict[str, Any]] | None = None,
        shock: bool = False,
        seed: str | None = REPORT_RUMOR,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._timeline = copy.deepcopy(TIMELINE if timeline is None else timeline)
        self._shock = shock
        self._seed = seed

    async def _read(self, name: str, cycle_id: str, value: Any) -> Any:
        self.calls.append((name, cycle_id))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return copy.deepcopy(value)

    async def read_consensus_summary(self, cycle_id: str) -> Any:
        return await self._read("read_consensus_summary", cycle_id, CONSENSUS)

    async def read_round_timeline(self, cycle_id: str) -> Any:
        return await self._read("read_round_timeline", cycle_id, self._timeline)

    async def read_bracket_narratives(self, cycle_id: str) -> Any:
        return await self._read("read_bracket_narratives", cycle_id, BRACKETS)

    async def read_key_dissenters(self, cycle_id: str) -> Any:
        return await self._read("read_key_dissenters", cycle_id, DISSENTERS)

    async def read_influence_leaders(self, cycle_id: str) -> Any:
        return await self._read("read_influence_leaders", cycle_id, INFLUENCE)

    async def read_signal_flips(self, cycle_id: str) -> Any:
        return await self._read("read_signal_flips", cycle_id, FLIPS)

    async def read_entity_impact(self, cycle_id: str) -> Any:
        return await self._read("read_entity_impact", cycle_id, ENTITIES)

    async def read_shock_event(self, cycle_id: str) -> Any:
        event = {"shock_text": SHOCK["shock_text"], "injected_before_round": 2} if self._shock else None
        return await self._read("read_shock_event", cycle_id, event)

    async def read_shock_impact(self, cycle_id: str) -> Any:
        return await self._read("read_shock_impact", cycle_id, SHOCK)

    async def read_cycle_seed(self, cycle_id: str) -> Any:
        return await self._read("read_cycle_seed", cycle_id, self._seed)
