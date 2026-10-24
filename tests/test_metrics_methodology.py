"""Round estimators on hand-built rounds (docs/DECISIONS.md#adr-consensus-estimators)."""

from __future__ import annotations

import math

import pytest

from alphaswarm.metrics import (
    bracket_signal_table,
    citation_gini,
    conformity_rate,
    mean_abs_confidence_delta,
    polarization,
    signal_entropy,
    transition_matrix,
)
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.types import AgentDecision, SignalType

B, S, H, E = SignalType.BUY, SignalType.SELL, SignalType.HOLD, SignalType.PARSE_ERROR
PERSONAS = generate_personas(load_bracket_configs())


def _d(signal: SignalType, confidence: float = 0.5, cited: tuple[str, ...] = ()) -> AgentDecision:
    return AgentDecision(
        signal=signal,
        confidence=confidence,
        sentiment=0.0,
        rationale="fictional",
        cited_agents=list(cited),
    )


def test_polarization_extremes() -> None:
    assert polarization([("a", _d(B)), ("b", _d(B)), ("c", _d(S)), ("d", _d(S))]) == 1.0
    assert polarization([("a", _d(B)), ("b", _d(S)), ("c", _d(H)), ("d", _d(H))]) == 0.25
    assert polarization([("a", _d(H)), ("b", _d(H))]) == 0.0


def test_signal_entropy_matches_consensus_dispersion() -> None:
    assert signal_entropy([("a", _d(B)), ("b", _d(S)), ("c", _d(H))]) == pytest.approx(1.0)


def test_bracket_signal_table_is_zero_filled_in_config_order() -> None:
    table = bracket_signal_table(
        [("sell_side_01", _d(B)), ("sell_side_02", _d(E)), ("shorts_01", _d(S))],
        PERSONAS,
    )
    assert list(table)[:3] == ["institutions", "sell_side", "event_driven"]
    assert len(table) == 10
    assert table["sell_side"] == {"buy": 1, "sell": 0, "hold": 0, "parse_error": 1}
    assert table["shorts"]["sell"] == 1
    assert sum(table["macro"].values()) == 0


def test_transition_matrix_skips_failures_and_newcomers() -> None:
    prev = [("a", _d(B)), ("b", _d(B)), ("c", _d(S)), ("d", _d(H)), ("e", _d(E))]
    curr = [("a", _d(B)), ("b", _d(S)), ("c", _d(S)), ("d", _d(B)), ("e", _d(B)), ("f", _d(B))]
    matrix = transition_matrix(prev, curr)
    assert len(matrix) == 9
    assert matrix[("buy", "buy")] == 1
    assert matrix[("buy", "sell")] == 1
    assert matrix[("sell", "sell")] == 1
    assert matrix[("hold", "buy")] == 1
    assert sum(matrix.values()) == 4


def test_conformity_counts_movers_toward_the_shown_majority() -> None:
    prev = [
        ("a", _d(S)),
        ("b", _d(B)),
        ("c", _d(B)),
        ("d", _d(B)),
        ("e", _d(S)),
        ("f", _d(H)),
        ("g", _d(B)),
        ("h", _d(B)),
        ("i", _d(H)),
    ]
    curr = [
        ("a", _d(B)),  # shown b, c, e -> majority BUY; moved to BUY: toward
        ("e", _d(H)),  # shown b, c, d -> majority BUY; moved to HOLD: away
        ("f", _d(S)),  # shown nobody: skipped
        ("g", _d(B)),  # did not move: skipped
        ("h", _d(S)),  # shown a, e -> majority SELL; moved to SELL: toward
        ("i", _d(B)),  # shown a, b -> SELL/BUY tie: skipped
    ]
    exposures = {"a": ("b", "c", "e"), "e": ("b", "c", "d"), "f": (), "h": ("a", "e"), "i": ("a", "b")}
    assert conformity_rate(prev, curr, exposures) == pytest.approx(2 / 3)


def test_mean_abs_confidence_delta() -> None:
    prev = [("a", _d(B, 0.5)), ("b", _d(B, 0.8)), ("c", _d(S, 0.4)), ("d", _d(E, 0.0))]
    curr = [("a", _d(B, 0.7)), ("b", _d(S, 0.6)), ("c", _d(S, 0.4)), ("d", _d(B, 0.9))]
    assert mean_abs_confidence_delta(prev, curr) == pytest.approx(0.4 / 3)


def test_citation_gini_inequality() -> None:
    four = PERSONAS[:4]
    ids = [p.id for p in four]
    concentrated = [(ids[0], _d(B, cited=(ids[3],))), (ids[1], _d(B, cited=(ids[3], ids[3])))]
    concentrated += [(ids[2], _d(B, cited=(ids[3],))), (ids[3], _d(B, cited=(ids[3],)))]
    # ids[3] receives 3 citations (duplicates and the self-citation do not count): [0, 0, 0, 3]
    assert citation_gini(concentrated, four) == pytest.approx(0.75)
    ring = [(ids[i], _d(B, cited=(ids[(i + 1) % 4],))) for i in range(4)]
    assert citation_gini(ring, four) == pytest.approx(0.0)


def test_estimators_with_no_decided_agents() -> None:
    failed = [("a", _d(E)), ("b", _d(E))]
    assert signal_entropy(failed) == 0.0
    assert polarization(failed) == 0.0
    assert conformity_rate(failed, failed, {"a": ("b",)}) is None
    assert mean_abs_confidence_delta(failed, failed) is None
    assert citation_gini([(PERSONAS[0].id, _d(E, cited=(PERSONAS[1].id,)))], PERSONAS) is None
    assert set(transition_matrix(failed, failed).values()) == {0}
    assert all(math.isfinite(v) for v in (signal_entropy(failed), polarization(failed)))
