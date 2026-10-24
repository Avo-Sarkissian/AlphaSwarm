"""Per-holding swarm evidence from final-round decisions (docs/DECISIONS.md#adr-grounded-advisory)."""

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType

import pytest

from alphaswarm.advisory.evidence import (
    MIN_SWARM_SUPPORT,
    compute_swarm_evidence,
    swarm_consensus_summary,
)
from alphaswarm.advisory.sector_map import SectorMap
from alphaswarm.graph.rows import EvidenceEntityRow, FinalDecisionRow

ZZZT = EvidenceEntityRow(name="ZZZT Holdings", type="company", ticker="ZZZT")
ZZZT_UNRESOLVED = EvidenceEntityRow(name="ZZZT Holdings", type="company", ticker=None)
QQQX = EvidenceEntityRow(name="QQQX Robotics", type="company", ticker="QQQX")
SECTOR = EvidenceEntityRow(name="Industrial Automation", type="sector", ticker=None)
HELD = {"ZZZT", "XQZW"}


def _row(
    agent_id: str,
    signal: str,
    confidence: float,
    entities: Sequence[EvidenceEntityRow],
    *,
    sentiment: float = 0.0,
    bracket: str = "quants",
    reach: float = 0.55,
) -> FinalDecisionRow:
    return FinalDecisionRow(
        agent_id=agent_id,
        bracket=bracket,
        reach=reach,
        signal=signal,
        confidence=confidence,
        sentiment=sentiment,
        entities=list(entities),
    )


def test_threshold_is_three_agents() -> None:
    assert MIN_SWARM_SUPPORT == 3


def test_support_below_threshold_has_no_swarm_signal() -> None:
    rows = [_row("quants_01", "buy", 0.9, [ZZZT], sentiment=0.4), _row("quants_02", "buy", 0.8, [ZZZT])]
    evidence = compute_swarm_evidence(rows, HELD)["ZZZT"]
    assert evidence.support == 2
    assert evidence.signal is None and evidence.confidence is None
    assert evidence.sentiment == pytest.approx(0.2)
    assert evidence.agent_ids == ("quants_01", "quants_02")


def test_signal_is_the_lean_of_the_headcount_net_score() -> None:
    rows = [
        _row("sell_side_01", "buy", 0.8, [ZZZT], bracket="sell_side", reach=0.75),
        _row("sell_side_02", "buy", 0.8, [ZZZT], bracket="sell_side", reach=0.75),
        _row("quants_01", "buy", 0.8, [ZZZT]),
        _row("shorts_01", "sell", 0.6, [ZZZT], bracket="shorts", reach=0.6),
    ]
    evidence = compute_swarm_evidence(rows, HELD)["ZZZT"]
    assert (evidence.support, evidence.buy, evidence.sell, evidence.hold) == (4, 3, 1, 0)
    assert evidence.net_score == pytest.approx(0.45)  # (3 * 0.8 - 0.6) / 4
    assert evidence.signal == "BUY"
    assert evidence.confidence == pytest.approx(0.6)  # (3 * 0.8) / 4


def test_low_conviction_split_is_hold_with_zero_confidence() -> None:
    rows = [
        _row("quants_01", "buy", 0.3, [ZZZT]),
        _row("quants_02", "buy", 0.3, [ZZZT]),
        _row("quants_03", "sell", 0.3, [ZZZT]),
        _row("quants_04", "sell", 0.3, [ZZZT]),
    ]
    evidence = compute_swarm_evidence(rows, HELD)["ZZZT"]
    assert evidence.signal == "HOLD"
    assert evidence.confidence == 0.0


def test_parse_errors_non_held_and_sector_entities_are_ignored() -> None:
    rows = [
        _row("degens_01", "parse_error", 0.0, [ZZZT]),
        _row("quants_01", "buy", 0.7, [QQQX]),
        _row("quants_02", "buy", 0.7, [SECTOR]),
    ]
    assert compute_swarm_evidence(rows, HELD) == {}


def test_resolved_ticker_wins_and_aliases_only_fill_gaps() -> None:
    aliases = SectorMap(aliases=MappingProxyType({"zzzt holdings": "ZZZT", "qqqx robotics": "XQZW"}))
    rows = [
        _row("quants_01", "buy", 0.7, [ZZZT_UNRESOLVED]),  # alias -> ZZZT
        _row("quants_02", "buy", 0.7, [QQQX]),  # resolved to a non-held ticker: never re-aliased
    ]
    evidence = compute_swarm_evidence(rows, HELD, sector_map=aliases)
    assert set(evidence) == {"ZZZT"}
    assert evidence["ZZZT"].agent_ids == ("quants_01",)


def test_an_agent_counts_once_per_ticker() -> None:
    rows = [_row("quants_01", "sell", 0.5, [ZZZT, ZZZT_UNRESOLVED])]
    aliases = SectorMap(aliases=MappingProxyType({"zzzt holdings": "ZZZT"}))
    assert compute_swarm_evidence(rows, HELD, sector_map=aliases)["ZZZT"].support == 1


def test_held_tickers_are_matched_case_insensitively() -> None:
    rows = [_row(f"quants_0{i}", "hold", 0.9, [ZZZT]) for i in range(1, 4)]
    evidence = compute_swarm_evidence(rows, {"zzzt"})
    assert evidence["ZZZT"].signal == "HOLD"
    assert evidence["ZZZT"].confidence == pytest.approx(0.9)


def test_swarm_consensus_summary_reports_all_three_weightings() -> None:
    rows = [
        _row("sell_side_01", "buy", 0.8, [], bracket="sell_side", reach=0.75),
        _row("shorts_01", "sell", 0.6, [], bracket="shorts", reach=0.6),
        _row("degens_01", "parse_error", 0.0, [], bracket="degens", reach=0.5),
    ]
    summary = swarm_consensus_summary(rows)
    assert summary.startswith("HOLD (net score +0.10 headcount")
    assert "2 decided agents" in summary
    assert swarm_consensus_summary([]) == "no decided agents in the final round"
