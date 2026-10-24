"""Cross-language consensus fixture: Python is the reference (docs/DECISIONS.md#adr-consensus-estimators)."""

from __future__ import annotations

from pathlib import Path

from alphaswarm.consensus import WEIGHTINGS, Vote, net_score_votes
from alphaswarm.types import SignalType
from tests.support.golden import assert_golden_file

FIXTURE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "__tests__" / "fixtures" / "consensus_cases.json"

# (bracket, signal, confidence, reach) with the real DEFAULT_BRACKETS reach values.
CASES: dict[str, list[tuple[str, str, float, float]]] = {
    "mixed": [("sell_side", "buy", 0.8, 0.75)] * 3 + [("shorts", "sell", 0.6, 0.6), ("quants", "hold", 0.5, 0.55)],
    "unanimous_sell": [("degens", "sell", 0.9, 0.5), ("degens", "sell", 0.7, 0.5)],
    "one_heavy_bracket": [("institutions", "buy", 0.4, 0.65)] * 6 + [("allocators", "sell", 0.9, 0.6)],
    "empty": [],
}


def _cases() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for name, raw in CASES.items():
        votes = [
            Vote(f"{bracket}_{i + 1:02d}", bracket, SignalType(signal), confidence, reach)
            for i, (bracket, signal, confidence, reach) in enumerate(raw)
        ]
        out.append(
            {
                "name": name,
                "votes": [
                    {"bracket": v.bracket, "signal": v.signal.value, "confidence": v.confidence, "reach": v.reach}
                    for v in votes
                ],
                "expected": {w: net_score_votes(votes, weighting=w) for w in WEIGHTINGS},
            }
        )
    return out


def test_consensus_fixture_matches_python() -> None:
    assert_golden_file(FIXTURE, _cases())
