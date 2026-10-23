"""Recoverable model output is normalised, not thrown away (docs/DECISIONS.md#adr-structured-output)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from alphaswarm.types import (
    AgentDecision,
    EntityType,
    SeedEntity,
    SeedEvent,
    SignalType,
    normalize_signed_unit,
    normalize_token,
    normalize_unit_interval,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.85, 0.85),
        (85, 0.85),
        ("85", 0.85),
        (50.0, 0.5),
        (1.2, 1.0),
        (1.5, 1.0),
        (-0.2, 0.0),
        (150, 1.0),
        ("0.4", 0.4),
    ],
)
def test_unit_interval(raw: object, expected: float) -> None:
    assert normalize_unit_interval(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    ["high", True, None, [0.5], 10**400],
    ids=["word", "bool", "none", "list", "huge-int"],
)
def test_unit_interval_passes_non_numbers_through(raw: object) -> None:
    assert normalize_unit_interval(raw) is raw


def test_unit_interval_leaves_nan_for_pydantic() -> None:
    value = normalize_unit_interval(float("nan"))
    assert isinstance(value, float) and math.isnan(value)


@pytest.mark.parametrize(("raw", "expected"), [(1.7, 1.0), (-3, -1.0), (0.25, 0.25), ("-0.5", -0.5)])
def test_signed_unit(raw: object, expected: float) -> None:
    assert normalize_signed_unit(raw) == pytest.approx(expected)


def test_token() -> None:
    assert normalize_token("  BUY ") == "buy"
    assert normalize_token(3) == 3


def test_agent_decision_recovers_upper_case_and_percent_confidence() -> None:
    decision = AgentDecision.model_validate(
        {"signal": "BUY", "confidence": 85, "sentiment": 1.7, "rationale": "ZZZT deal is accretive"}
    )
    assert decision.signal is SignalType.BUY
    assert decision.confidence == pytest.approx(0.85)
    assert decision.sentiment == 1.0


def test_agent_decision_still_rejects_unknown_signal_and_nan() -> None:
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"signal": "maybe", "confidence": 0.5})
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"signal": "buy", "confidence": float("nan")})


def test_seed_entity_and_event_are_clamped() -> None:
    entity = SeedEntity.model_validate(
        {"name": "ZZZT Holdings", "type": "Company", "relevance": 1.5, "sentiment": -1.5}
    )
    assert entity.type is EntityType.COMPANY
    assert (entity.relevance, entity.sentiment) == (1.0, -1.0)
    event = SeedEvent(raw_rumor="r", entities=[entity], overall_sentiment=5.0)
    assert event.overall_sentiment == 1.0
